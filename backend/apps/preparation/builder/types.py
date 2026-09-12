"""建包库的公共类型：异常、引用、字段助手、计算图助手。

本模块为纯 Python（不导入 Django、不访问数据库），可脱离 Django 单独使用，
便于脚本作者本地生成归档 JSON。
"""
from __future__ import annotations

from typing import Any


# ==================== 异常 ====================


class BuilderError(Exception):
    """建包库使用错误（缺必填、名称重复、引用不存在、类型非法等）。

    注意：这是**写脚本时**的错误，应在 build() 阶段就抛出，不会污染数据库；
    与「导入阶段」的 archive.ArchiveError 分工不同。
    """


# ==================== 引用 ====================


class Ref:
    """指向某项已登记资源实例的引用（如某个区域、某个零件）。

    使用方式：登记方法（company / part / region …）返回本对象，
    可直接作为其它方法的参数传下去；字符串形式的名称会在内部自动转成本类型。
    """

    __slots__ = ("resource", "name")

    def __init__(self, resource: str, name: str) -> None:
        self.resource = resource
        self.name = str(name)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试可读性
        return f"Ref({self.resource}:{self.name})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Ref):
            return self.resource == other.resource and self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.resource, self.name))


# ==================== 取值助手 ====================


def resolve_ref(ref: Any, resource: str, field: str) -> str:
    """把参数统一解析成「名称字符串」。

    允许三种写法：
    - Ref（登记方法的返回值）——资源类型必须一致，否则报错，避免张冠李戴；
    - str —— 直接当名称用（已存在于目标比赛的对象也可这样引用）；
    - None —— 报错（该字段必填）。
    """
    if ref is None:
        raise BuilderError(f"{field} 不能为空（需要 {resource} 的引用或名称）")
    if isinstance(ref, Ref):
        if ref.resource != resource:
            raise BuilderError(
                f"{field} 需要 {resource} 的引用，但拿到的是 {ref.resource} 的引用：{ref.name!r}"
            )
        return ref.name
    if isinstance(ref, str):
        name = ref.strip()
        if not name:
            raise BuilderError(f"{field} 不能为空字符串")
        return name
    raise BuilderError(
        f"{field} 只接受 {resource} 的引用或名称字符串，收到 {type(ref).__name__}: {ref!r}"
    )


def refs_of(value: Any, resource: str, field: str) -> list[str]:
    """把「单个引用 / 引用列表 / 名称字典」统一解析成名称列表（保持顺序、去重）。"""
    if value is None:
        return []
    if isinstance(value, dict):
        raw: list[Any] = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = [value]
    out: list[str] = []
    for item in raw:
        name = resolve_ref(item, resource, field)
        if name not in out:
            out.append(name)
    return out


def positive_int(value: Any, field: str, *, default: int = 0) -> int:
    """非负整数校验（用于 x / y / tier / sortOrder 等）。"""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuilderError(f"{field} 必须是整数，收到 {type(value).__name__}: {value!r}")
    if value < 0:
        raise BuilderError(f"{field} 不能为负数：{value}")
    return value


def require_text(value: Any, field: str) -> str:
    """必填文本（去空白后不能为空）。"""
    if value is None:
        raise BuilderError(f"{field} 为必填项")
    text = str(value).strip()
    if not text:
        raise BuilderError(f"{field} 不能为空")
    return text


# ==================== 财年定时器 ====================

TIMER_FY_START = "FY_START"
TIMER_FY_END = "FY_END"
TIMER_TRIGGERS = (TIMER_FY_START, TIMER_FY_END)

# 字段类型（与 apps.industry_types.models.IndustryField.TYPE_CHOICES 一致）
FIELD_TYPES = ("STRING", "NUMBER", "BOOLEAN", "DICTIONARY", "LIST")


# ==================== 产业计算图（GGraph）助手 ====================
# calcGraph 是前端「产业计算图」的 GGraph JSON。这里提供最小可用的构造助手：
# 生成的结构与前端 graph-model 兼容（nodes + edges），可用 calc_graph() 直接挂到字段上。
# 需要复杂图（多输入、常量节点等）时，把 graph=... 换成从可视化界面导出/手写的 JSON 即可。

# 计算图节点类型
CALC_TYPES = {
    "add": "ADD",       # 加法：所有输入相加
    "sub": "SUB",       # 减法：第一个输入减其余输入
    "mul": "MUL",       # 乘法：所有输入相乘
    "div": "DIV",       # 除法：第一个输入除其余输入
    "field": "FIELD",   # 引用本公司另一个产业字段
    "const": "CONST",   # 常量
    "sum": "SUM",       # 聚合：对某字段在全比赛范围内求和/求均值
    "avg": "AVG",
    "max": "MAX",
    "min": "MIN",
}


def calc_node(node_type: str, *, node_id: str | None = None, **config: Any) -> dict:
    """构造一个计算图节点。

    node_type 可用 CALC_TYPES 里的短名（add/mul/field/const/sum/avg/max/min）或原始类型名。
    FIELD 节点需 fieldKey=...；CONST 节点需 value=...；聚合节点需 fieldKey=...（可选 scope）。
    """
    key = str(node_type).strip()
    resolved = CALC_TYPES.get(key.lower(), key.upper())
    node: dict[str, Any] = {"id": node_id or resolved.lower(), "type": resolved}
    node.update(config)
    return node


def calc_graph(*nodes: dict, edges: list | None = None, **extra: Any) -> dict:
    """把若干 calc_node 组装成 calcGraph。

    edges 省略时按 nodes 的传入顺序自动串联成一条链（第一个节点为根），
    这是最常见的「字段 A + 字段 B → 本字段」场景：calc_graph(calc_node("add"))。
    """
    node_list = [n for n in nodes if isinstance(n, dict)]
    if not node_list:
        raise BuilderError("calc_graph 至少需要一个 calc_node(...) 节点")
    ids = [str(n["id"]) for n in node_list]
    if len(set(ids)) != len(ids):
        raise BuilderError(f"calc_graph 的节点 id 必须唯一，当前为 {ids}")
    if edges is None:
        edge_list = [
            {"from": ids[i + 1], "to": ids[i], "fromPort": "out", "toPort": f"in{i + 1}"}
            for i in range(len(node_list) - 1)
        ]
    else:
        edge_list = list(edges)
    graph: dict[str, Any] = {"nodes": node_list, "edges": edge_list}
    graph.update(extra)
    return graph
