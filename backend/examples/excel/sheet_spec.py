# -*- coding: utf-8 -*-
"""比赛建包表格规范（Excel / CSV）：**一张工作表 = 一类内容**，只描述「比赛框架」。

只建框架，不建运行数据
----------------------

本规范只覆盖**换一场比赛仍然成立**的东西：比赛本身、财年、**股票市场规则（股票参数）**、
行业口径（产业类型 / 产业字段）、地图与路径、物资与产能（燃料 / 原料 / 科技 / 零件 / 产品 /
载具 / 生产线 / 基建 / 仓库）、消费者需求、合同类型（模板）。

**参赛主体与运行期内容不走 Excel**（见 `OUT_OF_SCOPE_SHEETS`）：公司、公司字段值、账号、
区域总览卡片、比赛内的合同实例、消息，以及**个股 / 资金账户 / 持仓 / 委托 / K 线** ——
它们都绑定具体公司、具体人、具体主键或只在运行时产生，
请在前端界面（公司管理 / 账号管理 / 合同管理 / 消息中心 / 股票管理 / 股票行情）维护，
或用代码建包脚本 `examples/competitions/auto_chain_competition.py`。
工作簿里若出现这些表名，程序会明确告诉你「该去哪里维护」，而不是静默忽略。

设计原则
--------

1. **一表一类内容**：想建什么就放哪张表，不放的表完全不参与产出 —— 这就是「不同表实现内容隔离」。
2. **没有新的落库路径**：本规范只是把表格翻译成 `CompetitionBuilder` 的调用，
   最终仍由既有的 `archive.apply_import` 落库，与代码建包、前端导入完全同构。
3. **表头用中文**（如「比赛名称」「字段键」），程序也接受英文参数名（老文件兼容）；
   中文表头 ↔ 参数名的对照见 `HEADERS`，模板的「说明」表里也有一份。
4. **单元格语法尽量贴近 Excel 习惯**：
   - 空单元格 = 不传该参数（用建包库默认值）；
   - 布尔：`是/否`、`TRUE/FALSE`、`1/0`、`y/n`；
   - 列表：`公路;铁路`（分号、顿号、逗号、换行都可以当分隔符）；
   - 配比 / 地点价 / 键值：`锂矿石*4; 铝土矿*1` 或 `白云鄂博矿区:180; 上游集运站:195`；
   - 以 `{` 或 `[` 开头的单元格按 **JSON** 解析（复杂结构直接用 JSON）；
   - 以 `#` 开头的行是注释，整行忽略。

工作表清单（按依赖顺序处理，worksheet 在文件里的先后不影响结果）
------------------------------------------------------------

    比赛 → 财年 → 股票参数
    产业类型 → 产业字段
    区域
    地图节点类型 → 路径类型 → 地图节点 → 地图连线
    燃料 → 原料 → 科技 → 生产线 → 基建 → 仓库 → 零件 → 产品 → 载具
    消费者需求
    合同类型（只写脚本路径 + 类型标识，四份 JSON 由代码脚本产出）

**个股 / 资金账户 / 持仓 / 委托 / K 线不在本规范内**：它们绑定具体公司、具体人或具体主键，
只在「股票管理」「股票行情」里维护/产生。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# =============================================================================
# 单元格语法
# =============================================================================

_ITEM_SEP_CHARS = set(";；\n、,，")
_PAIR_SEP_RE = re.compile(r"[:：*=×]")
_TRUE_WORDS = {"是", "对", "true", "y", "yes", "1", "t", "✓", "√"}
_FALSE_WORDS = {"否", "不", "false", "n", "no", "0", "f", "×", "x"}


class SheetFormatError(ValueError):
    """表格内容不符合规范（会带工作表名与行号）。"""


def is_json_cell(text: str) -> bool:
    s = (text or "").strip()
    return s.startswith("{") or s.startswith("[")


def smart_split(text: str) -> list[str]:
    """按分号 / 顿号 / 逗号 / 换行切分，但**不切进 JSON 与引号内部**。

    这样 `goods={"锂矿石": 20, "铝土矿": 5}` 这种内嵌 JSON 的单元格不会被逗号切碎。
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    for ch in str(text or ""):
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth = max(0, depth - 1)
        if depth == 0 and ch in _ITEM_SEP_CHARS:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def as_bool(text: str | None, *, default: bool | None = None) -> bool | None:
    s = str(text or "").strip().lower()
    if s == "":
        return default
    if s in _TRUE_WORDS:
        return True
    if s in _FALSE_WORDS:
        return False
    raise SheetFormatError(f"无法识别的布尔值「{text}」（请用 是/否）")


def as_items(text: str | None) -> list[str]:
    """列表单元格 → 字符串列表。"""
    s = str(text or "").strip()
    if s == "":
        return []
    if is_json_cell(s):
        data = json.loads(s)
        if not isinstance(data, list):
            raise SheetFormatError(f"列表单元格的 JSON 必须是数组：{s[:40]}")
        return [str(x) for x in data]
    return smart_split(s)


def _as_scalar(text: str) -> Any:
    """标量：能当数字就当数字（配比/价格），否则保留文本。"""
    s = str(text).strip()
    if s == "":
        return ""
    try:
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
        return float(s)
    except ValueError:
        return s


def as_map(text: str | None, *, keep_text: bool = False) -> dict[str, Any]:
    """键值对单元格 → dict。

    支持 `名称:数量` / `名称*数量` / `名称=数量`，也支持整格 JSON（`{"名称": 数量}`）。

    `keep_text=True` 时值一律保留**原文**（金额/单价这类 Decimal 字段建议这样，
    避免 float 把精度带偏；与代码建包里写 `price="600000"` 同一个道理）。
    """
    s = str(text or "").strip()
    if s == "":
        return {}
    if is_json_cell(s):
        data = json.loads(s)
        if not isinstance(data, dict):
            raise SheetFormatError(f"键值单元格的 JSON 必须是对象：{s[:40]}")
        return {str(k): (str(v) if keep_text else v) for k, v in data.items()}
    out: dict[str, Any] = {}
    for item in smart_split(s):
        parts = _PAIR_SEP_RE.split(item, maxsplit=1)
        if len(parts) != 2 or not parts[0].strip():
            raise SheetFormatError(f"键值单元格格式应为「名称:数量」，收到「{item}」")
        out[parts[0].strip()] = parts[1].strip() if keep_text else _as_scalar(parts[1])
    return out


def as_pairs(text: str | None) -> dict[str, Any]:
    """`key=value` 单元格 → dict（用于合同输入项）。

    value 以 `{` / `[` 开头按 JSON 解析；能当数字就当数字；其余保留文本。
    """
    s = str(text or "").strip()
    if s == "":
        return {}
    if is_json_cell(s):
        data = json.loads(s)
        if not isinstance(data, dict):
            raise SheetFormatError(f"输入项单元格的 JSON 必须是对象：{s[:40]}")
        return {str(k): v for k, v in data.items()}
    out: dict[str, Any] = {}
    for item in smart_split(s):
        if "=" not in item:
            raise SheetFormatError(f"输入项格式应为「key=value」，收到「{item}」")
        key, value = item.split("=", 1)
        key, value = key.strip(), value.strip()
        if is_json_cell(value):
            out[key] = json.loads(value)
        else:
            out[key] = _as_scalar(value)
    return out


def _number_or_text(text: str) -> Any:
    s = str(text or "").strip()
    return _as_scalar(s) if s != "" else None


def _industry_ref(ctx: SheetContext, text: str) -> str:
    """产业类型列的取值可以是**名称**，也可以是 **code**（建包库内部按名称登记，这里做一次归一）。"""
    s = str(text or "").strip()
    if re.fullmatch(r"[+-]?\d+", s):
        for row in ctx.builder.rows("industryTypes"):
            if str(row.get("code")) == str(int(s)):
                return str(row.get("name") or s)
    return s


# =============================================================================
# 计算图：把 `字段A + 字段B` 这种最常用的写法翻译成产业计算图 GGraph
# =============================================================================

_SUM_SEP_RE = re.compile(r"[+＋,，、;；\s]+")


# =============================================================================
# 值源形状归一：`{"from": "input", "key": X}` → `{"type": "INPUT", "key": X}`
# =============================================================================

#: 「文档形状」的 from 取值 → 引擎值源类型
_LEGACY_FROM_TYPES = {"input": "INPUT", "const": "CONST", "var": "VAR"}

#: 引擎认识的检查（condition）种类；`FIELD` 不是其中之一（老文档里写错过）
CONDITION_KINDS = ("VALUE_COMPARE", "FIELD_COMPARE", "DICT_COMPARE", "LIST_COMPARE", "INDUSTRY_IS")


def normalize_conditions(conditions: Any, *, count: list[int] | None = None) -> Any:
    """把检查里的老写法 `{"kind": "FIELD", ...}` 归一成引擎的 `FIELD_COMPARE`。

    引擎没有 `FIELD` 这个检查种类（只有 `FIELD_COMPARE` / `VALUE_COMPARE` /
    `INDUSTRY_IS` / `DICT_COMPARE` / `LIST_COMPARE`），写成 `FIELD` 时检查会**恒不通过**，
    而建包库文档与 `demo_competition.py` 里正是这么写的。
    """
    if not isinstance(conditions, list):
        return conditions
    out = []
    for item in conditions:
        if isinstance(item, dict) and item.get("kind") == "FIELD" and item.get("fieldKey"):
            item = {**item, "kind": "FIELD_COMPARE"}
            if count is not None:
                count[0] += 1
        out.append(item)
    return out


def normalize_value_specs(node: Any, *, count: list[int] | None = None) -> Any:
    """递归把老文档里的 `{"from": "input", "key": X}` 归一成引擎认识的值源。

    为什么需要：合同引擎的 `eval_value_spec` 只认 `{"type": ...}`；
    带 `"from"` 的形状会一路落到函数末尾 **静默返回 0**
    （表现是「金额恒为 0」），而建包库文档与 `demo_competition.py` 里恰好是这种写法。
    表格里贴 JSON 时两种形状都会遇到，这里统一归一，避免静默算错。
    """
    if isinstance(node, list):
        return [normalize_value_specs(item, count=count) for item in node]
    if not isinstance(node, dict):
        return node
    if "type" not in node and isinstance(node.get("from"), str):
        mapped = _LEGACY_FROM_TYPES.get(str(node["from"]).strip().lower())
        if mapped:
            if count is not None:
                count[0] += 1
            out = {k: v for k, v in node.items() if k != "from"}
            out["type"] = mapped
            out.setdefault("key", node.get("key"))
            return {k: normalize_value_specs(v, count=count) for k, v in out.items()}
    return {k: normalize_value_specs(v, count=count) for k, v in node.items()}


def field_sum_graph(expression: str) -> dict:
    """`cash + bank_deposit`（或 `cash`）→ 产业计算图（GGraph）。

    ⚠️ 结构必须与**产业计算字段求值器**（`apps/company_fields/calc.py::_eval_graph`）
    一致：节点 `type` 取 `output` / `value`，数值源写在 `data.kind`，连线用
    `source/target/sourceHandle/targetHandle`，且必须有唯一 `output` 汇点。
    （建包库自带的 `calc_node/calc_graph` 产出的是合同编辑器风格的图，求值器不认，
    详见 `docs/汽车产业链测试赛准备.md` 第 6 节。）
    """
    keys = [k for k in _SUM_SEP_RE.split(str(expression or "").strip()) if k]
    if not keys:
        raise SheetFormatError("计算图表达式为空")
    nodes: list[dict] = [{"id": "out", "type": "output", "data": {}, "position": {"x": 640, "y": 200}}]
    edges: list[dict] = []
    field_nodes = [
        {"id": f"f{i}", "type": "value", "data": {"kind": "FIELD", "fieldKey": key},
         "position": {"x": 120, "y": 120 + i * 90}}
        for i, key in enumerate(keys)
    ]
    nodes.extend(field_nodes)
    if len(keys) == 1:
        edges.append({"id": "e0", "source": "f0", "target": "out",
                      "sourceHandle": "out", "targetHandle": "value"})
    else:
        prev = None
        for i in range(len(keys) - 1):
            node_id = f"add{i}"
            nodes.append({"id": node_id, "type": "value", "data": {"kind": "OP", "op": "ADD"},
                          "position": {"x": 380 + i * 220, "y": 200}})
            edges.append({"id": f"e_l{i}", "source": prev or "f0", "target": node_id,
                          "sourceHandle": "out", "targetHandle": "left"})
            edges.append({"id": f"e_r{i}", "source": f"f{i + 1}", "target": node_id,
                          "sourceHandle": "out", "targetHandle": "right"})
            prev = node_id
        edges.append({"id": "e_out", "source": prev, "target": "out",
                      "sourceHandle": "out", "targetHandle": "value"})
    return {"nodes": nodes, "edges": edges}


# =============================================================================
# 规范定义
# =============================================================================

#: 列类型 → 说明（生成模板的「说明」表用）
KIND_LABELS = {
    "text": "文本",
    "number": "数字（可按文本填写以保精度）",
    "bool": "是/否",
    "list": "列表（分号分隔）",
    "map": "键值（名称:数值，分号分隔）",
    "pairs": "键值（key=value，分号分隔）",
    "json": "JSON 文本",
}

#: 表头中文化：{表名: {参数名: 中文表头}}
#:
#: 表格里**推荐写中文表头**；程序同时接受英文参数名（老文件与代码口径都能用），
#: 两者指向同一列。中文表头只在**同一张表内**需要唯一，不同表可以复用（如「状态」「说明」）。
HEADERS: dict[str, dict[str, str]] = {
    "比赛": {
        "name": "比赛名称", "status": "状态", "map_background_url": "地图背景图地址",
        "map_background_width": "背景图宽", "map_background_height": "背景图高",
    },
    "财年": {"year": "年份", "status": "状态"},
    "股票参数": {"param": "参数", "value": "值"},
    "产业类型": {"code": "编码", "name": "产业名称", "description": "说明", "icon": "图标"},
    "产业字段": {
        "industry_type": "所属产业", "name": "字段名称", "field_key": "字段键",
        "field_type": "字段类型", "default_value": "默认值", "is_calculated": "是否计算字段",
        "graph": "计算图", "timer_enabled": "启用财年定时器", "timer_trigger": "定时器时机",
        "timer_value": "定时器写入值", "sort_order": "排序", "visible": "是否展示",
        "config": "类型配置",
    },
    "区域": {"name": "区域名称", "description": "说明"},
    "地图节点类型": {"name": "类型名称", "description": "说明", "color": "颜色"},
    "路径类型": {"name": "类型名称", "description": "说明", "color": "颜色"},
    "地图节点": {
        "name": "节点名称", "node_type": "节点类型", "region": "所属区域",
        "x": "X坐标", "y": "Y坐标",
    },
    "地图连线": {
        "from_node": "起点节点", "to_node": "终点节点", "distance": "距离(公里)",
        "path_type": "路径类型",
    },
    "燃料": {"name": "燃料名称", "price_per_liter": "每升单价"},
    "原料": {
        "name": "原料名称", "origin": "产地", "carbon_emission_coefficient": "碳排系数",
        "type": "类型", "node_prices": "地点价",
    },
    "科技": {
        "name": "科技名称", "tier": "层级", "research_cost": "研发费用",
        "description": "说明", "prerequisites": "前置科技",
    },
    "生产线": {
        "name": "生产线名称", "price": "单价", "labor_count": "用工人数", "max_per_year": "年产能",
    },
    "基建": {
        "name": "基建名称", "footprint": "占地面积", "price": "单价", "activation_price": "启用费用",
        "employment_rate_bonus": "就业率加成", "population_bonus": "人口加成",
        "high_quality_population_bonus": "高素质人口加成", "happiness_index_bonus": "幸福度加成",
        "per_capita_income_bonus": "人均收益加成", "carbon_reduction_bonus": "减碳加成",
    },
    "仓库": {"name": "仓库名称", "type": "仓库种类", "capacity": "容量", "price": "单价"},
    "零件": {"name": "零件名称", "materials": "原料配比", "tech": "所需科技"},
    "产品": {"name": "产品名称", "parts": "零件配比", "tech": "所需科技"},
    "载具": {
        "name": "载具名称", "fuel": "燃料", "path_types": "可通行路径类型",
        "fuel_consumption_per_km": "每公里油耗", "max_cargo": "载货量",
        "price": "单价", "carbon_emission": "碳排系数",
    },
    "消费者需求": {"region": "区域名称", "product": "产品名称", "quantity": "需求量", "note": "备注"},
    "合同类型": {"script": "脚本路径", "key": "类型标识", "enabled": "是否启用"},
}


def header_for(sheet_name: str, key: str) -> str:
    """取某表某列的**中文表头**（缺失时回退参数名）。"""
    return HEADERS.get(sheet_name, {}).get(key, key)


def header_aliases(spec: "SheetSpec") -> dict[str, str]:
    """构造「表头 → 参数名」的别名表：中文表头与英文参数名都指向同一列。"""
    alias: dict[str, str] = {}
    for col in spec.columns:
        alias[col.key] = col.key
        alias[header_for(spec.name, col.key)] = col.key
    return alias


def example_rows(spec: "SheetSpec") -> list[tuple[str, ...]]:
    """取某张表的示例行（模板与文档用）。

    `SheetSpec.example` 支持两种写法：
    - 一行：`("2026", "ACTIVE")`；
    - 多行：`(("白云鄂博矿区", …), ("上游集运站", …))` —— 需要注册两个引用对象时用
      （例如「地图节点」要给出两个节点，「地图连线」的示例才引用得到）。
    """
    ex = spec.example
    if not ex:
        return []
    if all(isinstance(item, (list, tuple)) for item in ex):
        return [tuple(item) for item in ex]
    return [tuple(ex)]


@dataclass(frozen=True)
class Column:
    key: str                       # 表头文字（= 建包库参数名）
    label: str                     # 中文说明
    kind: str = "text"             # text/number/bool/list/map/pairs/json
    required: bool = False


@dataclass
class SheetContext:
    """处理某张表时传给 handler 的上下文。"""

    builder: Any                                   # CompetitionBuilder
    base_dir: Any = None                           # 表格所在目录（解析 script 相对路径用）
    notes: list[str] = field(default_factory=list)
    row_no: int = 0

    def note(self, text: str) -> None:
        self.notes.append(text)


@dataclass(frozen=True)
class SheetSpec:
    name: str
    scope: str                     # 对应建包库分组：competition/industry/company/supply/geo/tech/market/access
    purpose: str
    columns: tuple[Column, ...]
    example: tuple[str, ...] = ()
    handler: Callable[[SheetContext, dict], None] | None = None
    allow_extra_columns: bool = False   # 额外列是否当「产业字段值」处理（公司表用）


# ------------------------------ 各表 handler ------------------------------


def _h_fiscal_year(ctx: SheetContext, row: dict) -> None:
    year = row.get("year")
    if not year:
        raise SheetFormatError("财年表的 year 必填")
    ctx.builder.fiscal_year(int(float(year)), status=(row.get("status") or "ACTIVE").upper())


def _h_industry_type(ctx: SheetContext, row: dict) -> None:
    code = row.get("code")
    name = row.get("name")
    if not code or not name:
        raise SheetFormatError("产业类型表的 code 与 name 必填")
    ctx.builder.industry_type(int(float(code)), name,
                              description=row.get("description") or None,
                              icon=row.get("icon") or None)


def _h_industry_field(ctx: SheetContext, row: dict) -> None:
    b = ctx.builder
    industry = row.get("industry_type")
    name, key = row.get("name"), row.get("field_key")
    if not industry or not name or not key:
        raise SheetFormatError("产业字段表的 industry_type / name / field_key 必填")
    is_calc = bool(as_bool(row.get("is_calculated"), default=False))
    graph_text = (row.get("graph") or "").strip()
    graph = None
    if graph_text:
        if is_json_cell(graph_text):
            graph = json.loads(graph_text)
        else:
            graph = field_sum_graph(graph_text)
    timer_enabled = bool(as_bool(row.get("timer_enabled"), default=False))
    kwargs: dict[str, Any] = {
        "field_type": (row.get("field_type") or "NUMBER").upper(),
        "default_value": row.get("default_value") or None,
        "is_calculated": is_calc,
        "graph": graph,
        "sort_order": int(float(row["sort_order"])) if row.get("sort_order") else 0,
        "visible": bool(as_bool(row.get("visible"), default=True)),
        "timer_enabled": timer_enabled,
        "timer_trigger": (row.get("timer_trigger") or None),
        "timer_value": row.get("timer_value") or None,
    }
    config_text = (row.get("config") or "").strip()
    if config_text:
        kwargs["config"] = json.loads(config_text) if is_json_cell(config_text) else {"valueType": config_text}
    b.add_field(_industry_ref(ctx, industry), name, key, **kwargs)


def _h_region(ctx: SheetContext, row: dict) -> None:
    name = row.get("name")
    if not name:
        raise SheetFormatError("区域表的 name 必填")
    ctx.builder.region(name, description=row.get("description") or None)


def _h_node_type(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("地图节点类型表的 name 必填")
    ctx.builder.node_type(row["name"], description=row.get("description") or None,
                          color=row.get("color") or None)


def _h_path_type(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("路径类型表的 name 必填")
    ctx.builder.path_type(row["name"], description=row.get("description") or None,
                          color=row.get("color") or None)


def _h_node(ctx: SheetContext, row: dict) -> None:
    name, node_type = row.get("name"), row.get("node_type")
    if not name or not node_type:
        raise SheetFormatError("地图节点表的 name 与 node_type 必填")
    ctx.builder.node(name, node_type, region=row.get("region") or "",
                     x=_as_scalar(row["x"]) if row.get("x") else 0,
                     y=_as_scalar(row["y"]) if row.get("y") else 0)


def _h_edge(ctx: SheetContext, row: dict) -> None:
    src, dst = row.get("from_node"), row.get("to_node")
    if not src or not dst:
        raise SheetFormatError("地图连线表的 from_node 与 to_node 必填")
    distance = row.get("distance")
    if not distance:
        raise SheetFormatError("地图连线表的 distance 必填")
    path_type = row.get("path_type")
    if not path_type:
        raise SheetFormatError("地图连线表的 path_type 必填（载具按它判断能否通行）")
    ctx.builder.edge(src, dst, _as_scalar(distance), path_type)


def _h_fuel(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("燃料表的 name 必填")
    ctx.builder.fuel(row["name"], price_per_liter=row.get("price_per_liter") or 0)


def _h_material(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("原料表的 name 必填")
    ctx.builder.material(
        row["name"],
        origin=row.get("origin") or "",
        carbon_emission_coefficient=_as_scalar(row["carbon_emission_coefficient"])
        if row.get("carbon_emission_coefficient") else 0,
        type=(row.get("type") or "NORMAL").upper(),
        # 地点价按原文写入（保精度，与代码建包 price="180" 一致）
        node_prices=as_map(row.get("node_prices"), keep_text=True) or None,
    )


def _h_tech(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("科技表的 name 必填")
    ctx.builder.tech(
        row["name"],
        tier=int(float(row["tier"])) if row.get("tier") else 0,
        research_cost=row.get("research_cost") or 0,
        description=row.get("description") or None,
        prerequisites=as_items(row.get("prerequisites")) or None,
    )


def _h_line(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("生产线表的 name 必填")
    ctx.builder.line(row["name"], price=row.get("price") or 0,
                     labor_count=int(float(row["labor_count"])) if row.get("labor_count") else 0,
                     max_per_year=row.get("max_per_year") or 0)


def _h_infrastructure(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("基建表的 name 必填")
    text_cols = ("price", "activation_price")            # 金额：保留原文以保精度
    num_cols = ("footprint", "employment_rate_bonus", "population_bonus",
                "high_quality_population_bonus", "happiness_index_bonus",
                "per_capita_income_bonus", "carbon_reduction_bonus")
    kwargs = {k: (row[k] if row.get(k) else 0) for k in text_cols}
    kwargs.update({k: (_as_scalar(row[k]) if row.get(k) else 0) for k in num_cols})
    ctx.builder.infrastructure(row["name"], **kwargs)


def _h_warehouse(ctx: SheetContext, row: dict) -> None:
    name, wtype = row.get("name"), row.get("type")
    if not name or not wtype:
        raise SheetFormatError("仓库表的 name 与 type 必填")
    ctx.builder.warehouse(name, wtype.upper(), capacity=row.get("capacity") or 0,
                          price=row.get("price") or 0)


def _h_part(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("零件表的 name 必填")
    ctx.builder.part(row["name"], materials=as_map(row.get("materials")) or None,
                     tech=as_items(row.get("tech")) or None)


def _h_product(ctx: SheetContext, row: dict) -> None:
    if not row.get("name"):
        raise SheetFormatError("产品表的 name 必填")
    ctx.builder.product(row["name"], parts=as_map(row.get("parts")) or None,
                        tech=as_items(row.get("tech")) or None)


def _h_vehicle(ctx: SheetContext, row: dict) -> None:
    name, fuel = row.get("name"), row.get("fuel")
    if not name or not fuel:
        raise SheetFormatError("载具表的 name 与 fuel 必填（载具必须绑定燃料）")
    ctx.builder.vehicle(
        name,
        fuel=fuel,
        path_types=as_items(row.get("path_types")) or None,
        fuel_consumption_per_km=_as_scalar(row["fuel_consumption_per_km"])
        if row.get("fuel_consumption_per_km") else 0,
        max_cargo=_as_scalar(row["max_cargo"]) if row.get("max_cargo") else 0,
        price=row.get("price") or 0,                      # 金额：保留原文
        carbon_emission=_as_scalar(row["carbon_emission"]) if row.get("carbon_emission") else 0,
    )


def _h_demand(ctx: SheetContext, row: dict) -> None:
    region, product, quantity = row.get("region"), row.get("product"), row.get("quantity")
    if not region or not product or not quantity:
        raise SheetFormatError("消费者需求表的 region / product / quantity 必填")
    ctx.builder.demand(region, product, int(float(quantity)), note=row.get("note") or None)


def _h_contract_type(ctx: SheetContext, row: dict) -> None:
    """合同类型**只由代码脚本创建**（「合同类型代码化」建库，见 docs/CONTRACT_TYPE_BY_CODE.md）。

    表格这一行只做两件事：指向脚本、挑选要引入的类型 —— 参与方 / 输入项 / 效果 / 前置检查
    这四份 JSON 全部由脚本里的 `apps.contracts.builder.ContractType` 产出，
    表格里不再手写（手写 JSON 极易写错，且引擎对写错的形状会**静默按 0 计算**）。

    - `脚本路径`：必填；相对 backend 目录或表格所在目录都可以；
    - `类型标识`：留空 = 引入该脚本产出的**全部**合同类型；填了 = 只引入这一个；
    - `是否启用`：对应合同类型的 enabled 开关。
    """
    script = (row.get("script") or "").strip()
    if not script:
        raise SheetFormatError(
            "合同类型表的「脚本路径」必填：合同类型必须由代码脚本产出"
            "（写法见 docs/CONTRACT_TYPE_BY_CODE.md 与 backend/examples/contracts/）"
        )
    wanted = (row.get("key") or "").strip()
    enabled = bool(as_bool(row.get("enabled"), default=True))

    types = _contract_types_from_script(ctx, script)
    matched = [ct for ct in types if not wanted or ct.key == wanted]
    if not matched:
        available = "、".join(ct.key for ct in types) or "（脚本没有产出任何合同类型）"
        raise SheetFormatError(f"脚本 {script} 里没有合同类型「{wanted}」；该脚本产出：{available}")

    for ct in matched:
        payload = ct.payload()
        key = payload["key"]
        # 安全网：脚本若用 keep_effects() 保留了老格式 JSON，这里照样归一并提示
        legacy = [0]
        legacy_cond = [0]
        effects = normalize_value_specs(payload.get("effects") or [], count=legacy)
        conditions = normalize_conditions(normalize_value_specs(payload.get("conditions") or [],
                                                              count=legacy), count=legacy_cond)
        if legacy[0]:
            ctx.note(f"合同类型 {key}：把 {legacy[0]} 处老写法 {{\"from\": \"input\"}} 归一成了引擎值源"
                     f" {{\"type\": \"INPUT\"}}（不归一的话引擎会静默按 0 计算）")
        if legacy_cond[0]:
            ctx.note(f"合同类型 {key}：把 {legacy_cond[0]} 处检查的老写法 kind=\"FIELD\" 归一成了"
                     f" \"FIELD_COMPARE\"（引擎没有 FIELD 这个检查种类，检查会恒不通过）")
        ctx.builder.contract_type(
            key,
            payload["name"],
            description=payload.get("description"),
            party_roles=payload.get("partyRoles") or [],
            input_schema=payload.get("inputSchema") or [],
            effects=effects,
            conditions=conditions,
            enabled=enabled,
        )
        ctx.note(f"合同类型 {key}（{payload['name']}）来自脚本 {Path(script).name}")


def _h_stock_config(ctx: SheetContext, row: dict) -> None:
    """股票参数表：**键值两列**，每行一个参数；本表只描述市场规则，不涉及任何公司/人/主键。

    - 参数名必须是 `apps.stock.engine.DEFAULT_STOCK_CONFIG` 里的键（写错会报错并给出最相近的名字）；
    - 值按该键的默认值类型解析：布尔用 `是/否`，其余为数值（`interventionMode` 为 `regression` / `expand-limit`）；
    - 整表为空 / 没有这张表 = 不产出 `stockConfig`，目标比赛沿用系统默认（个股与资金账户也不在表格内）；
    - 每行都会并进同一份配置，最终由建包库 `stock_config_set()` 产出归档里的 `stockConfig`。
    """
    from apps.stock.engine import DEFAULT_STOCK_CONFIG

    param = str(row.get("param") or "").strip()
    raw_value = str(row.get("value") or "").strip()
    if not param:
        raise SheetFormatError("股票参数表的「参数」必填（键名见规范，如 limitPct / mmMinQty）")
    if param not in DEFAULT_STOCK_CONFIG:
        import difflib

        near = difflib.get_close_matches(param, list(DEFAULT_STOCK_CONFIG), n=3, cutoff=0.4)
        hint = f"；是不是想写：{'、'.join(near)}？" if near else ""
        raise SheetFormatError(
            f"未知的股票参数「{param}」{hint}"
            f"（可用参数：{'、'.join(DEFAULT_STOCK_CONFIG)}）"
        )
    if raw_value == "":
        raise SheetFormatError(
            f"股票参数「{param}」的值不能为空；想沿用系统默认就不要写这一行"
            f"（系统默认 = {DEFAULT_STOCK_CONFIG[param]!r}）"
        )

    value = _stock_config_value(param, raw_value, DEFAULT_STOCK_CONFIG[param])

    # 逐行并入：与已登记的配置合并后再交给建包库（stock_config_set 是整份替换语义）
    merged = dict(getattr(ctx.builder, "stock_config", None) or {})
    merged[param] = value
    _assert_stock_config_sane(merged, ctx)
    ctx.builder.stock_config_set(merged)


def _stock_config_value(param: str, raw: str, default: Any) -> Any:
    """按默认值的类型解析单元格：布尔 / 枚举 / 数值（整数位保留 int，便于与默认值同形）。"""
    if isinstance(default, bool):
        parsed = as_bool(raw)
        if parsed is None:
            raise SheetFormatError(f"股票参数「{param}」是开关，请填 是/否（默认 {default}）")
        return bool(parsed)
    if isinstance(default, str):
        text = raw.strip()
        allowed = ("regression", "expand-limit")
        if text not in allowed:
            raise SheetFormatError(
                f"股票参数「{param}」只接受 {' / '.join(allowed)}，收到「{text}」"
            )
        return text
    number = _as_scalar(raw)
    if isinstance(number, str):        # 不是数字
        raise SheetFormatError(f"股票参数「{param}」需要数字，收到「{raw}」")
    if number < 0:
        raise SheetFormatError(f"股票参数「{param}」不能为负（收到 {number}）")
    if isinstance(default, int) and float(number).is_integer():
        return int(number)
    return float(number)


def _assert_stock_config_sane(config: dict, ctx: SheetContext) -> None:
    """建包库只校验「非空字典」，这里补上引擎口径的两条硬约束与一条风险提示。"""
    limit, move = config.get("limitPct"), config.get("maxMovePct")
    if limit is not None and move is not None and float(limit) < float(move):
        raise SheetFormatError(
            f"limitPct（单轮限幅 {limit}）不能小于 maxMovePct（单轮最大波动 {move}）"
        )
    low, high = config.get("mmMinQty"), config.get("mmMaxQty")
    if low is not None and high is not None and float(low) > float(high):
        raise SheetFormatError(f"mmMinQty（做市商最小数量 {low}）不能大于 mmMaxQty（{high}）")
    if limit is not None and float(limit) > 0.1:
        ctx.note(f"股票参数：limitPct={limit} 已高于 10%，玩家更容易把价格拉到涨停"
                 f"（引擎的防连板机制仍会兜底，但建议不超过 0.10）")


def _contract_types_from_script(ctx: SheetContext, script: str) -> list:
    """执行「合同类型代码化」脚本，取回它产出的 ContractType 列表。"""
    import importlib.util

    path = Path(script)
    if not path.is_absolute() and ctx.base_dir is not None:
        candidate = Path(ctx.base_dir) / script
        path = candidate if candidate.exists() else path
    if not path.exists():
        raise SheetFormatError(f"合同类型脚本不存在：{path}")
    spec = importlib.util.spec_from_file_location(f"_sheet_ct_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SheetFormatError(f"无法加载合同类型脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - 脚本自身的错误直接暴露给使用者
        raise SheetFormatError(f"合同类型脚本 {path.name} 执行失败：{type(exc).__name__}: {exc}") from None
    build_fn = getattr(module, "build", None)
    produced = build_fn() if callable(build_fn) else getattr(module, "CONTRACTS", None)
    if produced is None:
        raise SheetFormatError(
            f"合同类型脚本 {path.name} 没有产出：请定义 build() 返回 ContractType / 列表 / 字典，"
            "或模块级 CONTRACTS"
        )
    items = produced if isinstance(produced, (list, tuple)) else list(produced.values()) \
        if isinstance(produced, dict) else [produced]
    types = [item for item in items if item is not None]
    if not types:
        raise SheetFormatError(f"合同类型脚本 {path.name} 没有产出任何合同类型")
    return types


# ------------------------------ 表清单 ------------------------------


SHEETS: tuple[SheetSpec, ...] = (
    SheetSpec(
        "比赛", "competition", "比赛本身：名称、状态、地图背景图（整表一行）",
        (
            Column("name", "比赛名称（全局唯一）", required=True),
            Column("status", "ACTIVE / CLOSED"),
            Column("map_background_url", "地图背景图地址"),
            Column("map_background_width", "背景图宽", "number"),
            Column("map_background_height", "背景图高", "number"),
        ),
        ("2026 汽车产业链测试赛", "ACTIVE", "", "", ""),
        None,   # 比赛表由驱动层在建包前特殊处理（它决定构建器的构造参数）
    ),
    SheetSpec(
        "财年", "competition", "财年：新建 / 由非 ACTIVE 改为 ACTIVE 会触发 FY_START 定时器",
        (Column("year", "年份", "number", True), Column("status", "ACTIVE / CLOSED")),
        ("2026", "ACTIVE"),
        _h_fiscal_year,
    ),
    SheetSpec(
        "股票参数", "competition",
        "股票市场的**规则**（单轮限幅 / 最大波动 / 做市商 / 随机事件…）：键值两列，每行一个参数；"
        "留空表示沿用系统默认。个股与资金账户绑定公司/人/主键，不在表格内（去「股票管理」维护）",
        (
            Column("param", "参数（键名与系统默认配置一致）", required=True),
            Column("value", "值（数值 / 是·否 / regression·expand-limit）", required=True),
        ),
        ("limitPct", "0.10"),
        _h_stock_config,
    ),
    SheetSpec(
        "产业类型", "industry", "全局资源：行业口径（按 code 跨比赛复用，不要给不同行业用同一个 code）",
        (
            Column("code", "数字编码（全局唯一）", "number", True),
            Column("name", "产业名称", required=True),
            Column("description", "说明"),
            Column("icon", "图标"),
        ),
        ("2001", "原料开采", "汽车产业链上游", ""),
        _h_industry_type,
    ),
    SheetSpec(
        "产业字段", "industry", "全局资源：产业下的字段（合同、图表、股票都按 field_key 绑定）",
        (
            Column("industry_type", "所属产业（code 或名称）", required=True),
            Column("name", "字段显示名", required=True),
            Column("field_key", "字段键（英文，公式里要用）", required=True),
            Column("field_type", "STRING/NUMBER/BOOLEAN/DICTIONARY/LIST", ),
            Column("default_value", "默认值"),
            Column("is_calculated", "是否计算字段", "bool"),
            Column("graph", "计算图：`cash + bank_deposit` 或 GGraph JSON", "json"),
            Column("timer_enabled", "启用财年定时器", "bool"),
            Column("timer_trigger", "FY_START / FY_END"),
            Column("timer_value", "定时器写入值"),
            Column("sort_order", "界面排序", "number"),
            Column("visible", "是否展示", "bool"),
            Column("config", "类型配置 JSON 或 valueType"),
        ),
        ("原料开采", "现金", "cash", "NUMBER", "0", "", "", "", "", "", "2", "是", ""),
        _h_industry_field,
    ),
    SheetSpec(
        "区域", "geo", "比赛内区域（区域总览、消费者需求按它聚合）",
        (Column("name", "区域名（比赛内唯一）", required=True), Column("description", "说明")),
        ("上游资源区", "锂 / 铝 / 铁矿与橡胶硅砂资源带"),
        _h_region,
    ),
    SheetSpec(
        "地图节点类型", "geo", "地图节点分类（矿区 / 港口 / 城市 …）",
        (Column("name", "类型名", required=True), Column("description", "说明"),
         Column("color", "颜色，如 #b45309")),
        (("矿区", "原矿开采地", "#b45309"),
         ("物流枢纽", "集运站 / 港口 / 铁路货场", "#0ea5e9")),
        _h_node_type,
    ),
    SheetSpec(
        "路径类型", "geo", "道路类型（公路 / 铁路 / 航运）；载具按它判断可通行",
        (Column("name", "类型名", required=True), Column("description", "说明"), Column("color", "颜色")),
        ("公路", "通用公路运输", "#94a3b8"),
        _h_path_type,
    ),
    SheetSpec(
        "地图节点", "geo", "地图节点（region 是文本列，不是外键）",
        (
            Column("name", "节点名（比赛内唯一）", required=True),
            Column("node_type", "节点类型（名称）", required=True),
            Column("region", "所属区域名（文本）"),
            Column("x", "画布 x 坐标", "number"),
            Column("y", "画布 y 坐标", "number"),
        ),
        (("白云鄂博矿区", "矿区", "上游资源区", "140", "120"),
         ("上游集运站", "物流枢纽", "上游资源区", "360", "300")),
        _h_node,
    ),
    SheetSpec(
        "地图连线", "geo", "节点之间的连线；同一对「起点+终点」只能有一条（反向算另一条）",
        (
            Column("from_node", "起点节点", required=True),
            Column("to_node", "终点节点", required=True),
            Column("distance", "距离（公里）", "number", True),
            Column("path_type", "路径类型（名称）", required=True),
        ),
        ("白云鄂博矿区", "上游集运站", "120", "公路"),
        _h_edge,
    ),
    SheetSpec(
        "燃料", "supply", "燃料（载具必须绑定燃料，外键 PROTECT）",
        (Column("name", "燃料名", required=True), Column("price_per_liter", "每升单价", "number")),
        ("柴油", "7.6"),
        _h_fuel,
    ),
    SheetSpec(
        "原料", "supply", "原料（地点价按地图节点名写；运输与运费计算都依赖它）",
        (
            Column("name", "原料名", required=True),
            Column("origin", "产地（通常写地图节点名）"),
            Column("carbon_emission_coefficient", "碳排系数", "number"),
            Column("type", "NORMAL / SPECIAL"),
            Column("node_prices", "地点价：`白云鄂博矿区:180; 上游集运站:195`", "map"),
        ),
        ("锂矿石", "白云鄂博矿区", "0.52", "NORMAL", "白云鄂博矿区:180; 上游集运站:195"),
        _h_material,
    ),
    SheetSpec(
        "科技", "supply", "科技节点（零件 / 产品按它设前置）",
        (
            Column("name", "科技名", required=True),
            Column("tier", "层级", "number"),
            Column("research_cost", "研发费用", "number"),
            Column("description", "说明"),
            Column("prerequisites", "前置科技：`高炉冶炼;转炉炼钢`", "list"),
        ),
        ("电池成组技术", "1", "80000", "解锁动力电池包", ""),
        _h_tech,
    ),
    SheetSpec(
        "生产线", "supply", "生产线（产能与用工人数）",
        (
            Column("name", "生产线名", required=True),
            Column("price", "单价", "number"),
            Column("labor_count", "用工人数", "number"),
            Column("max_per_year", "年产能", "number"),
        ),
        ("电芯产线", "2400000", "120", "6000"),
        _h_line,
    ),
    SheetSpec(
        "基建", "supply", "基建及其 6 项加成（合同可按清单聚合这些属性）",
        (
            Column("name", "基建名", required=True),
            Column("footprint", "占地面积", "number"),
            Column("price", "单价", "number"),
            Column("activation_price", "启用费用", "number"),
            Column("employment_rate_bonus", "就业率加成", "number"),
            Column("population_bonus", "人口加成", "number"),
            Column("high_quality_population_bonus", "高素质人口加成", "number"),
            Column("happiness_index_bonus", "幸福度加成", "number"),
            Column("per_capita_income_bonus", "人均收益加成", "number"),
            Column("carbon_reduction_bonus", "减碳加成", "number"),
        ),
        ("光伏电站", "160", "1200000", "50000", "0.02", "", "", "", "", "0.12"),
        _h_infrastructure,
    ),
    SheetSpec(
        "仓库", "supply", "仓库（MATERIAL / PART / PRODUCT / FUEL 四种建议都覆盖）",
        (
            Column("name", "仓库名", required=True),
            Column("type", "MATERIAL/PART/PRODUCT/FUEL", required=True),
            Column("capacity", "容量", "number"),
            Column("price", "单价", "number"),
        ),
        ("原料仓", "MATERIAL", "30000", "400000"),
        _h_warehouse,
    ),
    SheetSpec(
        "零件", "supply", "零件：原料配比 + 科技前置（配比只能引用原料）",
        (
            Column("name", "零件名", required=True),
            Column("materials", "原料配比：`锂矿石*4; 铝土矿*1`", "map"),
            Column("tech", "所需科技：`电池成组技术`", "list"),
        ),
        ("动力电池包", "锂矿石*4", "电池成组技术"),
        _h_part,
    ),
    SheetSpec(
        "产品", "supply", "产品：零件配比 + 科技前置（配比只能引用零件）",
        (
            Column("name", "产品名", required=True),
            Column("parts", "零件配比：`动力电池包*1; 驱动电机*1`", "map"),
            Column("tech", "所需科技", "list"),
        ),
        ("纯电轿车", "动力电池包*1", "电池成组技术"),
        _h_product,
    ),
    SheetSpec(
        "载具", "supply", "载具：绑定燃料 + 可通行路径类型（缺路径类型会导致运输校验失败）",
        (
            Column("name", "载具名", required=True),
            Column("fuel", "燃料（必填）", required=True),
            Column("path_types", "可通行路径类型：`公路;铁路`", "list"),
            Column("fuel_consumption_per_km", "每公里油耗", "number"),
            Column("max_cargo", "载货量", "number"),
            Column("price", "单价", "number"),
            Column("carbon_emission", "碳排系数", "number"),
        ),
        ("重型卡车", "柴油", "公路", "0.35", "30", "260000", "0.9"),
        _h_vehicle,
    ),
    SheetSpec(
        "消费者需求", "tech", "区域消费者需求（导入按「区域+产品+数量」去重，改数量 = 新增一条）",
        (
            Column("region", "区域名（文本）", required=True),
            Column("product", "产品名（需已登记）", required=True),
            Column("quantity", "需求量", "number", True),
            Column("note", "备注"),
        ),
        ("东部车都", "纯电轿车", "1200", "城市通勤主力车型"),
        _h_demand,
    ),
    SheetSpec(
        "合同类型", "market",
        "合同类型**只由代码脚本创建**（合同类型代码化建库）：本表只写脚本路径与要引入的类型标识",
        (
            Column("script", "脚本路径（相对 backend 或表格所在目录）", required=True),
            Column("key", "类型标识：留空 = 引入该脚本的全部合同类型；填了 = 只引入这一个"),
            Column("enabled", "是否启用", "bool"),
        ),
        ("examples/contracts/auto_chain_contracts.py", "auto-mining", "是"),
        _h_contract_type,
    ),
)

SHEET_BY_NAME: dict[str, SheetSpec] = {s.name: s for s in SHEETS}

#: **不在 Excel 规范内的表**：出现了就提示原因与「该去哪里维护」，而不是静默忽略。
#:
#: 划分原则：**Excel 只负责「比赛框架」**（换一场比赛仍然成立的口径与规则）；
#: 参赛主体、账号、预置合同、卡片、消息这些**关乎实际比赛运行**的内容，
#: 由前端界面（推荐）或代码建包脚本维护 —— 它们都绑定具体公司、具体人和具体主键。
OUT_OF_SCOPE_SHEETS: dict[str, str] = {
    "公司": "参赛主体属于运行期数据：请在「公司管理」界面维护，"
            "或用代码建包脚本 examples/competitions/auto_chain_competition.py",
    "公司字段值": "公司字段值是参赛主体的初始数据：请在「公司管理 → 公司详情」里维护",
    "账号": "账号与权限属于运行期数据（且涉及口令安全）：请用「账号管理」界面创建与重置密码",
    "区域总览卡片": "卡片绑定具体公司与产业字段主键：请在「区域总览」界面配置",
    "合同实例": "比赛内的预置合同要绑定具体公司：请在「合同管理」界面创建",
    "消息": "消息是开赛后发布的运行内容：请在「消息中心」发布",
    "股票": "个股绑定具体公司（PE 联动公司/字段、碳排·幸福度绑定卡片主键）：请在「股票管理」维护",
    "资金账户": "资金账户绑定具体公司或用户（含绑定的产业字段主键）：请在「股票管理」维护",
    "持仓": "持仓由撮合引擎在运行时生成，无法预置",
    "委托": "委托由玩家在「股票行情」下单产生，无法预置",
    "K线": "K 线由「推进轮次」在运行时生成，无法预置",
}

#: 说明表（自由文本，解析时忽略）
NOTES_SHEET_NAMES = {"说明", "README", "readme", "Readme"}


def summarize_spec() -> str:
    """把规范渲染成 Markdown（写文档 / 打印用）。

    表头一栏给出**中文表头**（表格里推荐写的），括号里是内部参数名（也接受，便于与代码对照）。
    """
    lines = ["# 比赛建包表格规范", ""]
    for spec in SHEETS:
        lines.append(f"## {spec.name}（分组：{spec.scope}）")
        lines.append("")
        lines.append(spec.purpose)
        lines.append("")
        lines.append("| 表头 | 参数名 | 说明 | 类型 | 必填 |")
        lines.append("| --- | --- | --- | --- | :---: |")
        for col in spec.columns:
            lines.append(
                f"| {header_for(spec.name, col.key)} | `{col.key}` | {col.label} | "
                f"{KIND_LABELS.get(col.kind, col.kind)} | {'是' if col.required else ''} |"
            )
        if spec.allow_extra_columns:
            lines.append(
                "| （额外列，可自定义） | — | 列名写**字段键或字段显示名**，作为该公司字段初始值 | 文本 | |"
            )
        rows = example_rows(spec)
        if rows:
            lines.append("")
            for row in rows:
                lines.append("示例行：" + " | ".join(str(x) for x in row))
        lines.append("")
    return "\n".join(lines)
