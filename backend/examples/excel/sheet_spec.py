# -*- coding: utf-8 -*-
"""比赛建包表格规范（Excel / CSV）：**一张工作表 = 一类内容**，表与表之间相互隔离。

设计原则
--------

1. **一表一资源**：每张工作表只描述一类对象（产业类型 / 公司 / 原料 / 合同类型 …），
   想建什么就放哪张表，不放的表完全不参与产出 —— 这就是「不同表实现不同内容隔离」。
2. **没有新的落库路径**：本规范只是把表格翻译成 `CompetitionBuilder` 的调用，
   最终仍由既有的 `archive.apply_import` 落库，与代码建包、前端导入完全同构。
3. **表头即参数名**：第一行是表头，列名与建包库的方法参数同名（`name` / `industry_type` /
   `region` / `field_key` …），因此 `build_competition --schema` 与本文档可以直接对照。
4. **单元格语法尽量贴近 Excel 习惯**：
   - 空单元格 = 不传该参数（用建包库默认值）；
   - 布尔：`是/否`、`TRUE/FALSE`、`1/0`、`y/n`；
   - 列表：`公路;铁路`（分号、顿号、逗号、换行都可以当分隔符）；
   - 配比 / 地点价 / 键值：`锂矿石*4; 铝土矿*1` 或 `白云鄂博矿区:180; 上游集运站:195`；
   - 以 `{` 或 `[` 开头的单元格按 **JSON** 解析（复杂结构直接用 JSON）；
   - 以 `#` 开头的行是注释，整行忽略。

工作表清单（按依赖顺序处理，worksheet 在文件里的先后不影响结果）
----------------------------------------------------------------

    比赛 → 财年
    产业类型 → 产业字段
    区域 → 公司 → 公司字段值
    地图节点类型 → 路径类型 → 地图节点 → 地图连线
    燃料 → 原料 → 科技 → 生产线 → 基建 → 仓库 → 零件 → 产品 → 载具
    消费者需求
    区域总览卡片 → 合同类型 → 合同实例 → 消息
    账号

**股票系统不在本规范内**（按要求不动）：没有股票 / 资金账户 / 股票参数三类表；
留空即不产出，目标比赛沿用系统默认配置。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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


def _h_company(ctx: SheetContext, row: dict) -> None:
    b = ctx.builder
    name = row.get("name")
    industry = row.get("industry_type")
    if not name or not industry:
        raise SheetFormatError("公司表的 name 与 industry_type 必填")
    known = {"name", "industry_type", "region", "status"}
    extra = {k: v for k, v in row.items() if k not in known and str(v).strip() != ""}
    kwargs: dict[str, Any] = {
        "industry_type": _industry_ref(ctx, industry),
        "region": row.get("region") or None,
        "status": (row.get("status") or "ACTIVE").upper(),
    }
    if extra:  # 额外列 = 该公司的产业字段初始值（列名就是 field_key）
        kwargs["field_values"] = {k: str(v) for k, v in extra.items()}
    b.company(name, **kwargs)


def _h_company_field_value(ctx: SheetContext, row: dict) -> None:
    company, key = row.get("company"), row.get("field_key")
    if not company or not key:
        raise SheetFormatError("公司字段值表的 company 与 field_key 必填")
    ctx.builder.add_field_value(company, key, row.get("value", ""))


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


def _h_card(ctx: SheetContext, row: dict) -> None:
    region, company, key = row.get("region"), row.get("company"), row.get("field_key")
    if not region or not company or not key:
        raise SheetFormatError("区域总览卡片表的 region / company / field_key 必填")
    ctx.builder.card(region, company, key, display_name=row.get("display_name") or None,
                     zone=row.get("zone") or None, card_id=row.get("card_id") or None)


def _h_contract_type(ctx: SheetContext, row: dict) -> None:
    b = ctx.builder
    key, name = row.get("key"), row.get("name")
    script = (row.get("script") or "").strip()
    payload: dict[str, Any] = {}
    if script:
        payload = _contract_payload_from_script(ctx, script, key)
        key = key or payload.get("key")
        name = name or payload.get("name")
    if not key or not name:
        raise SheetFormatError("合同类型表的 key 与 name 必填（用 script 列时可留空，由脚本提供）")
    party_roles = payload.get("partyRoles")
    if party_roles is None:
        text = (row.get("party_roles") or "").strip()
        party_roles = as_map(text) if text and not is_json_cell(text) else (json.loads(text) if text else [])
        if isinstance(party_roles, dict):  # `seller=卖方; bank=银行|host` 紧凑写法
            party_roles = [
                {
                    "role": role,
                    "label": str(value).split("|")[0].strip() or role,
                    **({"isHost": True}
                       if "|" in str(value) and str(value).split("|", 1)[1].strip().lower()
                       in ("host", "主办", "主办方", "h") else {}),
                }
                for role, value in party_roles.items()
            ]
    input_schema = payload.get("inputSchema")
    if input_schema is None:
        text = (row.get("input_schema") or "").strip()
        input_schema = json.loads(text) if text else []
    effects = payload.get("effects")
    if effects is None:
        text = (row.get("effects") or "").strip()
        effects = json.loads(text) if text else []
    conditions = payload.get("conditions")
    if conditions is None:
        text = (row.get("conditions") or "").strip()
        conditions = json.loads(text) if text else []
    enabled = as_bool(row.get("enabled"), default=True)
    b.contract_type(key, name, description=row.get("description") or payload.get("description"),
                    party_roles=party_roles, input_schema=input_schema,
                    effects=effects, conditions=conditions, enabled=bool(enabled))


def _contract_payload_from_script(ctx: SheetContext, script: str, key: str | None) -> dict:
    """用「合同类型代码化」脚本产出四份 JSON（Excel 里只写脚本路径，逻辑仍留在代码里）。"""
    import importlib.util
    from pathlib import Path

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
    spec.loader.exec_module(module)
    build_fn = getattr(module, "build", None)
    produced = build_fn() if callable(build_fn) else getattr(module, "CONTRACTS", None)
    items = produced if isinstance(produced, (list, tuple)) else [produced]
    for item in items:
        if item is None:
            continue
        if key and getattr(item, "key", None) != key:
            continue
        ctx.note(f"合同类型 {getattr(item, 'key', '?')} 来自脚本 {path.name}")
        return item.payload()
    raise SheetFormatError(f"脚本 {path.name} 里找不到合同类型 key={key}")


def _h_contract_instance(ctx: SheetContext, row: dict) -> None:
    b = ctx.builder
    ct_key = row.get("contract_type")
    if not ct_key:
        raise SheetFormatError("合同实例表的 contract_type 必填（写合同类型的 key）")
    parties_text = (row.get("parties") or "").strip()
    parties: list[dict] = []
    if parties_text:
        parsed = json.loads(parties_text) if is_json_cell(parties_text) else as_map(parties_text)
        if isinstance(parsed, list):
            parties = parsed
        else:  # `miner=西岭锂业|MIN-2026-001; buyer=中原创能|BY-001`
            for role, value in parsed.items():
                parts = [p.strip() for p in str(value).split("|")]
                entry = {"role": role, "company": parts[0]}
                if len(parts) > 1 and parts[1]:
                    entry["contractNumber"] = parts[1]
                parties.append(entry)
    b.contract(row.get("name") or None, contract_type=ct_key, parties=parties,
               inputs=as_pairs(row.get("inputs")), status=(row.get("status") or "DRAFT").upper())


def _h_user(ctx: SheetContext, row: dict) -> None:
    username = row.get("username")
    if not username:
        raise SheetFormatError("账号表的 username 必填")
    ctx.builder.user(
        username,
        role=(row.get("role") or "PLAYER").upper(),
        display_name=row.get("display_name") or None,
        company_scopes=as_items(row.get("company_scopes")) or None,
        view_company_scopes=as_items(row.get("view_company_scopes")) or None,
        contract_view_company_scopes=as_items(row.get("contract_view_company_scopes")) or None,
        stock_company_scopes=as_items(row.get("stock_company_scopes")) or None,
        permissions=as_items(row.get("permissions")) or None,
        is_active=bool(as_bool(row.get("is_active"), default=True)),
    )


def _h_message(ctx: SheetContext, row: dict) -> None:
    title = row.get("title")
    if not title:
        raise SheetFormatError("消息表的 title 必填")
    to_all = as_bool(row.get("to_all"), default=True)
    # 单元格里写不出的换行用字面量 \n 代替（Excel 单元格内换行会带上引号，统一在这里还原）
    content = str(row.get("content") or "").replace("\\n", "\n")
    ctx.builder.message(title, content, to_all=bool(to_all),
                        to_users=as_items(row.get("to_users")) or None,
                        sender=row.get("sender") or None)


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
        "区域", "company", "比赛内区域（区域总览、总览卡片按它聚合）",
        (Column("name", "区域名（比赛内唯一）", required=True), Column("description", "说明")),
        ("上游资源区", "锂 / 铝 / 铁矿与橡胶硅砂资源带"),
        _h_region,
    ),
    SheetSpec(
        "公司", "company",
        "参赛公司；**额外列会被当作该公司的产业字段初始值**（列名 = field_key）",
        (
            Column("name", "公司名（比赛内唯一）", required=True),
            Column("industry_type", "所属产业（code 或名称）", required=True),
            Column("region", "所属区域（不存在会按名自动建）"),
            Column("status", "ACTIVE / INACTIVE"),
        ),
        ("西岭锂业", "原料开采", "上游资源区", "ACTIVE", "白云鄂博矿区", "1200000"),
        _h_company,
        allow_extra_columns=True,
    ),
    SheetSpec(
        "公司字段值", "company", "单独维护公司字段值（与公司表二选一或并用，后写覆盖先写）",
        (
            Column("company", "公司名", required=True),
            Column("field_key", "产业字段键", required=True),
            Column("value", "值（NUMBER 建议写字符串以保精度）"),
        ),
        ("西岭锂业", "bank_deposit", "300000"),
        _h_company_field_value,
    ),
    SheetSpec(
        "地图节点类型", "geo", "地图节点分类（矿区 / 港口 / 城市 …）",
        (Column("name", "类型名", required=True), Column("description", "说明"),
         Column("color", "颜色，如 #b45309")),
        ("矿区", "原矿开采地", "#b45309"),
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
        ("白云鄂博矿区", "矿区", "上游资源区", "140", "120"),
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
        ("动力电池包", "锂矿石*4; 铝土矿*1", "电池成组技术"),
        _h_part,
    ),
    SheetSpec(
        "产品", "supply", "产品：零件配比 + 科技前置（配比只能引用零件）",
        (
            Column("name", "产品名", required=True),
            Column("parts", "零件配比：`动力电池包*1; 驱动电机*1`", "map"),
            Column("tech", "所需科技", "list"),
        ),
        ("纯电轿车", "动力电池包*1; 驱动电机*1", "整车平台化"),
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
        "区域总览卡片", "market", "区域总览卡片（industryFieldId 由建包库自动回填，见文档两遍导入）",
        (
            Column("region", "区域名", required=True),
            Column("company", "公司名", required=True),
            Column("field_key", "要展示的产业字段键", required=True),
            Column("display_name", "卡片标题"),
            Column("zone", "分区标记"),
            Column("card_id", "卡片 id（缺省自动生成）"),
        ),
        ("上游资源区", "西岭锂业", "cash", "西岭锂业现金", "", ""),
        _h_card,
    ),
    SheetSpec(
        "合同类型", "market",
        "全局资源：合同模板。四份 JSON 可写 JSON，也可用 `script` 列指向合同类型代码化脚本",
        (
            Column("key", "合同类型 key（全局唯一）", required=True),
            Column("name", "合同类型名", required=True),
            Column("description", "说明"),
            Column("script", "合同类型脚本路径（如 examples/contracts/auto_chain_contracts.py）"),
            Column("party_roles", "参与方：`seller=卖方; bank=银行|host` 或 JSON", "json"),
            Column("input_schema", "输入项 JSON", "json"),
            Column("effects", "效果 JSON", "json"),
            Column("conditions", "前置检查 JSON", "json"),
            Column("enabled", "是否启用", "bool"),
        ),
        ("auto-mining", "开采合同", "开采企业缴纳权利金并入库原矿",
         "examples/contracts/auto_chain_contracts.py", "", "", "", "", "是"),
        _h_contract_type,
    ),
    SheetSpec(
        "合同实例", "market",
        "比赛内的预置合同（保持 DRAFT 不落账）。名称缺省取合同类型名，故每种类型只预置一份",
        (
            Column("contract_type", "合同类型 key", required=True),
            Column("name", "合同名（缺省 = 合同类型名）"),
            Column("parties", "参与方：`miner=西岭锂业|MIN-001; buyer=中原创能|BY-001`", "map"),
            Column("inputs", "输入项：`quantity=20; goods={\"锂矿石\": 20}`", "pairs"),
            Column("status", "DRAFT / PENDING_EXEC / EXECUTED / TERMINATED"),
        ),
        ("auto-mining", "开采合同", "miner=西岭锂业|MIN-2026-001",
         "ore_type=锂矿石; quantity=20; royalty_rate=60", "DRAFT"),
        _h_contract_instance,
    ),
    SheetSpec(
        "消息", "market", "比赛内消息（导入不做判重：重复导入会多建，注意去重）",
        (
            Column("title", "标题", required=True),
            Column("content", "正文（可用 \\n 换行）"),
            Column("to_all", "是否发给全体", "bool"),
            Column("to_users", "指定收件人：`player_a;player_b`", "list"),
            Column("sender", "发布者用户名（缺省用导入操作者）"),
        ),
        ("开局公告", "欢迎参赛，请先核对本公司初始字段。", "是", "", ""),
        _h_message,
    ),
    SheetSpec(
        "账号", "access", "参赛账号与四套公司范围（范围为空 = 登录后什么都看不到）",
        (
            Column("username", "用户名（全局唯一）", required=True),
            Column("role", "SUPER_ADMIN / COMPETITION_ADMIN / PLAYER"),
            Column("display_name", "显示名"),
            Column("company_scopes", "公司管理范围：`西岭锂业;中原创能`", "list"),
            Column("view_company_scopes", "查看范围", "list"),
            Column("contract_view_company_scopes", "合同查看范围", "list"),
            Column("stock_company_scopes", "股票范围（本规范不覆盖股票，可留空）", "list"),
            Column("permissions", "细粒度权限键：`contract:manage;contract:audit`", "list"),
            Column("is_active", "是否启用", "bool"),
        ),
        ("player_a", "PLAYER", "玩家A", "西岭锂业;中原创能", "西岭锂业;中原创能",
         "西岭锂业;中原创能", "", "", "是"),
        _h_user,
    ),
)

SHEET_BY_NAME: dict[str, SheetSpec] = {s.name: s for s in SHEETS}

#: 本规范明确不覆盖的表（出现了就提示原因，而不是静默忽略）
UNSUPPORTED_SHEETS = {
    "股票": "本规范按要求不覆盖股票系统（请用代码建包或前端维护）",
    "资金账户": "本规范按要求不覆盖股票系统（请用代码建包或前端维护）",
    "股票参数": "本规范按要求不覆盖股票系统（请用代码建包或前端维护）",
}

#: 说明表（自由文本，解析时忽略）
NOTES_SHEET_NAMES = {"说明", "README", "readme", "Readme"}


def summarize_spec() -> str:
    """把规范渲染成 Markdown（写文档 / 打印用）。"""
    lines = ["# 比赛建包表格规范", ""]
    for spec in SHEETS:
        lines.append(f"## {spec.name}（分组：{spec.scope}）")
        lines.append("")
        lines.append(spec.purpose)
        lines.append("")
        lines.append("| 列 | 说明 | 类型 | 必填 |")
        lines.append("| --- | --- | --- | :---: |")
        for col in spec.columns:
            lines.append(
                f"| `{col.key}` | {col.label} | {KIND_LABELS.get(col.kind, col.kind)} | "
                f"{'是' if col.required else ''} |"
            )
        if spec.allow_extra_columns:
            lines.append("| （额外列） | 列名视作 `field_key`，作为该公司字段初始值 | 文本 | |")
        if spec.example:
            lines.append("")
            lines.append("示例行：" + " | ".join(str(x) for x in spec.example))
        lines.append("")
    return "\n".join(lines)
