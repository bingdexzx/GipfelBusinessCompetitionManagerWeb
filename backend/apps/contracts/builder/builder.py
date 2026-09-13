"""合同类型代码化建库：用一段简单 Python 代码描述合同类型，产出后端契约 JSON。

一句话用法
----------
    from apps.contracts.builder import ContractType, snapshot, input, add_number

    def build():
        snap = snapshot(7)
        ct = ContractType("steel-sale", "钢材销售合同")

        seller = ct.party("seller", "卖方")
        buyer = ct.party("buyer", "买方")

        amount = ct.input("amount", "成交金额", "number", required=True)
        plate = ct.input("plate", "钢材清单", "materialList", party=seller)

        ct.check(buyer.field("cash") >= amount, error="买方货币资金不足")
        ct.add_number(seller.field("cash"), amount)
        ct.sub_number(buyer.field("cash"), amount)
        ct.add_number(buyer.field("inventory_value"), total_price(plate, at=buyer))
        return ct

产出四份 JSON，直接 POST 到既有的 `/api/contract-types`：

    ct.payload()      # {"key","name",...,"partyRoles","inputSchema","effects","conditions","graph":None}
    ct.build()        # {"partyRoles":[...], "inputSchema":[...], "effects":[...], "conditions":[...]}
    ct.effects_json() # 落库用的 JSON 字符串（与前端可视化编辑器产物同格式）

零新增语义
----------
本库**不引入任何新的引擎语义**：产物就是引擎今天已经在跑的值源与效果 JSON，
`graph` 传 None（后端 `allow_null=True`，引擎从不读它）。因此可逆性
（`revert_contract` 的事件溯源重放）、审计粒度（`ContractFieldEffect` 每字段一行）
完全不受影响。

降低抽象的两处重点
------------------
- **效果**：`add_number` / `append_items` / `sub_dict` / `remove_keys` … 共 11 种具名效果，
  效果名自带字段类型契约。不再用「`op=ADD` 的含义取决于字段类型」这种写法，
  字典的「减数」与「删键」也拆成了两个名字。
- **实体**：`snapshot(7).material("铁矿石").carbon` —— 一层具名访问器，
  属性名对模型真实字段做白名单校验；`entityRef` 需要的隐藏输入项由快照自动生成，
  使用者不再需要手搓。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Sequence

from .effects import (
    EFFECT_KINDS,
    Effect,
    EffectBase,
    add_dict,
    add_number,
    append_items,
    remove_items,
    remove_keys,
    set_dict,
    set_items,
    set_number,
    set_value,
    sub_dict,
    sub_number,
)
from .errors import BuildError, SchemaError
from .values import (
    INPUT_TYPES,
    LIST_INPUT_ENTITY,
    LIST_INPUT_TYPES,
    Value,
    _as_value,
    _party_role,
)

__all__ = [
    "ContractType",
    "PartyRef",
    "FieldRef",
    "Check",
]

#: 公式里可用作标识符的名字（输入项 key 需要是合法标识符才能直接写进表达式）
_NAME_RE = re.compile(r"\W")

#: 这些输入项类型的值是**列表**（直接遍历）；其余（清单类/字典）的值是「名称→数量」字典
_LIST_VALUED_INPUT_TYPES = frozenset({"list", "nodeRoute", "mapNode"})


def _as_list_source(items: Any, input_types: dict[str, str]) -> dict:
    """把「要遍历的东西」转成引擎 FOREACH 需要的**列表**值源。

    - 清单类输入项（值是 `{名称: 数量}` 字典）→ `FORMULA: keys(名称)`，
      循环变量拿到名称；数量用 `ct.item(...)` 取；
    - 列表型输入项（`list` / `nodeRoute` / `mapNode`）→ 原样（值本身就是列表）；
    - 其它值源 → 原样透传（引擎对非列表会跳过循环，体检里也会提示）。
    """
    spec = _as_value(items).to_spec()
    if spec.get("type") == "INPUT" and not spec.get("aggregate"):
        key = str(spec.get("key") or "")
        itype = input_types.get(key, "")
        if itype not in _LIST_VALUED_INPUT_TYPES:
            name = _NAME_RE.sub("_", key)
            return {"type": "FORMULA", "expr": f"keys({name})"}
    return spec


class FieldRef:
    """「某参与方的某产业字段」——效果的写入目标、条件与值的读取来源。

    本类**同时具备两种身份**，因此 `buyer.field("cash")` 既能当写入目标，
    也能直接参与运算与比较：

        ct.add_number(buyer.field("cash"), amount)      # 作为写入目标
        ct.check(buyer.field("cash") >= amount)          # 作为读取来源（编译成 FIELD 值源）

    实现方式是 `__getattr__` 委托给 `value()` 返回的 `Value`：Python 对运算符
    走类型槽位查找（不走实例 `__getattr__`），所以下面显式列出了各运算符。
    """

    __slots__ = ("role", "field_key", "label")

    def __init__(self, role: str, field_key: str, *, label: str = "") -> None:
        self.role = role
        self.field_key = field_key
        self.label = label or f"{role}.{field_key}"

    def __repr__(self) -> str:  # pragma: no cover - 调试可读性
        return f"FieldRef({self.label})"

    def value(self) -> Value:
        """读取该字段当前值（引擎 `FIELD` 值源）。"""
        return Value(
            {"type": "FIELD", "party": self.role, "fieldKey": self.field_key},
            label=self.label,
        )

    # 便捷别名，让读取语义更直观
    def current(self) -> Value:
        return self.value()

    # ---------- 运算符：委托给 value()，使字段可直接写进表达式 ----------

    def __add__(self, other: Any) -> Value:
        return self.value() + other

    def __radd__(self, other: Any) -> Value:
        return _as_value(other) + self.value()

    def __sub__(self, other: Any) -> Value:
        return self.value() - other

    def __rsub__(self, other: Any) -> Value:
        return _as_value(other) - self.value()

    def __mul__(self, other: Any) -> Value:
        return self.value() * other

    def __rmul__(self, other: Any) -> Value:
        return _as_value(other) * self.value()

    def __truediv__(self, other: Any) -> Value:
        return self.value() / other

    def __rtruediv__(self, other: Any) -> Value:
        return _as_value(other) / self.value()

    def __ge__(self, other: Any) -> Value:  # type: ignore[override]
        return self.value() >= other

    def __le__(self, other: Any) -> Value:  # type: ignore[override]
        return self.value() <= other

    def __gt__(self, other: Any) -> Value:  # type: ignore[override]
        return self.value() > other

    def __lt__(self, other: Any) -> Value:  # type: ignore[override]
        return self.value() < other

    def equals(self, other: Any) -> Value:
        return self.value().equals(other)

    def not_equals(self, other: Any) -> Value:
        return self.value().not_equals(other)

    def and_(self, *others: Any) -> Value:
        return self.value().and_(*others)

    def or_(self, *others: Any) -> Value:
        return self.value().or_(*others)

    def not_(self) -> Value:
        return self.value().not_()

    # 对象相等语义保持默认（避免与「字段值相等」混淆）；比较请用 equals()
    __hash__ = object.__hash__


class PartyRef:
    """合同参与方。`ct.party(...)` 的返回值。"""

    __slots__ = ("role", "label", "is_host", "selectable", "industry_type_id", "_ct")

    def __init__(
        self,
        ct: "ContractType",
        role: str,
        label: str,
        *,
        is_host: bool = False,
        selectable: bool = True,
        industry_type_id: int | None = None,
    ) -> None:
        self._ct = ct
        self.role = role
        self.label = label
        self.is_host = bool(is_host)
        self.selectable = bool(selectable)
        self.industry_type_id = industry_type_id

    def __repr__(self) -> str:  # pragma: no cover - 调试可读性
        return f"PartyRef({self.role})"

    def field(self, field_key: str) -> FieldRef:
        """引用该参与方公司的某产业字段。"""
        key = str(field_key or "").strip()
        if not key:
            raise BuildError(f"参与方「{self.label}」的字段名不能为空")
        return FieldRef(self.role, key, label=f"{self.label}.{key}")

    def is_industry(self, industry_type_id: int) -> Value:
        """该参与方公司是否属于指定产业类型（布尔）。"""
        from .values import industry_is

        return industry_is(self, industry_type_id)

    def company_name(self) -> Value:
        """该参与方公司的名称。"""
        from .values import company_name

        return company_name(self)


class Check:
    """一条前置检查（引擎 `conditions`）。"""

    __slots__ = ("spec", "kind", "label")

    def __init__(self, spec: dict, *, kind: str, label: str = "") -> None:
        self.spec = spec
        self.kind = kind
        self.label = label

    def to_spec(self) -> dict:
        return dict(self.spec)

    @property
    def describe(self) -> str:
        return self.label or self.kind

    def __repr__(self) -> str:  # pragma: no cover - 调试可读性
        return f"Check({self.describe})"


class _Block:
    """效果块（`with ct.when(...)` / `with ct.for_each(...)`）。

    块内登记的效果进入本块的列表，退出时**一次性**作为一条嵌套效果挂到父级。
    同一个 IF 的 `then` / `else` 两个块共享同一条 IF 效果（`_owner`），
    因此不会产出两条并列的 IF。
    """

    #: 本块把子效果写进嵌套效果的哪个字段（IF 用 then/else，FOREACH 用 body）
    child_key = "then"

    def __init__(self, ct: "ContractType", spec: dict, *, body: list | None = None, branch: str = "") -> None:
        self._ct = ct
        self._spec = spec
        #: 本块自己的子效果列表；`_spec` 是**共享的** IF/FOREACH 描述（then/else 复用同一条）
        self._body: list = self._spec["_body"] if body is None else body
        self._branch = branch or self._spec.get("_branch") or self.child_key
        self._parent: list = []

    def __enter__(self) -> "_Block":
        # 记下父级列表：退出时把嵌套效果挂到这里（不能用 _stack[-1]，那时已弹出）
        self._parent = self._ct._stack[-1]
        self._ct._stack.append(self._body)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._ct._stack.pop()
        if exc_type is not None:
            return False  # 块内报错：不挂载半成品
        owner: _RawEffect | None = self._spec.get("_owner")
        if owner is None:
            # 第一次退出：把 IF 效果本身挂到父级，并留下引用供 otherwise() 复用
            node = {k: v for k, v in self._spec.items() if not k.startswith("_")}
            node["then"] = [e.to_spec() for e in self._body]
            node.setdefault("else", [])
            raw = _RawEffect(node, kind="IF")
            self._spec["_owner"] = raw
            self._spec["_node"] = node
            self._parent.append(raw)
        else:
            # 后续分支（otherwise）：把内容写进同一条 IF 效果的对应字段
            self._spec["_node"][self._branch] = [e.to_spec() for e in self._body]
        return False


class _ForeachBlock(_Block):
    """`for_each` 的块：进入时把循环变量加入作用域，退出时移除并挂载 FOREACH 效果。"""

    child_key = "body"

    def __init__(self, ct: "ContractType", spec: dict, var: str) -> None:
        super().__init__(ct, spec)
        self._var = var

    def __enter__(self) -> "_ForeachBlock":
        self._ct._var_scopes[-1].add(self._var)
        self._ct._var_scopes.append(set())
        return super().__enter__()  # type: ignore[return-value]

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._ct._var_scopes.pop()
        self._ct._var_scopes[-1].discard(self._var)
        self._ct._stack.pop()
        if exc_type is not None:
            return False
        node = {k: v for k, v in self._spec.items() if not k.startswith("_")}
        node["body"] = [e.to_spec() for e in self._body]
        self._parent.append(_RawEffect(node, kind="FOREACH"))
        return False


class _RawEffect(EffectBase):
    """控制流效果的载体（IF / FOREACH / ASSIGN）。

    不参与「效果 × 字段类型」校验（控制流本身不写字段），只负责把
    已经拼好的 JSON 交给编译链路。
    """

    __slots__ = ("_spec", "kind")

    def __init__(self, spec: dict, *, kind: str) -> None:
        self._spec = spec
        self.kind = kind

    def to_spec(self) -> dict:
        return dict(self._spec)

    @property
    def describe(self) -> str:
        return {"IF": "条件分支", "FOREACH": "循环", "ASSIGN": "赋值"}.get(self.kind, self.kind)


class ContractType:
    """合同类型构建器。

    链式调用，`build()` 产出四份 JSON。所有校验在构建期完成：
    参与方/输入项引用、效果与字段类型匹配、清单类型匹配、控制流作用域。
    """

    def __init__(self, key: str, name: str, *, description: str | None = None, enabled: bool = True) -> None:
        self.key = _require_key(key)
        self.name = str(name or "").strip()
        if not self.name:
            raise BuildError("合同类型名称不能为空")
        self.description = description
        self.enabled = bool(enabled)

        self._parties: list[PartyRef] = []
        self._party_by_role: dict[str, PartyRef] = {}
        self._inputs: list[dict[str, Any]] = []
        self._input_keys: dict[str, str] = {}  # key -> 输入类型
        self._checks: list[Check] = []
        self._root: list[EffectBase] = []
        self._stack: list[list[EffectBase]] = [self._root]
        self._var_scopes: list[set[str]] = [set()]
        # 漏挂载自检：本构建器创建过哪些效果、哪些已挂进效果树
        self._created: list[Effect] = []
        self._attached_ids: set[int] = set()
        # 构造时的「游离效果」水位线：之后新出现的游离效果才归因于本次 build 的脚本
        self._loose_mark = len(Effect.loose)
        self._snapshot = None  # 由 use_snapshot() 注入
        self._preserved_effects: list[Any] = []

    # ==================== ① 参与方 ====================

    def party(
        self,
        role: str,
        label: str | None = None,
        *,
        is_host: bool = False,
        selectable: bool = True,
        industry_type_id: int | None = None,
    ) -> PartyRef:
        """登记一个参与方角色。

        - `is_host=True` 表示主办方（虚拟参与方，不绑定公司，不能作为效果目标）；
        - `selectable=False` 表示该角色在创建合同时不可手选（由系统决定）；
        - `industry_type_id` 限定该角色只能由指定产业类型的公司担任。
        """
        key = str(role or "").strip()
        if not key:
            raise BuildError("参与方 role 不能为空")
        if key in self._party_by_role:
            raise BuildError(
                f"参与方角色「{key}」重复定义",
                hint="同一合同类型内 role 必须唯一（引擎按 role 定位目标公司）",
            )
        ref = PartyRef(
            self,
            key,
            str(label or key).strip() or key,
            is_host=is_host,
            selectable=selectable,
            industry_type_id=industry_type_id,
        )
        self._parties.append(ref)
        self._party_by_role[key] = ref
        return ref

    def _party(self, party: Any) -> PartyRef:
        role = _party_role(party)
        found = self._party_by_role.get(role)
        if found is None:
            raise BuildError(
                f"未定义的参与方角色「{role}」",
                hint=f"已定义：{'、'.join(self._party_by_role) or '（无，请先调用 party()）'}",
            )
        return found

    # ==================== ② 输入项 ====================

    def input(
        self,
        key: str,
        label: str,
        type: str = "number",  # noqa: A002 - 与后端契约字段同名，保持直观
        *,
        required: bool = False,
        default: Any = None,
        entity_type: str | None = None,
        party: Any = None,
        allowed: Sequence[str] | None = None,
        hidden: bool = False,
        when: "Value | None" = None,
    ) -> Value:
        """登记一个输入项（创建合同时由用户填写），返回可直接参与运算的值。

        `type` 取 15 种之一（与前端表单一一对应）：

        | 类型 | 含义 | 表单控件 |
        | --- | --- | --- |
        | `number` / `string` / `boolean` | 标量 | 数字框 / 文本框 / 开关 |
        | `ENTITY` | 从数据管理选一个实体（需 `entity_type=`） | 下拉 |
        | `nodeRoute` | 有序地图节点列表 | 节点链路编辑器 |
        | `mapNode` | 单个地图节点 | 下拉 |
        | `list` / `dict` | 自由列表 / 字典 | JSON 文本框 |
        | `materialList` 等 7 种清单 | `{名称: 数量}` 字典 | 多选 + 数量 |

        参数：

        - `party`：清单类输入项可绑定参与方（原料清单按该方所在地取价）；
        - `allowed`：限制可选的基建名 / 载具名（对应后端的 `allowedInfrastructures`
          与 `allowedVehicles`，引擎执行时会校验）；
        - `hidden=True`：不在表单渲染（快照的实体槽位用它）；
        - `when=<布尔值>`：该输入项只在条件成立时显示（对应引擎的 `branch`）。
        """
        k = str(key or "").strip()
        if not k:
            raise BuildError("输入项 key 不能为空")
        if k in self._input_keys:
            raise BuildError(f"输入项 key「{k}」重复定义")
        itype = str(type or "").strip()
        if itype not in INPUT_TYPES:
            raise BuildError(
                f"未知输入类型「{itype}」",
                hint=f"可用：{'、'.join(INPUT_TYPES)}",
            )
        if itype == "ENTITY":
            if not entity_type:
                raise BuildError(
                    f"输入项「{k}」的类型是 ENTITY，必须指定 entity_type",
                    hint="例：ct.input('m', '选择原料', 'ENTITY', entity_type='MATERIAL')",
                )
            from .values import ENTITY_ATTRIBUTES

            if str(entity_type).upper() not in ENTITY_ATTRIBUTES:
                raise BuildError(
                    f"未知实体类型「{entity_type}」",
                    hint=f"可用：{'、'.join(ENTITY_ATTRIBUTES)}",
                )

        item: dict[str, Any] = {
            "key": k,
            "label": str(label or k).strip() or k,
            "type": itype,
            "required": bool(required),
        }
        if entity_type:
            item["entityType"] = str(entity_type).upper()
        if default is not None:
            item["default"] = default
        if party is not None:
            if itype not in LIST_INPUT_TYPES:
                raise BuildError(
                    f"输入项「{k}」绑定了参与方，但类型 {itype} 不是清单类",
                    hint=f"只有 {'、'.join(LIST_INPUT_TYPES)} 可以绑定参与方",
                )
            item["party"] = self._party(party).role
        if allowed:
            names = [str(x).strip() for x in allowed if str(x).strip()]
            if not names:
                raise BuildError(f"输入项「{k}」的 allowed 不能为空列表")
            if itype == "infrastructureList":
                item["allowedInfrastructures"] = names
            elif itype == "vehicleList":
                item["allowedVehicles"] = names
            else:
                raise BuildError(
                    f"输入项「{k}」的类型 {itype} 不支持 allowed 限制",
                    hint="只有 infrastructureList（基建清单）与 vehicleList（载具清单）支持",
                )
        if hidden:
            item["hidden"] = True
        if when is not None:
            item["branch"] = _branch_of(when)

        self._inputs.append(item)
        self._input_keys[k] = itype
        return Value({"type": "INPUT", "key": k}, label=f"输入项 {k}", input_type=itype)

    def _input_type_of(self, key: str) -> str:
        return self._input_keys.get(key, "")

    # ==================== ③ 检查 ====================

    def check(
        self,
        condition: Any,
        *,
        label: str = "",
        error: str = "",
    ) -> Check:
        """登记一条前置检查。`condition` 直接写比较表达式：

            ct.check(buyer.field("cash") >= amount, error="买方货币资金不足")
            ct.check(plate.has_key("钢坯"), label="清单包含钢坯")
            ct.check(seller.is_industry(1))

        引擎支持 5 种检查：数值互相比较（本方法的比较表达式）、产业字段比较、
        产业类型判断（`party.is_industry(...)`）、字典/列表比较（`Container.compare`）。
        前三种本方法已覆盖；字典/列表的容器比较请用 `check_container()`。
        """
        spec = _condition_spec(condition)
        if label:
            spec["label"] = str(label)
        if error:
            spec["errorMessage"] = str(error)
        chk = Check(spec, kind=str(spec.get("kind") or ""), label=label or error)
        self._checks.append(chk)
        return chk

    def check_container(
        self,
        kind: str,
        op: str,
        value1: Any,
        value2: Any,
        *,
        label: str = "",
        error: str = "",
    ) -> Check:
        """登记一条字典/列表相互比较的检查。

        - `kind="DICT_COMPARE"`：`op` 取 GTE / GT / EQ，逐键比较；
        - `kind="LIST_COMPARE"`：`op` 取 ELEMENT_EQ / CONTAINS / GT / GTE / EQ。

        典型用法：判断「需求清单的每个键都在库存里」。
        """
        k = str(kind or "").upper()
        if k not in ("DICT_COMPARE", "LIST_COMPARE"):
            raise BuildError(
                f"check_container 的 kind 只能是 DICT_COMPARE / LIST_COMPARE，收到 {kind}",
                hint="普通数值比较请直接用 ct.check(a >= b)",
            )
        allowed = ("ELEMENT_EQ", "CONTAINS", "GT", "GTE", "EQ") if k == "LIST_COMPARE" else ("GTE", "GT", "EQ")
        o = str(op or "").upper()
        if o not in allowed:
            raise BuildError(f"{k} 的 op 只能是 {'、'.join(allowed)}，收到 {op}")
        spec: dict[str, Any] = {
            "kind": k,
            "op": o,
            "value1": _as_value(value1).to_spec(),
            "value2": _as_value(value2).to_spec(),
        }
        if label:
            spec["label"] = str(label)
        if error:
            spec["errorMessage"] = str(error)
        chk = Check(spec, kind=k, label=label or error)
        self._checks.append(chk)
        return chk

    # ==================== ④ 效果 ====================

    def _emit(self, factory, *args: Any) -> Effect:
        """在当前效果块登记一条具名效果。

        `factory` 是 effects 模块里的具名效果构造函数。调用期间把
        `Effect.builder_active` 置位，使效果被标记为「经由构建器登记」，
        从而能与「直接调用模块级函数」区分开（后者会被漏挂载自检拦下）。
        """
        prev = Effect.builder_active
        Effect.builder_active = True
        try:
            effect = factory(*args)
        finally:
            Effect.builder_active = prev
        self._created.append(effect)
        self._attached_ids.add(id(effect))
        self._stack[-1].append(effect)
        return effect

    def _emit_raw(self, effect: EffectBase) -> EffectBase:
        """挂载控制流效果（不需要漏挂载检查）。"""
        self._stack[-1].append(effect)
        return effect

    def add_number(self, target: FieldRef, amount: Any) -> Effect:
        """数值字段增加（只能作用于 NUMBER 字段）。"""
        return self._emit(add_number, target, amount)

    def sub_number(self, target: FieldRef, amount: Any) -> Effect:
        """数值字段扣减（只能作用于 NUMBER 字段）。"""
        return self._emit(sub_number, target, amount)

    def set_number(self, target: FieldRef, amount: Any) -> Effect:
        """数值字段设定（只能作用于 NUMBER 字段）。"""
        return self._emit(set_number, target, amount)

    def append_items(self, target: FieldRef, *items: Any) -> Effect:
        """列表字段追加元素（自动去重）。"""
        return self._emit(append_items, target, *items)

    def remove_items(self, target: FieldRef, *items: Any) -> Effect:
        """列表字段按元素移除。"""
        return self._emit(remove_items, target, *items)

    def set_items(self, target: FieldRef, items: Iterable[Any]) -> Effect:
        """列表字段整体设定。"""
        return self._emit(set_items, target, items)

    def add_dict(self, target: FieldRef, delta: dict) -> Effect:
        """字典字段逐键累加（保留独有键）。"""
        return self._emit(add_dict, target, delta)

    def sub_dict(self, target: FieldRef, delta: dict) -> Effect:
        """字典字段逐键扣减（**保留键**）。要删键请用 `remove_keys`。"""
        return self._emit(sub_dict, target, delta)

    def remove_keys(self, target: FieldRef, *keys: str) -> Effect:
        """字典字段删除键。"""
        return self._emit(remove_keys, target, *keys)

    def set_dict(self, target: FieldRef, value: dict) -> Effect:
        """字典字段整体设定。"""
        return self._emit(set_dict, target, value)

    def set_value(self, target: FieldRef, value: Any) -> Effect:
        """任意类型字段整体设定。"""
        return self._emit(set_value, target, value)

    # ---------- 控制流 ----------

    def when(self, condition: Any) -> _Block:
        """条件分支：`with ct.when(cond): ...`，可选 `with ct.otherwise(): ...`。

            with ct.when(buyer.is_industry(1)):
                ct.add_number(buyer.field("subsidy"), number("100"))
            with ct.otherwise():
                ct.add_number(buyer.field("subsidy"), number("0"))

        两个 `with` 产出**同一条** IF 效果（then / else 两个分支）。
        """
        spec = {
            "kind": "IF",
            "cond": _branch_condition_spec(condition),
            "_body": [],
            "_branch": "then",
        }
        self._last_if = spec
        return _Block(self, spec)

    def otherwise(self) -> _Block:
        """`when()` 的假分支。必须紧跟在 `with ct.when(...)` 之后，且只能用一次。"""
        spec = getattr(self, "_last_if", None)
        if spec is None:
            raise BuildError(
                "otherwise() 必须紧跟在 with ct.when(...) 之后",
                hint="写法：with ct.when(cond): ... 然后 with ct.otherwise(): ...",
            )
        if spec.get("_else_used"):
            raise BuildError("otherwise() 对同一个 when() 只能使用一次")
        spec["_else_used"] = True
        # 复用同一个 spec（_owner/_node 在 when 块退出时写回这里），只换 body 与分支名
        return _Block(self, spec, body=[], branch="else")

    def for_each(self, items: Any, *, var: str = "row") -> _Block:
        """循环：`with ct.for_each(清单, var="row"): ...`。

        循环体里元素是**清单的键**（名称字符串），取数量用 `ct.item("清单key")`。

        清单类输入项（materialList 等）的值是 `{名称: 数量}` **字典**，而引擎的
        FOREACH 只遍历列表（`lst = arr if isinstance(arr, list) else []`）。
        因此这里自动把它转成「键列表」：`FORMULA: keys(清单)`，循环体拿到名称。
        列表型输入项（list / nodeRoute / mapNode）则直接遍历，元素就是值本身。
        """
        name = str(var or "").strip()
        if not name:
            raise BuildError("for_each() 的变量名不能为空")
        spec = {
            "kind": "FOREACH",
            "items": _as_list_source(items, self._input_keys),
            "var": name,
            "_body": [],
        }
        return _ForeachBlock(self, spec, name)

    def assign(self, name: str, value: Any) -> Effect:
        """中间变量赋值，后续用 `var(name)` 引用。

        引擎的 ASSIGN 是**常量求值**（求值发生在写入时、结果进作用域），
        因此不要指望它按每次读取重新计算——需要动态值时请直接写表达式。
        """
        key = str(name or "").strip()
        if not key:
            raise BuildError("assign() 的变量名不能为空")
        self._var_scopes[-1].add(key)
        return self._emit_raw(
            _RawEffect(
                {"kind": "ASSIGN", "name": key, "value": _as_value(value).to_spec()},
                kind="ASSIGN",
            )
        )

    def item(self, key: str, *, var: str = "row") -> Value:
        """取清单/字典里某个键的值：`清单[当前元素]`。

        编译成 `FORMULA: mats[row]`。**注意不能用 `inputs['mats']`**：引擎的
        `eval_value_spec` 把 FORMULA 的沙箱拼成 `{**inputs, **EXPR_HELPERS, **scope}`
        （`engine.py:1788`），也就是**输入项与循环变量是顶层名字**，并没有
        `inputs` / `scope` 这两个字典对象——写成 `inputs['mats']` 会取到 None 再
        按 0 参与运算（静默错误）。
        """
        k = str(key or "").strip()
        if not k:
            raise BuildError("item() 需要清单输入项的 key")
        if k not in self._input_keys:
            raise BuildError(
                f"item() 引用的输入项「{k}」未定义",
                hint=f"已定义：{'、'.join(self._input_keys) or '（无）'}",
            )
        v = str(var or "").strip()
        if not self._in_scope(v):
            current = sorted({n for scope in self._var_scopes for n in scope})
            raise BuildError(
                f"item() 的变量「{v}」不在当前作用域内",
                hint=(
                    "请把 item() 写在 for_each(..., var=...) 的循环体内，"
                    "并让两处的变量名一致"
                    + (f"；当前作用域内可用变量：{'、'.join(current)}" if current else "")
                ),
            )
        return Value(
            {"type": "FORMULA", "expr": f"{_NAME_RE.sub('_', k)}[{_NAME_RE.sub('_', v)}]"},
            label=f"{k}[{v}]",
        )

    def _in_scope(self, name: str) -> bool:
        """变量是否在**任意**外层作用域中（嵌套循环时内层可用外层的变量）。"""
        return any(name in scope for scope in self._var_scopes)

    # ==================== 漏挂载自检 ====================

    def _track(self, effect: EffectBase) -> None:
        """记录一条效果的创建（供漏挂载自检）。"""
        if isinstance(effect, Effect):
            self._created.append(effect)

    def _assert_no_orphan_effects(self) -> None:
        """检查有没有「创建了效果但没挂进效果树」的情况。

        典型误用是直接调用模块级函数：

            add_number(buyer.field("cash"), amount)     # ✗ 没登记，会被静默丢弃
            ct.add_number(buyer.field("cash"), amount)  # ✓

        没有这道检查时，前者产出的合同类型会少一条效果——不报错、只是数字不对。
        """
        orphans = [e for e in self._created if id(e) not in self._attached_ids]
        # 模块级函数直接创建的效果（未经本构建器）同样会丢，一并报出
        orphans += [e for e in Effect.loose[self._loose_mark :] if id(e) not in self._attached_ids]
        # 消费掉，避免影响后续构建器（每个游离效果只报一次）
        del Effect.loose[self._loose_mark :]
        if not orphans:
            return
        shown = "、".join(f"{e.kind}({e.target_label or e.role + '.' + e.field_key})" for e in orphans[:3])
        detail = "；".join(f"{e.kind} → {e.role}.{e.field_key}" for e in orphans[:5])
        raise BuildError(
            f"有 {len(orphans)} 条效果创建后没有登记到合同类型上：{shown}"
            + ("…" if len(orphans) > 3 else ""),
            hint=(
                "请用构建器方法登记：ct.add_number(...) / ct.sub_number(...) / ct.append_items(...) 等；"
                "直接调用模块级的 add_number(...) 不会挂到合同上。明细：" + detail
            ),
        )

    # ==================== 快照 ====================

    def use_snapshot(self, snap: Any) -> "ContractType":
        """绑定比赛数据快照（`snapshot(competition_id)` 的返回值）。

        绑定后 `build()` 会把快照按需生成的**实体槽位输入项**注入 `inputSchema`
        （`hidden=True`），从而在保留引擎 `ENTITY` 值源的同时消灭手写隐藏输入项。
        """
        self._snapshot = snap
        return self

    # ==================== 既有数据（保留） ====================

    def keep_effects(self, effects: Sequence[Any]) -> "ContractType":
        """原样保留一段已有的 `effects` JSON（通常来自可视化编辑器）。

        用于「代码只接管一部分效果、其余保持原样」的渐进迁移：
        保留的效果排在**最前**，与代码产出的效果顺序一致可控。
        """
        for e in effects or []:
            if not isinstance(e, dict):
                raise BuildError(f"keep_effects() 只接受 JSON 对象，收到 {type(e).__name__}")
        self._preserved_effects.extend(effects or [])
        return self

    # ==================== 编译 ====================

    def build(self) -> dict:
        """产出四份 JSON（`partyRoles` / `inputSchema` / `effects` / `conditions`）。"""
        if not self._parties:
            raise BuildError(
                f"合同类型「{self.name}」没有任何参与方",
                hint="至少需要一个参与方；主办方可写 ct.party('bank', '银行', is_host=True)",
            )
        non_host = [p for p in self._parties if not p.is_host]
        if not non_host:
            raise BuildError(
                f"合同类型「{self.name}」只有主办方参与方",
                hint="效果与检查都要落到具体公司，至少需要一个非主办方角色",
            )

        effects = [dict(e) if isinstance(e, dict) else e for e in self._preserved_effects]
        effects.extend(e.to_spec() for e in self._root)
        self._assert_no_orphan_effects()

        input_schema = [dict(i) for i in self._inputs]
        if self._snapshot is not None:
            existing = {i["key"] for i in input_schema}
            # 快照槽位是构建期固定状态：每次 build 都必须注入（重复 build 不得丢槽位，
            # 否则 effects 里的 entityRef 无对应输入项，运行期实体引用静默变 0）
            for slot in self._snapshot.pinned_inputs():
                if slot["key"] not in existing:
                    input_schema.append(dict(slot))
                    existing.add(slot["key"])

        payload = {
            "partyRoles": [_party_spec(p) for p in self._parties],
            "inputSchema": input_schema,
            "effects": effects,
            "conditions": [c.to_spec() for c in self._checks],
        }
        _assert_contract_shape(payload)
        return payload

    def payload(self) -> dict:
        """产出可直接 POST 到 `/api/contract-types` 的请求体。

        `graph` 传 `None`（后端 `allow_null=True`，引擎从不读它）。
        若想同时保留可视化画布，把既有 `graph` 通过 `graph=` 传进来即可。
        """
        body = self.build()
        body.update(
            {
                "key": self.key,
                "name": self.name,
                "description": self.description,
                "partyCount": len(self._parties),
                "graph": None,
                "schemaVersion": 1,
                "enabled": self.enabled,
            }
        )
        return body

    def to_json(self, *, indent: int = 2) -> str:
        """产出 `effects` / `conditions` / ... 的 JSON 文本（便于比对与留档）。"""
        return json.dumps(self.payload(), ensure_ascii=False, indent=indent)

    def effects_json(self) -> str:
        """`effects` 的落库 JSON 字符串（与前端可视化编辑器产物同格式）。"""
        return json.dumps(self.build()["effects"], ensure_ascii=False)

    def conditions_json(self) -> str:
        """`conditions` 的落库 JSON 字符串。"""
        return json.dumps(self.build()["conditions"], ensure_ascii=False)

    def default_inputs(self, overrides: dict | None = None) -> dict:
        """按 `inputSchema` 的默认值组装一份可用输入（`overrides` 优先）。

        **为什么需要它**：引擎的 `ContractEngine.execute` **不会**自动套用
        `inputSchema` 里的 `default`——它只读 `contract["inputs"]` 里已有的键。
        默认值是在**创建合同**那一步由调用方填进 `inputs` 的
        （前端表单如此、试算接口的注释也写明了「inputSchema 默认值打底」）。

        因此用代码做试算/自测时，必须自己把默认值补齐，否则未显式提供的输入项
        在引擎里取到 `None`，经 `to_number` 变成 **0**——表现就是「乘费率的效果恒为 0」
        这类静默错误。本方法就是那个补齐动作，`--trial` 也用它。
        """
        merged: dict = {}
        for item in self.build()["inputSchema"]:
            key = item.get("key")
            if key and item.get("default") is not None:
                merged[key] = item["default"]
        if overrides:
            merged.update(overrides)
        return merged

    # ==================== 只读视图 ====================

    @property
    def parties(self) -> tuple[PartyRef, ...]:
        return tuple(self._parties)

    @property
    def input_keys(self) -> tuple[str, ...]:
        return tuple(self._input_keys)

    def describe(self) -> str:
        """一句话摘要（体检报告与日志用）。"""
        return (
            f"{self.name}（{self.key}）：{len(self._parties)} 个参与方、"
            f"{len(self._inputs)} 个输入项、{len(self._root)} 组效果、{len(self._checks)} 条检查"
        )


class _VarBlock(_Block):
    """`for_each` 的块：进入时把循环变量加入作用域，退出时移除。"""

    def __init__(self, ct: ContractType, spec: dict, var: str) -> None:
        super().__init__(ct, spec)
        self._var = var

    def __enter__(self) -> "_VarBlock":
        self._ct._var_scopes[-1].add(self._var)
        self._ct._var_scopes.append(set())
        return super().__enter__()  # type: ignore[return-value]

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._ct._var_scopes.pop()
        self._ct._var_scopes[-1].discard(self._var)
        return super().__exit__(exc_type, exc, tb)


# ==================== 辅助 ====================


def _require_key(raw: str) -> str:
    key = str(raw or "").strip()
    if not key:
        raise BuildError("合同类型 key 不能为空")
    if not all(c.isalnum() or c in "-_" for c in key):
        raise BuildError(
            f"合同类型 key「{key}」含非法字符",
            hint="只允许字母、数字、连字符与下划线（它会出现在 URL 与文件名里）",
        )
    return key


def _party_spec(p: PartyRef) -> dict:
    spec: dict[str, Any] = {
        "role": p.role,
        "label": p.label,
        "isHost": p.is_host,
        "selectable": p.selectable,
    }
    if p.industry_type_id is not None:
        spec["industryTypeId"] = int(p.industry_type_id)
    return spec


def _branch_of(condition: Value) -> dict:
    """输入项的条件显隐：把布尔值源转成 `{when, cond}`。"""
    spec = _as_value(condition).to_spec()
    if spec.get("type") == "OP" and str(spec.get("op") or "").startswith("CMP_"):
        return {"when": "then", "cond": spec}
    return {"when": "then", "cond": spec}


def _condition_spec(condition: Any) -> dict:
    """把 Python 比较表达式转成引擎的 condition JSON（**检查对象**形状，带 `kind`）。

    - `party.field(key) >= value` → `FIELD_COMPARE`
    - `valueA >= valueB`         → `VALUE_COMPARE`
    - `party.is_industry(id)`    → `INDUSTRY_IS`

    注意与 `_branch_condition_spec` 的区别：挂在 IF 分支上的条件/输入项显隐用的是
    **值源**形状（带 `type`），见 `_branch_condition_spec`。
    """
    v = _as_value(condition)
    spec = v.to_spec()
    t = spec.get("type")

    if t == "INDUSTRY_IS":
        return {
            "kind": "INDUSTRY_IS",
            "party": spec.get("party"),
            "industryTypeId": spec.get("industryTypeId"),
        }
    if t == "OP" and str(spec.get("op") or "").startswith("CMP_"):
        args = spec.get("args") or []
        if len(args) != 2:
            raise SchemaError(f"比较运算必须有左右两个操作数：{spec}")
        left, right = args
        op = str(spec["op"])[4:]  # 去掉 CMP_ 前缀 → GTE/LTE/GT/LT/EQ/NE
        if op == "NE":
            raise BuildError(
                "检查暂不支持「不等于」（引擎的 FIELD_COMPARE / VALUE_COMPARE 无此 op）",
                hint="请改用等式取反的等价条件，或用 check_container",
            )
        if left.get("type") == "FIELD":
            if right.get("type") == "FIELD":
                raise BuildError(
                    "检查不支持「两个产业字段互相比较」",
                    hint=(
                        "引擎的 FIELD_COMPARE 右侧只接受值源（常量/输入项/变量/公式）；"
                        "两个字段比较请用 VALUE_COMPARE 的写法或公式"
                    ),
                )
            return {
                "kind": "FIELD_COMPARE",
                "party": left.get("party"),
                "fieldKey": left.get("fieldKey"),
                "op": op,
                "value": right,
            }
        return {"kind": "VALUE_COMPARE", "op": op, "value1": left, "value2": right}
    raise BuildError(
        f"检查条件必须是比较或产业类型判断，收到：{v.describe}",
        hint="例：ct.check(buyer.field('cash') >= amount)、ct.check(p.is_industry(1))",
    )


def _branch_condition_spec(condition: Any) -> dict:
    """把布尔值源转成引擎的**值源** JSON（带 `type`），用于 IF 的 cond 与输入项显隐。

    引擎的 `eval_value_spec` 按 `type` 分派；IF 分支条件必须是这个形状
    （与前端 graph-model.ts:1275 产出一致）。
    """
    spec = _as_value(condition).to_spec()
    t = spec.get("type")
    if t == "INDUSTRY_IS" or t == "FORMULA" or t == "VAR" or t == "INPUT":
        return spec
    if t == "OP" and str(spec.get("op") or "").startswith("CMP_"):
        return spec
    raise BuildError(
        f"分支条件必须是布尔值源，收到：{_as_value(condition).describe}",
        hint="例：with ct.when(buyer.is_industry(1))、with ct.when(buyer.field('cash') >= amount)",
    )


def _assert_contract_shape(payload: dict) -> None:
    """编译产物自检：确保四个字段的类型与后端契约一致。

    这是防「本库产出坏 JSON」的最后一道闸门——一旦形状不对，宁可在构建期失败，
    也不要写进数据库让引擎在比赛当天报错。
    """
    for field in ("partyRoles", "inputSchema", "effects", "conditions"):
        if not isinstance(payload.get(field), list):
            raise SchemaError(f"{field} 必须是数组，实际是 {type(payload.get(field)).__name__}")
    for i, item in enumerate(payload["partyRoles"]):
        if not isinstance(item, dict) or not item.get("role"):
            raise SchemaError(f"partyRoles[{i}] 缺少 role：{item!r}")
    for i, item in enumerate(payload["inputSchema"]):
        if not isinstance(item, dict) or not item.get("key"):
            raise SchemaError(f"inputSchema[{i}] 缺少 key：{item!r}")
        if item.get("type") not in INPUT_TYPES:
            raise SchemaError(f"inputSchema[{i}] 的 type 非法：{item.get('type')!r}")
    seen: set[str] = set()
    for i, item in enumerate(payload["inputSchema"]):
        k = item["key"]
        if k in seen:
            raise SchemaError(f"inputSchema 出现重复 key：{k}")
        seen.add(k)
    for i, eff in enumerate(payload["effects"]):
        _assert_effect_shape(eff, f"effects[{i}]")


def _assert_effect_shape(eff: Any, where: str) -> None:
    if not isinstance(eff, dict):
        raise SchemaError(f"{where} 不是对象：{eff!r}")
    kind = eff.get("kind")
    if kind == "FIELD":
        if not eff.get("party"):
            raise SchemaError(
                f"{where} 未指定参与方（引擎会拒绝执行：无法定位目标公司）"
            )
        if not eff.get("fieldKey"):
            raise SchemaError(f"{where} 未指定 fieldKey")
        if eff.get("op") not in ("ADD", "SUB", "SET"):
            raise SchemaError(f"{where} 的 op 非法：{eff.get('op')!r}")
        if "value" not in eff:
            raise SchemaError(f"{where} 缺少 value（引擎会按 0 处理，属于静默错误）")
    elif kind == "IF":
        if not isinstance(eff.get("cond"), dict):
            raise SchemaError(f"{where} 的 IF 缺少 cond")
        for branch in ("then", "else"):
            body = eff.get(branch)
            if body is None:
                continue
            if not isinstance(body, list):
                raise SchemaError(f"{where} 的 IF.{branch} 必须是数组")
            for j, sub in enumerate(body):
                _assert_effect_shape(sub, f"{where}.{branch}[{j}]")
    elif kind == "FOREACH":
        if not isinstance(eff.get("items"), dict):
            raise SchemaError(f"{where} 的 FOREACH 缺少 items")
        body = eff.get("body")
        if not isinstance(body, list):
            raise SchemaError(f"{where} 的 FOREACH.body 必须是数组")
        for j, sub in enumerate(body):
            _assert_effect_shape(sub, f"{where}.body[{j}]")
    elif kind == "ASSIGN":
        if not eff.get("name"):
            raise SchemaError(f"{where} 的 ASSIGN 缺少 name")
        if "value" not in eff:
            raise SchemaError(f"{where} 的 ASSIGN 缺少 value")
    else:
        raise SchemaError(f"{where} 出现未知效果类型：{kind!r}")
