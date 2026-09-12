"""低抽象效果层：效果种类 = 业务动作，而不是「一个 op + 运行时猜字段类型」。

现状的问题
----------
落库的 effect 只有一种形状 `{kind:"FIELD", party, fieldKey, op, value}`，
`op` 的**真实含义取决于目标字段的运行时类型**（`engine.apply_field_effect`）：

| 字段类型 | `ADD` | `SUB` |
| --- | --- | --- |
| `NUMBER` | 数值相加 | 数值相减 |
| `LIST` | 追加并去重 | 按元素移除 |
| `DICTIONARY` | 逐键累加 | **逐键相减；若值是数组则改为「删键」** |
| `STRING`/`BOOLEAN` | 覆盖（`ADD` 无意义） | 覆盖 |

于是「这条效果会做什么」必须再去查字段类型才能知道；字典的 `SUB` 更是靠
**值的形态**（数组=删键 / 字典=减数）来区分意图。这是典型的抽象过度。

本层的做法
----------
把意图写成**具名效果**，效果名自带字段类型契约：

    add_number(target, amount)      只能作用于 NUMBER   → op ADD
    sub_number(target, amount)      只能作用于 NUMBER   → op SUB
    set_number(target, amount)      只能作用于 NUMBER   → op SET
    append_items(target, item)      只能作用于 LIST     → op ADD
    remove_items(target, item)      只能作用于 LIST     → op SUB
    set_items(target, [..])         只能作用于 LIST     → op SET
    add_dict(target, {"A": 2})      只能作用于 DICTIONARY → op ADD
    sub_dict(target, {"A": 2})      只能作用于 DICTIONARY → op SUB
    remove_keys(target, ["A"])      只能作用于 DICTIONARY → op SUB（值必须是数组）
    set_value(target, value)        任意类型            → op SET

关键收益：

1. **可预测**：看效果名就知道做什么，不必查字段类型（不匹配在构建期直接报错）；
2. **意图显式**：「字典删键」与「字典减数」是两个不同的效果名，不再靠传数组暗示；
3. **零新增语义**：编译产物仍然是引擎今天就在跑的 `{kind:"FIELD", op, value[, valueOp, value2]}`，
   没有引入任何新 op、新 kind、新表字段——可逆性（`revert_contract` 的重放）完全不受影响。

关于 `valueOp` / `value2`
-------------------------
引擎支持「写入量 = value ⟨valueOp⟩ value2」。本层不暴露这两个参数，而是让调用方
在**值层**做运算（`add_number(f, a + b)`），编译时把 `combine` 折叠成 `OP` 值源：

    add_number(target, a + b)   → op ADD + value2=a + valueOp=ADD + value=a

两种写法在引擎里等价（`combine_values` 先算 `value ⟨op⟩ value2`，再交给
`apply_field_effect`），但前者的意图写在 Python 里，可读、可测、可静态校验。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .errors import BuildError, require, type_mismatch
from .values import Value, _as_value

# ==================== 效果种类定义 ====================

# kind → (需要的字段类型, 引擎 op, 值形态, 中文名)
# 值形态：single=单个值；sequence=列表（可多元素）；mapping=字典
EFFECT_KINDS: dict[str, tuple[str, str, str, str]] = {
    "add_number": ("NUMBER", "ADD", "single", "增加数值"),
    "sub_number": ("NUMBER", "SUB", "single", "扣减数值"),
    "set_number": ("NUMBER", "SET", "single", "设定数值"),
    "append_items": ("LIST", "ADD", "sequence", "追加列表元素"),
    "remove_items": ("LIST", "SUB", "sequence", "移除列表元素"),
    "set_items": ("LIST", "SET", "sequence", "设定整个列表"),
    "add_dict": ("DICTIONARY", "ADD", "mapping", "字典逐键累加"),
    "sub_dict": ("DICTIONARY", "SUB", "mapping", "字典逐键扣减"),
    "remove_keys": ("DICTIONARY", "SUB", "keys", "字典删除键"),
    "set_dict": ("DICTIONARY", "SET", "mapping", "设定整个字典"),
    "set_value": ("ANY", "SET", "single", "设定值（任意类型）"),
}

# 反查：(引擎 op, 值形态) → 候选效果名。用于把已有合同类型反解成具名效果。
# 值形态：dict = 字面量字典 / 逐键运算；list = 数组（列表元素或删键）；scalar = 标量。
_VALUESHAPE_TO_KINDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("ADD", "scalar"): ("add_number",),
    ("ADD", "list"): ("append_items",),
    ("ADD", "dict"): ("add_dict",),
    ("SUB", "scalar"): ("sub_number",),
    ("SUB", "list"): ("remove_items", "remove_keys"),
    ("SUB", "dict"): ("sub_dict",),
    ("SET", "scalar"): ("set_number", "set_value"),
    ("SET", "list"): ("set_items",),
    ("SET", "dict"): ("set_dict",),
}

# 字段类型 → 该类型可用的效果名（文档与报错用）
KINDS_BY_FIELD_TYPE: dict[str, tuple[str, ...]] = {
    "NUMBER": ("add_number", "sub_number", "set_number", "set_value"),
    "LIST": ("append_items", "remove_items", "set_items", "set_value"),
    "DICTIONARY": ("add_dict", "sub_dict", "remove_keys", "set_dict", "set_value"),
    "STRING": ("set_value",),
    "BOOLEAN": ("set_value",),
    "ANY": tuple(EFFECT_KINDS),
}


class EffectBase:
    """效果的公共接口：只有两个方法被编译/报告链路调用。

    分成基类是为了让控制流（IF / FOREACH / ASSIGN）能进同一个列表，
    同时不必伪装成 FIELD 效果。
    """

    __slots__ = ()

    def to_spec(self) -> dict:  # pragma: no cover - 抽象
        raise NotImplementedError

    @property
    def describe(self) -> str:  # pragma: no cover - 抽象
        raise NotImplementedError


class Effect(EffectBase):
    """一条具名效果。由 `add_number(...)` 这类函数创建，不要直接构造。"""

    __slots__ = ("kind", "role", "field_key", "value", "target_label", "via_builder")

    #: 是否有构建器正处于登记状态。由 `ContractType` 登记效果时临时置位：
    #: 用它区分「通过 ct.add_number(...) 登记」与「直接调用模块级 add_number(...)」。
    #: 后者不会被挂到任何合同上，今天会静默丢弃一条效果——构建期必须报出来。
    builder_active: bool = False

    #: 未经过构建器直接创建的效果（模块级函数误用）。由漏挂载自检消费。
    loose: list["Effect"] = []

    def __init__(
        self,
        kind: str,
        role: str,
        field_key: str,
        value: Value | tuple[Value, ...] | dict[str, Value],
        *,
        target_label: str = "",
    ) -> None:
        if kind not in EFFECT_KINDS:
            raise BuildError(f"未知效果种类：{kind}", hint=f"可用：{'、'.join(EFFECT_KINDS)}")
        self.kind = kind
        self.role = role
        self.field_key = field_key
        self.value = value
        self.target_label = target_label
        self.via_builder = Effect.builder_active
        if not self.via_builder:
            Effect.loose.append(self)

    # ---------- 元信息 ----------

    @property
    def field_type(self) -> str:
        """本效果要求的字段类型。"""
        return EFFECT_KINDS[self.kind][0]

    @property
    def engine_op(self) -> str:
        """编译后使用的引擎 op。"""
        return EFFECT_KINDS[self.kind][1]

    @property
    def kind_label(self) -> str:
        return EFFECT_KINDS[self.kind][3]

    @property
    def describe(self) -> str:
        target = self.target_label or f"{self.role}.{self.field_key}"
        if isinstance(self.value, dict):
            shown = "{" + "、".join(f"{k}: {v.describe}" for k, v in self.value.items()) + "}"
        elif isinstance(self.value, tuple):
            shown = "、".join(v.describe for v in self.value)
        else:
            shown = self.value.describe
        return f"{self.kind_label}：{target} ← {shown}"

    def __repr__(self) -> str:  # pragma: no cover - 调试可读性
        return f"Effect({self.describe})"

    # ---------- 类型校验 ----------

    def check_field_type(self, actual: str | None, *, where: str = "") -> str | None:
        """校验本效果与真实字段类型是否匹配；不匹配返回问题描述，匹配返回 None。

        `actual=None` 表示字段不存在（由调用方另报「字段不存在」）。
        """
        need = self.field_type
        if need == "ANY" or actual is None:
            return None
        if str(actual).upper() == need:
            return None
        spot = f"{where}：" if where else ""
        return (
            f"{spot}{self.describe} —— 字段实际类型是 {actual}，"
            f"而「{self.kind}」只能作用于 {need} 字段"
            f"（{need} 字段可用：{'、'.join(KINDS_BY_FIELD_TYPE.get(need, ()))}）"
        )

    # ---------- 编译 ----------

    def to_spec(self) -> dict:
        """编译为引擎 effect JSON。"""
        op = self.engine_op
        spec: dict[str, Any] = {
            "kind": "FIELD",
            "party": self.role,
            "fieldKey": self.field_key,
            "op": op,
        }

        if isinstance(self.value, tuple):
            # 多元素合并成单个值源（列表拼接）。
            # `remove_keys` **必须**是数组：引擎靠「值是数组还是字典」区分「删键」与「减数」，
            # 单键时若退化成裸字符串，引擎会走标量分支（语义也是删键，但形状不稳定）。
            if len(self.value) == 1 and self.kind != "remove_keys":
                spec["value"] = self.value[0].to_spec()
            else:
                spec["value"] = _concat(self.value)
        elif isinstance(self.value, dict):
            spec["value"] = _materialize_mapping(self.value)
        else:
            spec["value"] = self.value.to_spec()
        return spec


def _concat(values: Sequence[Value]) -> dict:
    """把若干值合并成一个「列表形状」的值源。

    - 两个值 → `LIST_CONCAT(a, b)`
    - 三个及以上 → 先两两 CONCAT 成一层，再 CONCAT 拍平（引擎的 LIST_CONCAT 会对
      每个参数做 as_list 再 extend，因此嵌套一层即可拍平）

    为什么要保证「至少两个参数」：引擎的 `as_list()` 对单个标量会包成 `[x]`，
    所以 `LIST_CONCAT([x])` 的结果仍是 `[x]`——形状稳定成数组，正是
    `remove_keys` 这类「靠数组形态表达语义」的效果需要的。
    """
    specs = [v.to_spec() for v in values]
    if len(specs) == 1:
        return {"type": "OP", "op": "LIST_CONCAT", "args": [specs[0]]}
    if len(specs) == 2:
        return {"type": "OP", "op": "LIST_CONCAT", "args": specs}
    inner = [
        {"type": "OP", "op": "LIST_CONCAT", "args": [specs[i], specs[i + 1]]}
        for i in range(0, len(specs) - 1, 2)
    ]
    if len(specs) % 2:
        inner.append(specs[-1])
    return {"type": "OP", "op": "LIST_CONCAT", "args": inner}


def _materialize_mapping(values: dict[str, Value]) -> Any:
    """字典效果的值：展开成 `{"type":"CONST","value":{...}}`，与前端可视化编辑器一致。

    为什么必须包一层 CONST：引擎在 `apply_leaf` 里对效果的 value 统一走
    `eval_value_spec`。若直接把字面量字典当 value，`eval_value_spec` 会落到
    默认分支 `to_number(dict)` → **0**，字典效果静默变成「加 0」。
    前端 graphToFlat 产出的是 `{type:"CONST", value:{...}}`，这里对齐同一形状。

    值必须是字面量：引擎对 CONST 的 value 直接当数据用（`to_number(v)`），不做求值。
    """
    out: dict[str, Any] = {}
    for key, val in values.items():
        spec = val.to_spec()
        if spec.get("type") != "CONST":
            raise BuildError(
                f"字典效果的键「{key}」用了动态值（{val.describe}），引擎不支持",
                hint=(
                    "字典效果的每个值必须是字面量（数字/字符串）；"
                    "动态数量请改用数值字段表达，或把该效果拆成常量效果逐条写入"
                ),
            )
        out[str(key)] = spec.get("value")
    return {"type": "CONST", "value": out}


# ==================== 效果的构造入口 ====================


def add_number(target: Any, amount: Any) -> Effect:
    """数值字段：增加 amount（引擎 op=ADD）。"""
    return _make("add_number", target, amount)


def sub_number(target: Any, amount: Any) -> Effect:
    """数值字段：扣减 amount（引擎 op=SUB）。"""
    return _make("sub_number", target, amount)


def set_number(target: Any, amount: Any) -> Effect:
    """数值字段：设定为 amount（引擎 op=SET）。"""
    return _make("set_number", target, amount)


def append_items(target: Any, *items: Any) -> Effect:
    """列表字段：追加元素（引擎 op=ADD，自动去重）。至少一个元素。"""
    return _make_sequence("append_items", target, items)


def remove_items(target: Any, *items: Any) -> Effect:
    """列表字段：按元素移除（引擎 op=SUB）。至少一个元素。"""
    return _make_sequence("remove_items", target, items)


def set_items(target: Any, items: Iterable[Any]) -> Effect:
    """列表字段：整体设定为给定列表（引擎 op=SET）。传 `[]` 表示清空。

    只接受 list / tuple：`iter([])` 这类迭代器多半是「忘了展开」的误用
    （空迭代器会被静默当成清空，非空迭代器取不出来），所以直接报错。
    """
    if isinstance(items, str) or not isinstance(items, (list, tuple)):
        raise BuildError(
            f"set_items() 需要列表，收到 {type(items).__name__}",
            hint="正确写法：set_items(party.field('tags'), ['A', 'B'])；清空写 []",
        )
    role, field_key, label = _read_target(target)
    return Effect(
        "set_items", role, field_key, tuple(_as_value(it) for it in items), target_label=label
    )


def add_dict(target: Any, delta: dict) -> Effect:
    """字典字段：逐键累加（共有键的值相加，独有键保留；引擎 op=ADD）。

    `delta` 的值必须是字面量（数字/字符串），不能是动态值源。
    """
    return _make_mapping("add_dict", target, delta)


def sub_dict(target: Any, delta: dict) -> Effect:
    """字典字段：逐键扣减（**保留键**，仅共有键的值相减；引擎 op=SUB）。

    想「删掉某些键」请用 `remove_keys()`——两者在引擎里是同一个 op，
    靠值的形态区分，这里拆成两个名字，意图不再靠猜。
    """
    return _make_mapping("sub_dict", target, delta)


def remove_keys(target: Any, *keys: str) -> Effect:
    """字典字段：删除指定键（引擎 op=SUB + 数组值）。至少一个键。

    **值形态很重要**：引擎对字典字段的 `SUB` 分支按「值是数组还是字典」区分
    「删键」与「减数」，所以这里始终编译成数组形状（即使只有一个键）。
    """
    if not keys:
        raise BuildError("remove_keys() 至少需要一个键名")
    cleaned: list[str] = []
    for k in keys:
        name = str(k or "").strip()
        if not name:
            raise BuildError("remove_keys() 的键名不能为空")
        if name not in cleaned:
            cleaned.append(name)
    role, field_key, label = _read_target(target)
    return Effect("remove_keys", role, field_key, tuple(_literal_key(k) for k in cleaned), target_label=label)


def set_dict(target: Any, value: dict) -> Effect:
    """字典字段：整体设定为给定字典（引擎 op=SET）。"""
    return _make_mapping("set_dict", target, value)


def set_value(target: Any, value: Any) -> Effect:
    """任意类型字段：整体设定（引擎 op=SET）。

    这是唯一不受字段类型限制的效果，用于 STRING / BOOLEAN 字段，
    或确知要整体覆盖的场合。
    """
    return _make("set_value", target, value)


# ==================== 内部构造 ====================


def _make(kind: str, target: Any, raw: Any) -> Effect:
    role, field_key, label = _read_target(target)
    return Effect(kind, role, field_key, _as_value(raw), target_label=label)


def _make_sequence(kind: str, target: Any, items: Sequence[Any]) -> Effect:
    if not items:
        raise BuildError(
            f"{kind}() 至少需要一个元素",
            hint="要清空列表请用 set_items(target, [])",
        )
    role, field_key, label = _read_target(target)
    values = tuple(_as_value(it) for it in items)
    return Effect(kind, role, field_key, values, target_label=label)



def _make_mapping(kind: str, target: Any, delta: Any) -> Effect:
    if not isinstance(delta, dict):
        raise BuildError(f"{kind}() 需要字典，收到 {type(delta).__name__}: {delta!r}")
    if not delta:
        raise BuildError(f"{kind}() 的字典不能为空")
    role, field_key, label = _read_target(target)
    values = {str(k): _as_value(v) for k, v in delta.items()}
    return Effect(kind, role, field_key, values, target_label=label)


def _literal_key(raw: str) -> Value:
    return Value({"type": "CONST", "value": raw}, label=f"键 {raw!r}")


def _read_target(target: Any) -> tuple[str, str, str]:
    """从 FieldRef 取出 (role, fieldKey, 展示名)。

    效果的目标必须是「某参与方的某字段」，因此只接受 `party.field(...)` 的返回值。
    """
    role = getattr(target, "role", None)
    field_key = getattr(target, "field_key", None)
    if not role or not field_key:
        raise BuildError(
            f"效果的目标必须是参与方字段，收到 {type(target).__name__}: {target!r}",
            hint="正确写法：add_number(buyer.field('cash'), number('100'))",
        )
    label = getattr(target, "label", "") or f"{role}.{field_key}"
    return str(role), str(field_key), str(label)


# ==================== 反解：已有 JSON → 具名效果 ====================


def effects_from_specs(effects: Sequence[Any], *, declared_types: dict[str, str] | None = None) -> list[Effect]:
    """把已有的 `effects` JSON 反解成具名效果（用于读取旧合同类型做体检）。

    反解按「引擎 op + 值形态」判定，与 `Effect.to_spec()` 的编译规则互为逆运算：

    | op | 标量值 | 数组值 | 字面量字典 |
    | --- | --- | --- | --- |
    | `ADD` | `add_number` | `append_items` | `add_dict` |
    | `SUB` | `sub_number` | `remove_items` / `remove_keys` | `sub_dict` |
    | `SET` | `set_number` / `set_value` | `set_items` | `set_dict` |

    `declared_types` 传「角色.字段 → 字段类型」时，可用字段类型把 `SUB + 数组`
    进一步区分为 `remove_keys`（字典删键）或 `remove_items`（列表移除）。
    无法归类的行会被**跳过**，由调用方原样保留，避免反解造成信息丢失。
    """
    out: list[Effect] = []
    for raw in effects or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("kind") != "FIELD":
            continue
        op = str(raw.get("op") or "ADD").upper()
        role = str(raw.get("party") or "")
        field_key = str(raw.get("fieldKey") or "")
        if not role or not field_key:
            continue
        value_spec = raw.get("value")
        shape = _value_shape(value_spec)
        kind = _pick_kind(op, shape, (declared_types or {}).get(f"{role}.{field_key}"))
        if kind is None:
            continue
        out.append(
            Effect(
                kind,
                role,
                field_key,
                _value_from_spec(value_spec, kind),
                target_label=f"{role}.{field_key}",
            )
        )
    return out


def _pick_kind(op: str, shape: str, field_type: str | None) -> str | None:
    ft = (field_type or "").upper()
    if shape == "list" and op == "SUB" and ft == "DICTIONARY":
        return "remove_keys"
    candidates = _VALUESHAPE_TO_KINDS.get((op, shape), ())
    if ft:
        for name in candidates:
            if EFFECT_KINDS[name][0] == ft:
                return name
    return candidates[0] if candidates else None


def _value_shape(spec: Any) -> str:
    """判定效果 value 的值形态：dict（字面量字典）/ list（数组）/ scalar（标量）。"""
    if isinstance(spec, list):
        return "list"
    if isinstance(spec, dict):
        t = spec.get("type")
        if t is None:
            # 没有 type 的老数据：整个对象就是字面量字典
            return "dict"
        if t == "CONST":
            inner = spec.get("value")
            if isinstance(inner, dict):
                return "dict"
            if isinstance(inner, list):
                return "list"
            return "scalar"
        if t == "OP":
            return "list" if str(spec.get("op") or "").startswith("LIST_") else "scalar"
        return "scalar"
    return "scalar"


def _value_from_spec(spec: Any, kind: str) -> Value:
    """把已有 JSON 值源包回 Value。

    - 字典类效果（add_dict / sub_dict / set_dict）：把字面量展开成 `{键: Value}`
      （含老数据的「裸字典、无 type」形态），以便重新编译时与具名效果形状一致；
    - 其余：原样包回（保持原字符串，不做归一）。
    """
    if kind in ("add_dict", "sub_dict", "set_dict"):
        inner = spec
        if isinstance(spec, dict) and spec.get("type") == "CONST":
            inner = spec.get("value")
        if isinstance(inner, dict):
            return {  # type: ignore[return-value]
                str(k): Value({"type": "CONST", "value": v}, label=f"常量 {v!r}")
                for k, v in inner.items()
            }
    if isinstance(spec, dict) and "type" in spec:
        return Value(spec)
    return Value({"type": "CONST", "value": spec})
