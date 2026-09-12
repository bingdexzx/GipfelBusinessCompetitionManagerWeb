"""低抽象值层：把「值从哪来」写成看得见的构造，编译成引擎的值源 JSON。

为什么要重写值层
----------------
引擎的值源（`engine.eval_value_spec`）是正确的，但表达它需要三层抽象：

    {"type": "ENTITY", "entityType": "MATERIAL", "entityRef": "hidden_input",
     "attribute": "price", "multiplyByInput": "qty"}

- `entityRef` 指向**某个输入项的 key**，于是「引用一个固定原料」必须先造隐藏输入项；
- `attribute` 走 `getattr(camel→snake, 0)` 反射，**属性名写错静默取 0**；
  （`MATERIAL` 类型在旧字段表里就声明了并不存在的 `price`，走这条路恒为 0）
- `multiplyByInput` 是第三个隐式依赖。

本层把它压平成**一层具名构造**，并在 `build()` 阶段逐项校验：

    material("铁矿石").carbon            # → ENTITY，属性已校验存在
    total_price(plate, at=buyer)         # → INPUT + PRICE 聚合（口径唯一）
    number("1") + var("qty") * 2         # → OP 树

设计约束
--------
1. **本模块是纯 Python**：不 import Django、不查库。所有「名字是否存在」的校验由
   调用方（`builder` 配合 `refs` 快照）在构建期完成。
2. **属性白名单来自模型真实字段**（见 `ENTITY_ATTRIBUTES`），而不是手写的期望表——
   这样「声明的字段不存在」这类问题在定义层就不可能发生。
3. **口径唯一**：原料单价只能走 `total_price()`（引擎的 MATCH 口径：地点价 → 回退均价），
   `ENTITY` 不再暴露任何取价属性，杜绝两条路径给出不同答案。
"""
from __future__ import annotations

from typing import Any, Iterable

from .errors import BuildError

# ==================== 实体属性白名单 ====================
# 只列**模型上真实存在**的标量字段（已剔除 id / created_at / updated_at）。
# 键是引擎的实体类型名（engine.ENTITY_MODEL_NAMES 的键），值是该类型可读的属性。
#
# 刻意排除：
# - MATERIAL.price —— 模型上没有该字段（价格存在 node_prices JSON 里，按地图节点存），
#   读它恒为 0。取价请用 total_price() / avg_price()，走引擎聚合口径。
# - TECH_NODE.researchCost —— 单点取值请用 tech_research_cost()，与聚合口径保持一致。
ENTITY_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "MATERIAL": ("name", "origin", "carbonEmissionCoefficient", "type"),
    "PART": ("name",),
    "PRODUCT": ("name",),
    "TECH_NODE": ("name", "description", "tier"),
    "WAREHOUSE": ("name", "capacity", "price", "type"),
    "PRODUCTION_LINE": ("name", "price", "laborCount", "maxPerYear"),
    "FUEL": ("name", "pricePerLiter"),
    "VEHICLE": ("name", "fuelConsumptionPerKm", "maxCargo", "price", "carbonEmission"),
    "INFRASTRUCTURE": (
        "name",
        "footprint",
        "price",
        "activationPrice",
        "employmentRateBonus",
        "populationBonus",
        "highQualityPopulationBonus",
        "happinessIndexBonus",
        "perCapitaIncomeBonus",
        "carbonReductionBonus",
    ),
    "MAP_NODE": ("name", "region", "x", "y"),
}

# 中文名（报错与文档用）
ENTITY_TYPE_LABEL: dict[str, str] = {
    "MATERIAL": "原料",
    "PART": "零件",
    "PRODUCT": "成品",
    "TECH_NODE": "科技节点",
    "WAREHOUSE": "仓库",
    "PRODUCTION_LINE": "生产线",
    "FUEL": "燃料",
    "VEHICLE": "载具",
    "INFRASTRUCTURE": "基建",
    "MAP_NODE": "地图节点",
}

# ==================== 输入项类型 ====================
# 与前端 ContractManageView 实际渲染分支一一对应（15 种）。
INPUT_TYPES: tuple[str, ...] = (
    "number",
    "string",
    "boolean",
    "ENTITY",
    "nodeRoute",
    "mapNode",
    "list",
    "dict",
    "materialList",
    "partList",
    "productList",
    "infrastructureList",
    "fuelList",
    "vehicleList",
    "warehouseList",
    "techNode",
)

# 清单类输入项：值是 {名称: 数量} 字典，可参与聚合
LIST_INPUT_TYPES: tuple[str, ...] = (
    "materialList",
    "partList",
    "productList",
    "infrastructureList",
    "fuelList",
    "vehicleList",
    "warehouseList",
)

# 清单类输入项 → 对应的实体类型（用于校验实体引用与清单是否同类）
LIST_INPUT_ENTITY: dict[str, str] = {
    "materialList": "MATERIAL",
    "partList": "PART",
    "productList": "PRODUCT",
    "infrastructureList": "INFRASTRUCTURE",
    "fuelList": "FUEL",
    "vehicleList": "VEHICLE",
    "warehouseList": "WAREHOUSE",
}

# 比较运算符（引擎 compare_op / compare_field）
COMPARE_OPS: tuple[str, ...] = ("GTE", "LTE", "GT", "LT", "EQ")
CONTAINER_COMPARE_OPS: tuple[str, ...] = ("CONTAINS", "HAS_KEY", "LEN_GTE", "LEN_LTE", "LEN_EQ")


def _normalize_cmp_type(comp_type: str) -> str:
    """把 Python 运算符名归一成引擎的 CMP_* 名。"""
    key = str(comp_type).upper()
    if not key.startswith("CMP_"):
        key = f"CMP_{key}"
    if key not in ("CMP_EQ", "CMP_NE", "CMP_GT", "CMP_LT", "CMP_GTE", "CMP_LTE"):
        raise BuildError(f"不支持的比较运算：{comp_type}")
    return key


# ==================== 值 ====================


class Value:
    """一个值来源。所有表达式构造都返回本类型，`to_spec()` 输出引擎 JSON。

    支持 Python 运算符，便于把公式写成算术式：

        total = number("1") + var("qty") * 2
        cond  = buyer.field("cash") >= total
    """

    __slots__ = ("spec", "label", "input_type")

    def __init__(self, spec: dict, *, label: str = "", input_type: str = "") -> None:
        if not isinstance(spec, dict) or "type" not in spec:
            raise BuildError(f"值的描述非法（缺少 type）：{spec!r}")
        self.spec = spec
        self.label = label
        #: 当本值是输入项时，记录其输入类型（构建期用于校验清单类型是否匹配）。
        #: 引擎不读这个字段，它只服务于本库的静态校验。
        self.input_type = input_type

    # ---------- 编译 ----------

    def to_spec(self) -> dict:
        """编译为引擎值源 JSON（返回副本，避免调用方改动内部状态）。"""
        return _deep_copy(self.spec)

    # ---------- 展示 ----------

    @property
    def describe(self) -> str:
        """人类可读的一句话说明（体检报告与文档用）。"""
        if self.label:
            return self.label
        t = self.spec.get("type")
        if t == "CONST":
            return f"常量 {self.spec.get('value')!r}"
        if t == "INPUT":
            agg = self.spec.get("aggregate")
            key = self.spec.get("key")
            return f"输入项 {key}" + (f"（聚合 {agg}）" if agg else "")
        if t == "FIELD":
            return f"{self.spec.get('party')} 的字段 {self.spec.get('fieldKey')}"
        if t == "VAR":
            return f"变量 {self.spec.get('name')}"
        if t == "OP":
            return f"运算 {self.spec.get('op')}"
        if t == "FORMULA":
            return f"公式 {self.spec.get('expr')}"
        if t == "ENTITY":
            return (
                f"{ENTITY_TYPE_LABEL.get(self.spec.get('entityType'), self.spec.get('entityType'))}"
                f"的属性 {self.spec.get('attribute')}"
            )
        if t == "PARTY_COMPANY_NAME":
            return f"{self.spec.get('party')} 的公司名称"
        if t == "INDUSTRY_IS":
            return f"{self.spec.get('party')} 的产业类型判断"
        if t == "ROUTE":
            return "路程"
        return str(t)

    def __repr__(self) -> str:  # pragma: no cover - 调试可读性
        return f"Value({self.describe})"

    # ---------- 算术 ----------

    def _op(self, op: str, other: Any, *, reverse: bool = False) -> "Value":
        left, right = (_as_value(other), self) if reverse else (self, _as_value(other))
        return Value({"type": "OP", "op": op, "args": [left.to_spec(), right.to_spec()]})

    def __add__(self, other: Any) -> "Value":
        return self._op("ADD", other)

    def __radd__(self, other: Any) -> "Value":
        return self._op("ADD", other, reverse=True)

    def __sub__(self, other: Any) -> "Value":
        return self._op("SUB", other)

    def __rsub__(self, other: Any) -> "Value":
        return self._op("SUB", other, reverse=True)

    def __mul__(self, other: Any) -> "Value":
        return self._op("MUL", other)

    def __rmul__(self, other: Any) -> "Value":
        return self._op("MUL", other, reverse=True)

    def __truediv__(self, other: Any) -> "Value":
        return self._op("DIV", other)

    def __rtruediv__(self, other: Any) -> "Value":
        return self._op("DIV", other, reverse=True)

    # ---------- 比较（产出可直接当条件用的布尔值） ----------

    def _cmp(self, comp_type: str, other: Any) -> "Value":
        return Value(
            {"type": "OP", "op": _normalize_cmp_type(comp_type), "args": [self.to_spec(), _as_value(other).to_spec()]},
            label=f"{self.describe} {_CMP_SYMBOL.get(_normalize_cmp_type(comp_type), comp_type)} {_as_value(other).describe}",
        )

    def __ge__(self, other: Any) -> "Value":  # type: ignore[override]
        return self._cmp("GTE", other)

    def __le__(self, other: Any) -> "Value":  # type: ignore[override]
        return self._cmp("LTE", other)

    def __gt__(self, other: Any) -> "Value":  # type: ignore[override]
        return self._cmp("GT", other)

    def __lt__(self, other: Any) -> "Value":  # type: ignore[override]
        return self._cmp("LT", other)

    def equals(self, other: Any) -> "Value":
        """等于比较（不用 `==`，避免与对象相等语义混淆）。"""
        return self._cmp("EQ", other)

    def not_equals(self, other: Any) -> "Value":
        return self._cmp("NE", other)

    # ---------- 逻辑 ----------

    def and_(self, *others: Any) -> "Value":
        return _logic("AND", (self, *others))

    def or_(self, *others: Any) -> "Value":
        return _logic("OR", (self, *others))

    def not_(self) -> "Value":
        return _logic("NOT", (self,))


_CMP_SYMBOL = {"CMP_GTE": "≥", "CMP_LTE": "≤", "CMP_GT": ">", "CMP_LT": "<", "CMP_EQ": "=", "CMP_NE": "≠"}


def _as_value(raw: Any) -> Value:
    """把裸 Python 值转成 Value。

    支持四种输入：
    - `Value` 本身；
    - 裸 Python 值（数字/字符串/布尔/列表/字典）→ CONST；
    - `FieldRef`（`party.field("cash")`）→ 引擎的 `FIELD` 值源，
      于是 `buyer.field("cash") >= amount` 能直接写；
    - `PartyRef` 误传 → 给出明确报错（而不是编译出一个坏 JSON）。
    """
    if isinstance(raw, Value):
        return raw
    # FieldRef / PartyRef 是鸭子类型识别（避免与 builder.py 形成循环导入）
    role = getattr(raw, "role", None)
    if role is not None:
        field_key = getattr(raw, "field_key", None)
        if field_key is not None:
            return Value(
                {"type": "FIELD", "party": str(role), "fieldKey": str(field_key)},
                label=getattr(raw, "label", "") or f"{role}.{field_key}",
            )
        raise BuildError(
            f"参与方「{role}」本身不是值，不能直接参与运算",
            hint="请指明字段：party.field('cash')；或取公司名：party.company_name()",
        )
    if isinstance(raw, bool):
        return Value({"type": "CONST", "value": raw}, label=f"常量 {raw}")
    if isinstance(raw, (int, float)):
        return Value({"type": "CONST", "value": _num_text(raw)}, label=f"常量 {raw}")
    if isinstance(raw, str):
        return Value({"type": "CONST", "value": raw}, label=f"常量 {raw!r}")
    if isinstance(raw, (list, dict)):
        return Value({"type": "CONST", "value": raw}, label="常量集合")
    if raw is None:
        return Value({"type": "CONST", "value": None}, label="空值")
    raise BuildError(
        f"不能把 {type(raw).__name__} 当作值使用：{raw!r}",
        hint="值只能是数字 / 字符串 / 布尔 / 列表 / 字典，或用 number()/text()/var()/input() 等构造",
    )


def _num_text(raw: Any) -> str:
    """数字转字符串：整数不带小数点，避免 CONST 里出现 "1.0" 这类会被引擎按浮点解析的值。"""
    if isinstance(raw, bool):
        return "1" if raw else "0"
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        if raw.is_integer():
            return str(int(raw))
        return repr(raw)
    return str(raw)


def _logic(op: str, values: Iterable[Any]) -> Value:
    """逻辑运算编译成 FORMULA（引擎的 EXPR_HELPERS 提供 IF/AND/OR/NOT）。

    为什么不直接用 OP：引擎的 apply_op 里没有 AND/OR/NOT，只有 CMP_* 与算术；
    布尔组合必须走 safe_evaluate 沙箱。
    """
    parts: list[str] = []
    for v in values:
        spec = _as_value(v).to_spec()
        parts.append(_spec_to_expr(spec))
    expr = f"{op}({', '.join(parts)})"
    return Value({"type": "FORMULA", "expr": expr}, label=f"{op}({', '.join(p for p in parts)})")


def _spec_to_expr(spec: dict) -> str:
    """把一个值源拼成 safe_evaluate 可求值的表达式片段。

    只覆盖逻辑组合会用到的形状：CMP_* 比较、其它值源（走输入项/变量名）。
    """
    t = spec.get("type")
    if t == "OP":
        op = str(spec.get("op") or "")
        args = spec.get("args") or []
        if op.startswith("CMP_"):
            symbol = {
                "CMP_EQ": "==",
                "CMP_NE": "!=",
                "CMP_GT": ">",
                "CMP_LT": "<",
                "CMP_GTE": ">=",
                "CMP_LTE": "<=",
            }.get(op)
            if symbol and len(args) == 2:
                return f"({_spec_to_expr(args[0])} {symbol} {_spec_to_expr(args[1])})"
        arith = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/"}.get(op)
        if arith and len(args) == 2:
            return f"({_spec_to_expr(args[0])} {arith} {_spec_to_expr(args[1])})"
        raise BuildError(
            f"逻辑组合里暂不支持运算 {op}",
            hint="请把该运算的结果先 assign() 成变量，再用变量参与逻辑组合",
        )
    if t == "FORMULA":
        return f"({spec.get('expr')})"
    if t == "CONST":
        return repr(spec.get("value"))
    if t == "INPUT":
        if spec.get("aggregate"):
            raise BuildError(
                "逻辑组合里暂不支持带聚合的输入项",
                hint="请先 assign() 成变量，再用变量参与逻辑组合",
            )
        return f"inputs[{spec.get('key')!r}]"
    if t == "VAR":
        return f"scope[{spec.get('name')!r}]"
    if t == "FIELD":
        return f"fieldValue({spec.get('party')!r}, {spec.get('fieldKey')!r})"
    raise BuildError(
        f"逻辑组合里暂不支持的值来源：{t}",
        hint="请先 assign() 成变量，再用变量参与逻辑组合",
    )


def _deep_copy(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj


# ==================== 值的构造器 ====================


def number(raw: Any) -> Value:
    """数值常量。写成字符串可保精度（引擎的 to_number 对整数字符串走 int）。"""
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise BuildError(f"number() 只接受数字或数字字符串，收到 {type(raw).__name__}: {raw!r}")
    text = _num_text(raw) if isinstance(raw, (int, float, bool)) else str(raw).strip()
    if text == "":
        raise BuildError("number() 不能为空字符串")
    return Value({"type": "CONST", "value": text}, label=f"数值 {text}")


def text(raw: Any) -> Value:
    """文本常量。"""
    if raw is None:
        raise BuildError("text() 不能为 None；空文本请写 text('')")
    return Value({"type": "CONST", "value": str(raw)}, label=f"文本 {str(raw)!r}")


def flag(raw: Any) -> Value:
    """布尔常量。"""
    return Value({"type": "CONST", "value": bool(raw)}, label=f"布尔 {bool(raw)}")


def const(raw: Any) -> Value:
    """任意常量（含列表 / 字典，引擎会按 JSON 解析）。"""
    return _as_value(raw)


def var(name: str) -> Value:
    """变量引用：循环变量（`for_each(var="row")`）或 `ct.assign()` 定义的中间值。

    引擎的 `VAR` 求值顺序是「先查作用域，再查输入项」，所以这里也能读到输入项的
    运行期值；但那样写不直观，读输入项请用 `input_value()`。
    """
    key = str(name or "").strip()
    if not key:
        raise BuildError("var() 需要变量名")
    return Value({"type": "VAR", "name": key}, label=f"变量 {key}")


def input_value(source: Any) -> Value:
    """读取某个输入项的**运行期值**（不是声明时的默认值）。

    与 `var()` 的区别是意图明确：`var()` 读变量，`input_value()` 读输入项。
    两者在引擎里都会编译成 `{"type":"VAR","name":...}`（引擎先查作用域、再查输入项），
    但分开写能让体检准确报错、也让代码更易读。

    典型用途：把一个输入项的值（如「引进的科技名」）写进列表字段：
    `ct.append_items(p.field("tech_list"), input_value(tech))`
    """
    if isinstance(source, Value) and source.to_spec().get("type") == "INPUT":
        key = str(source.to_spec().get("key"))
        return Value({"type": "VAR", "name": key}, label=f"输入项值 {key}")
    if isinstance(source, str) and source.strip():
        return Value({"type": "VAR", "name": source.strip()}, label=f"输入项值 {source.strip()}")
    raise BuildError(
        f"input_value() 需要输入项，收到 {type(source).__name__}",
        hint="正确写法：input_value(ct.input('tech', '科技', 'techNode'))",
    )


def range_list(start: Any, stop: Any, step: Any = 1) -> Value:
    """整数序列（引擎 `LIST_RANGE`，左闭右开）。

    用途：`for_each` 需要一个**列表**才能遍历。要「按 1..N 循环」时用它：

        with ct.for_each(range_list(1, months + 1), var="period"):
            ct.add_dict(p.field("terms"), {"待还期数": 1})

    注意 `stop` 是开区间（与 Python 的 range 一致），所以 1..months 要写 `months + 1`。
    """
    return Value(
        {
            "type": "OP",
            "op": "LIST_RANGE",
            "args": [_as_value(start).to_spec(), _as_value(stop).to_spec(), _as_value(step).to_spec()],
        },
        label="整数序列",
    )


def concat_text(*parts: Any) -> Value:
    """把若干值拼成一段文本。

    **不能用 `+` 拼字符串**：`+` 编译成引擎的 `OP:ADD`，而 `apply_op` 的 ADD 走数值路径
    （`to_number`），两段文本都会被转成 **0**。拼接必须用公式沙箱的 `concat`：

        concat_text(route_start_node(route), " → ", route_end_node(route))
        # → FORMULA: concat(输入项名, ' → ', 输入项名)
    """
    if not parts:
        raise BuildError("concat_text() 至少需要一个片段")
    pieces = [_spec_to_expr(_as_value(p).to_spec()) for p in parts]
    expr = f"concat({', '.join(pieces)})"
    return Value({"type": "FORMULA", "expr": expr}, label="拼接文本")


def join_text(items: Any, sep: str = ",") -> Value:
    """把列表值用分隔符拼成文本（引擎 `LIST_JOIN`）。

    例：把路程经过的路径类型拼成 `公路/铁路`。
    """
    spec = _as_value(items).to_spec()
    return Value(
        {"type": "OP", "op": "LIST_JOIN", "args": [spec, {"type": "CONST", "value": str(sep)}]},
        label="拼接列表",
    )


def formula(expr: str) -> Value:
    """自由公式（引擎 safe_evaluate 沙箱）。

    可用名字：输入项 key（顶层）、循环变量与 assign 变量（顶层）、
    逻辑助手 `IF / AND / OR / NOT`、容器助手 `len / get / keys / values / has /
    hasKey / merge / unique / flatten / join / push / concat / contains / indexIn / sumOf`、
    数学函数 `abs / sqrt / cbrt / sign / floor / ceil / round / trunc / pow / exp / log /
    log2 / log10 / sin / cos / tan / ... / min / max / sum / avg`（**都是小写**），
    以及常量 `pi / e`。

    注意：**没有** `inputs` / `scope` 这两个字典对象，也没有 `range`；
    需要整数序列请用 `ct.range_list(...)`。
    """
    src = str(expr or "").strip()
    if not src:
        raise BuildError("formula() 需要非空表达式")
    return Value({"type": "FORMULA", "expr": src}, label=f"公式 {src}")


def route_distance(nodes: Value) -> Value:
    """路程距离（对 `nodeRoute` 输入项求相邻节点最短路径距离之和）。"""
    return Value({"type": "ROUTE", "routeRef": _require_input_key(nodes, "route_distance")}, label="路程距离")


def route_path_types(nodes: Value) -> Value:
    """路程经过的路径类型列表。"""
    return _input_aggregate(nodes, "ROUTE_PATH_TYPES", "路程路径类型")


def route_start_node(nodes: Value) -> Value:
    """路程起始节点名。"""
    return _input_aggregate(nodes, "ROUTE_START_NODE_NAME", "路程起始节点名")


def route_end_node(nodes: Value) -> Value:
    """路程终止节点名。"""
    return _input_aggregate(nodes, "ROUTE_END_NODE_NAME", "路程终止节点名")


def company_name(party: Any) -> Value:
    """参与方所绑定公司的名称。"""
    role = _party_role(party)
    return Value({"type": "PARTY_COMPANY_NAME", "party": role}, label=f"{role} 的公司名称")


def industry_is(party: Any, industry_type_id: int) -> Value:
    """参与方公司的产业类型是否等于给定 id（布尔）。"""
    role = _party_role(party)
    try:
        tid = int(industry_type_id)
    except (TypeError, ValueError):
        raise BuildError(f"industry_is 需要整数产业类型 id，收到 {industry_type_id!r}")
    return Value({"type": "INDUSTRY_IS", "party": role, "industryTypeId": tid}, label=f"{role} 是产业#{tid}")


def _require_input_key(value: Any, who: str) -> str:
    v = _as_value(value)
    spec = v.to_spec()
    if spec.get("type") != "INPUT":
        raise BuildError(
            f"{who}() 需要传入一个输入项（如 input('nodes', '节点列表', 'nodeRoute')）",
            hint=f"收到的是：{v.describe}",
        )
    return str(spec.get("key") or "")


def _input_aggregate(value: Any, aggregate: str, label: str) -> Value:
    key = _require_input_key(value, label)
    return Value({"type": "INPUT", "key": key, "aggregate": aggregate}, label=f"{label}（{key}）")


def _party_role(party: Any) -> str:
    """从参与方对象 / 字符串取出 role。"""
    role = getattr(party, "role", None)
    if role:
        return str(role)
    if isinstance(party, str) and party.strip():
        return party.strip()
    raise BuildError(
        f"需要参与方，收到 {type(party).__name__}",
        hint="请用 ct.party('buyer', '买方') 的返回值，或直接传角色字符串",
    )
