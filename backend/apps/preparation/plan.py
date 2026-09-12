"""比赛准备数据收集与开赛前体检。

对外入口：
- collect(competition_id) -> dict   统计 + 体检 + 明细（供前端展示）
- render_markdown(plan)   -> str    人类可读的归档报告（导出 Markdown）
- render_json(plan)       -> str    机器可读快照（导出 JSON）

设计要点：
- 只读，不写任何业务表；不触发广播、不落审计（本模块不注册 MODEL_TO_RESOURCE）。
- 明细条数上限 _DETAIL_LIMIT，避免大比赛导出体积失控；超出部分以「…还有 N 条」提示。
- 所有体检均为「提醒」级别：只提示风险，不阻止任何操作。
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Callable

from django.db.models import Count, Q

from apps.companies.models import Company, CompanyFieldValue
from apps.company_fields.timer import TIMER_REF_PREFIX
from apps.consumer_demands.models import ConsumerDemand
from apps.contracts.models import Contract, ContractType
from .checklist import ALL_ITEMS, CATEGORIES, PrepItem

# 明细行上限（超出只记录条数，避免导出过大）
_DETAIL_LIMIT = 200
# 体积较大的模板字段不重复内联到导出里
_MAX_MARKDOWN_CELL = 160

STATUS_EMPTY = "empty"
STATUS_READY = "ready"
STATUS_WARNING = "warning"

STATUS_LABEL = {
    STATUS_EMPTY: "待准备",
    STATUS_READY: "就绪",
    STATUS_WARNING: "提醒",
}


# ==================== 小工具 ====================

def _text(value: Any) -> str:
    """任意值 → 单元格文本（Markdown 表格安全：去换行、转义竖线、限长）。"""
    if value is None:
        s = ""
    elif isinstance(value, bool):
        s = "是" if value else "否"
    elif isinstance(value, (dict, list)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = str(value)
    s = s.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    if len(s) > _MAX_MARKDOWN_CELL:
        s = s[: _MAX_MARKDOWN_CELL - 1] + "…"
    return s


def _cell(value: Any) -> str:
    """Markdown 表格单元格：空值显示为 —。"""
    s = _text(value)
    return s if s else "—"


def _fmt_dt(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _json_obj(raw: Any) -> Any:
    """JSON 文本 → 对象；解析失败返回 None。"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _json_list(raw: Any) -> list:
    v = _json_obj(raw)
    return v if isinstance(v, list) else []


def _json_dict(raw: Any) -> dict:
    v = _json_obj(raw)
    return v if isinstance(v, dict) else {}


def _short_names(names: list[str], limit: int = 6) -> str:
    """列表 → 「A、B、C 等 N 项」形式的简短说明。"""
    uniq = [n for n in dict.fromkeys(names) if n]
    if not uniq:
        return ""
    if len(uniq) <= limit:
        return "、".join(uniq)
    return "、".join(uniq[:limit]) + f" 等 {len(uniq)} 项"


def _detail(title: str, columns: list[str], rows: list[list]) -> dict:
    """构造明细表：超出上限的行被截断，但保留总条数供导出时说明。"""
    total = len(rows)
    return {
        "title": title,
        "columns": columns,
        "rows": rows,
        "total": total,
    }


# ==================== 各准备事项的收集器 ====================
# 每个收集器返回：
#   {"stats": [(标签, 数量)], "details": {... 表格数据 ...}, "warnings": [...], "notes": [...]}
# warnings 为「提醒」：仅提示风险。notes 为中性说明（不计入状态）。

def _c_competition_base(cid: int) -> dict:
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=cid).first()
    if comp is None:
        return {"stats": [("比赛", 0)], "warnings": ["比赛不存在"]}
    warnings = []
    if comp.status != "ACTIVE":
        warnings.append(f"比赛状态为 {comp.status}，非进行中（ACTIVE），玩家侧功能可能不可用")
    return {
        "stats": [("比赛", 1), ("状态", comp.status)],
        "details": _detail("比赛", ["ID", "名称", "状态", "创建时间", "更新时间"], [[comp.id, comp.name, comp.status, _fmt_dt(comp.created_at), _fmt_dt(comp.updated_at)]]),
        "warnings": warnings,
    }


def _c_map_background(cid: int) -> dict:
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=cid).first()
    bg = _json_dict(comp.map_background) if comp else {}
    url = bg.get("url") or bg.get("filename") or ""
    stats = [("背景图", 1 if url else 0)]
    if bg.get("width") or bg.get("height"):
        stats.append(("尺寸", f"{int(bg.get('width') or 0)}×{int(bg.get('height') or 0)}"))
    details = None
    if url:
        details = _detail(
            "地图背景图",
            ["地址", "文件名", "宽", "高"],
            [[url, bg.get("filename") or "", bg.get("width") or "", bg.get("height") or ""]],
        )
    return {"stats": stats, "details": details}


def _c_fiscal_year(cid: int) -> dict:
    from apps.competitions.models import FiscalYear

    rows = list(
        FiscalYear.objects.filter(competition_id=cid).order_by("year")
        .values("id", "year", "status", "created_at", "updated_at")
    )
    warnings = []
    active = [r for r in rows if r["status"] == "ACTIVE"]
    if not rows:
        warnings.append("尚未创建任何财年，比赛没有时间轴")
    elif not active:
        warnings.append("没有「进行中」的财年，财年定时器(FY_START/FY_END)不会触发")
    if len(active) > 1:
        warnings.append(f"存在 {len(active)} 个进行中的财年，通常同一时间只应有一个")
    return {
        "stats": [("财年", len(rows)), ("进行中", len(active))],
        "details": _detail("财年", ["ID", "财年", "状态", "创建时间", "更新时间"], [
                [r["id"], f"第 {r['year']} 财年", r["status"], _fmt_dt(r["created_at"]), _fmt_dt(r["updated_at"])]
                for r in rows
            ]),
        "warnings": warnings,
    }


def _c_stock_config(cid: int) -> dict:
    from apps.competitions.models import Competition
    from apps.stock.engine import DEFAULT_STOCK_CONFIG, resolve_stock_config

    comp = Competition.objects.filter(pk=cid).first()
    custom = comp.stock_config if comp else None
    effective = resolve_stock_config(custom)
    is_custom = isinstance(custom, dict) and len(custom) > 0

    warnings = []
    limit = effective.get("limitPct")
    move = effective.get("maxMovePct")
    if isinstance(limit, (int, float)) and isinstance(move, (int, float)) and move > limit:
        warnings.append(f"单轮最大波动 maxMovePct({move}) 大于限幅 limitPct({limit})，可能触顶异常")
    mm_min = effective.get("mmMinQty")
    mm_max = effective.get("mmMaxQty")
    if isinstance(mm_min, (int, float)) and isinstance(mm_max, (int, float)) and mm_min > mm_max:
        warnings.append(f"做市商最小数量 mmMinQty({mm_min}) 大于最大数量 mmMaxQty({mm_max})")
    for key in ("mmBadNewsProb", "mmGoodNewsProb"):
        v = effective.get(key)
        if isinstance(v, (int, float)) and not (0 <= v <= 1):
            warnings.append(f"{key}({v}) 不在 0~1 区间")
    diff = {k: v for k, v in effective.items() if DEFAULT_STOCK_CONFIG.get(k) != v}

    return {
        "stats": [("配置来源", "自定义" if is_custom else "系统默认"), ("偏离默认项", len(diff))],
        "details": _detail("股票系统参数（生效值）", ["参数", "生效值", "系统默认", "是否已改"], [
                [k, effective.get(k), DEFAULT_STOCK_CONFIG.get(k), "是" if k in diff else ""]
                for k in sorted(effective.keys())
            ]),
        "warnings": warnings,
        "notes": ["未配置自定义参数时，导出记录的是系统默认值（各比赛共用）。"],
    }


def _c_industry_types(cid: int) -> dict:
    from apps.industry_types.models import IndustryField, IndustryType

    types = list(IndustryType.objects.all().order_by("code"))
    field_counts = dict(
        IndustryField.objects.values_list("industry_type_id")
        .annotate(n=Count("id"))
        .values_list("industry_type_id", "n")
    )
    used = set(
        Company.objects.filter(competition_id=cid)
        .exclude(industry_type__isnull=True)
        .values_list("industry_type_id", flat=True)
    )
    warnings = []
    if not types:
        warnings.append("尚未创建任何产业类型，公司无法归属行业")
    unused = [t.name for t in types if t.id not in used]
    if types and unused:
        warnings.append(f"本比赛未使用 {len(unused)} 个产业类型：{_short_names(unused)}")
    no_field = [t.name for t in types if field_counts.get(t.id, 0) == 0]
    if no_field:
        warnings.append(f"{len(no_field)} 个产业类型没有任何字段：{_short_names(no_field)}")
    return {
        "stats": [("产业类型", len(types)), ("本比赛在用", len(used))],
        "details": _detail("产业类型（全局库）", ["ID", "名称", "code", "字段数", "本比赛是否在用"], [
                [t.id, t.name, t.code, field_counts.get(t.id, 0), "在用" if t.id in used else ""]
                for t in types
            ]),
        "warnings": warnings,
        "notes": ["产业类型为全局资源（无比赛归属），导出为整个库，供复用到其它比赛。"],
    }


def _c_industry_fields(cid: int) -> dict:
    from apps.industry_types.models import IndustryField

    fields = list(
        IndustryField.objects.select_related("industry_type").order_by(
            "industry_type__code", "sort_order", "id"
        )
    )
    used_type_ids = set(
        Company.objects.filter(competition_id=cid)
        .exclude(industry_type__isnull=True)
        .values_list("industry_type_id", flat=True)
    )
    # 仅统计本比赛在用产业类型的字段，避免其它行业的历史配置干扰体检
    relevant = [f for f in fields if f.industry_type_id in used_type_ids] if used_type_ids else []

    warnings = []
    calc_missing = [f for f in relevant if f.is_calculated and not (f.calc_graph or "").strip()]
    for f in calc_missing:
        warnings.append(
            f"字段「{f.industry_type.name}·{f.name}」标记为计算字段但没有配置产业计算图，该字段不会自动推导"
        )

    timer_enabled = [f for f in relevant if f.timer_enabled]
    timer_bad = [f for f in timer_enabled if not f.timer_trigger]
    for f in timer_bad:
        warnings.append(f"字段「{f.industry_type.name}·{f.name}」启用了财年定时器但未设置触发时机")

    both = [f for f in timer_enabled if f.is_calculated]
    for f in both:
        warnings.append(
            f"字段「{f.industry_type.name}·{f.name}」同时启用了计算字段与财年定时器（二者应互斥）"
        )

    # timer_value 形如 "field:<key>" 时，被引用字段必须存在
    keys_by_type: dict[int, set[str]] = {}
    for f in fields:
        keys_by_type.setdefault(f.industry_type_id, set()).add(f.field_key)
    for f in timer_enabled:
        tv = (f.timer_value or "").strip()
        if tv.startswith(TIMER_REF_PREFIX):
            ref = tv[len(TIMER_REF_PREFIX):]
            if ref not in keys_by_type.get(f.industry_type_id, set()):
                warnings.append(
                    f"字段「{f.industry_type.name}·{f.name}」的定时器引用了不存在的字段 {ref}"
                )

    # 重复字段名（fieldKey 不同但中文同名）会造成录入混淆
    name_counter: dict[tuple[int, str], list[str]] = {}
    for f in relevant:
        name_counter.setdefault((f.industry_type_id, f.name), []).append(f.field_key)
    for (type_id, name), klist in name_counter.items():
        if len(klist) > 1:
            tname = next((f.industry_type.name for f in relevant if f.industry_type_id == type_id), type_id)
            warnings.append(f"产业「{tname}」有 {len(klist)} 个同名（{name}）但 key 不同的字段：{_short_names(klist)}")

    used_types = set(used_type_ids)
    if used_types and not relevant:
        warnings.append("本比赛在用的产业类型下没有任何字段")

    return {
        "stats": [
            ("字段总数", len(fields)),
            ("本比赛在用", len(relevant)),
            ("计算字段", len([f for f in relevant if f.is_calculated])),
            ("定时器字段", len(timer_enabled)),
        ],
        "details": _detail("产业字段", ["产业类型", "字段名", "fieldKey", "类型", "可见", "计算字段", "有计算图", "定时器", "触发时机", "定时值"], [
                [
                    f.industry_type.name if f.industry_type else "",
                    f.name,
                    f.field_key,
                    f.field_type,
                    f.visible,
                    f.is_calculated,
                    bool((f.calc_graph or "").strip()),
                    f.timer_enabled,
                    f.timer_trigger or "",
                    f.timer_value or "",
                ]
                for f in fields
            ]),
        "warnings": warnings,
    }


def _c_companies(cid: int) -> dict:
    companies = list(
        Company.objects.filter(competition_id=cid)
        .select_related("industry_type", "region")
        .order_by("id")
    )
    warnings = []
    no_industry = [c.name for c in companies if c.industry_type_id is None]
    if no_industry:
        warnings.append(
            f"{len(no_industry)} 家公司未设置所属产业类型，其字段集合为空：{_short_names(no_industry)}"
        )
    no_region = [c.name for c in companies if c.region_id is None]
    if no_region:
        warnings.append(f"{len(no_region)} 家公司未设置所在区域：{_short_names(no_region)}")
    inactive = [c.name for c in companies if c.status != "ACTIVE"]
    if inactive:
        warnings.append(f"{len(inactive)} 家公司状态非 ACTIVE：{_short_names(inactive)}")
    if not companies:
        warnings.append("尚未创建任何公司")
    names = [c.name for c in companies]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        warnings.append(f"存在同名公司（不同 ID）：{_short_names(sorted(dup))}")

    return {
        "stats": [("公司", len(companies)), ("已设产业", len(companies) - len(no_industry)), ("已设区域", len(companies) - len(no_region))],
        "details": _detail("公司", ["ID", "名称", "产业类型", "区域", "状态"], [
                [
                    c.id,
                    c.name,
                    c.industry_type.name if c.industry_type else "",
                    c.region.name if c.region else "",
                    c.status,
                ]
                for c in companies
            ]),
        "warnings": warnings,
    }


def _c_company_field_values(cid: int) -> dict:
    from apps.industry_types.models import IndustryField

    companies = list(Company.objects.filter(competition_id=cid).select_related("industry_type"))
    if not companies:
        return {"stats": [("公司", 0)], "warnings": ["尚未创建公司，无法统计字段初始值"]}

    # 每个产业类型的字段集合
    fields_by_type: dict[int, list[IndustryField]] = {}
    for f in IndustryField.objects.all().only("id", "industry_type_id", "name", "field_key", "is_calculated"):
        fields_by_type.setdefault(f.industry_type_id, []).append(f)

    filled_map: dict[int, set[int]] = {}
    for row in CompanyFieldValue.objects.filter(company__competition_id=cid).values(
        "company_id", "industry_field_id"
    ):
        filled_map.setdefault(row["company_id"], set()).add(row["industry_field_id"])

    warnings = []
    missing_total = 0
    rows = []
    for c in companies:
        flds = fields_by_type.get(c.industry_type_id or 0, [])
        basic = [f for f in flds if not f.is_calculated]
        filled = filled_map.get(c.id, set())
        missing = [f for f in basic if f.id not in filled]
        missing_total += len(missing)
        if missing:
            warnings.append(
                f"公司「{c.name}」有 {len(missing)} 个基础字段没有初始值：{_short_names([f.name for f in missing])}"
            )
        rows.append(
            [
                c.id,
                c.name,
                c.industry_type.name if c.industry_type else "",
                len(basic),
                len(basic) - len(missing),
                len(missing),
                len(flds) - len(basic),
            ]
        )
    if missing_total:
        warnings.insert(0, f"共 {missing_total} 个字段缺少初始值（未填写的字段在引擎侧按类型取空值）")

    return {
        "stats": [
            ("公司", len(companies)),
            ("未填字段合计", missing_total),
            ("已填字段合计", sum(int(r[4]) for r in rows)),
        ],
        "details": _detail("公司字段初始值覆盖情况", ["公司ID", "公司", "产业类型", "基础字段", "已填", "未填", "计算字段"], rows),
        "warnings": warnings,
        "notes": ["计算字段无需手填，由产业计算图级联重算，故不计入缺失。"],
    }


def _simple_named(cid: int, model, extra_columns: list[tuple[str, str]], warnings_fn=None, **filter_kw) -> dict:
    """通用收集器：按名称罗列的简单比赛级主数据。"""
    rows = list(model.objects.filter(competition_id=cid, **filter_kw).order_by("id"))
    warnings = warnings_fn(rows) if warnings_fn else []
    return {
        "stats": [("数量", len(rows))],
        "details": _detail("", ["ID", "名称"] + [c[0] for c in extra_columns], [
                [getattr(r, "id", ""), getattr(r, "name", "")]
                + [getattr(r, attr, "") for _, attr in extra_columns]
                for r in rows
            ]),
        "warnings": warnings,
    }


def _c_materials(cid: int) -> dict:
    from apps.materials.models import Material

    rows = list(Material.objects.filter(competition_id=cid).order_by("id"))
    warnings = []

    def _norm_origin(raw: str) -> list[str]:
        """产地：兼容 JSON 数组、逗号分隔、空格分隔三种写法。"""
        s = (raw or "").strip()
        if not s:
            return []
        v = _json_list(s)
        if v:
            return [str(x).strip() for x in v if str(x).strip()]
        if "," in s or "，" in s:
            return [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]
        return [x.strip() for x in s.split() if x.strip()]

    node_names = {
        n.name for n in _map_nodes(cid)
    }
    no_origin = [m.name for m in rows if not _norm_origin(m.origin)]
    if no_origin:
        warnings.append(f"{len(no_origin)} 种原料未填写产地：{_short_names(no_origin)}")

    unknown_origin = []
    for m in rows:
        for o in _norm_origin(m.origin):
            if node_names and o not in node_names:
                unknown_origin.append(f"{m.name}→{o}")
    if unknown_origin:
        warnings.append(
            f"{len(unknown_origin)} 处原料产地不是本比赛的地图节点名：{_short_names(unknown_origin)}"
        )

    no_carbon = [m.name for m in rows if not m.carbon_emission_coefficient]
    if no_carbon:
        warnings.append(f"{len(no_carbon)} 种原料碳排放系数为 0：{_short_names(no_carbon)}")

    no_price = [m.name for m in rows if not _json_dict(m.node_prices)]
    if no_price:
        warnings.append(
            f"{len(no_price)} 种原料未配置任何地点价（将统一按基础价计算）：{_short_names(no_price)}"
        )
    if not rows:
        warnings.append("尚未录入任何原料，依赖原料的零件配比与合同清单都会为空")

    return {
        "stats": [("原料", len(rows)), ("已配地点价", len(rows) - len(no_price))],
        "details": _detail("原料", ["ID", "名称", "产地", "碳排放系数", "类型", "地点价"], [
                [m.id, m.name, m.origin, m.carbon_emission_coefficient, m.type, _json_dict(m.node_prices)]
                for m in rows
            ]),
        "warnings": warnings,
        "notes": ["地点价以地图节点 id 为键存储，换比赛复用节点 id 会变化，需重新配置。"],
    }


def _c_parts(cid: int) -> dict:
    from apps.parts.models import Part, PartMaterial, PartTechRequirement

    rows = list(Part.objects.filter(competition_id=cid).order_by("id"))
    mat_map: dict[int, int] = dict(
        PartMaterial.objects.filter(part__competition_id=cid)
        .values_list("part_id").annotate(n=Count("id")).values_list("part_id", "n")
    )
    tech_map: dict[int, int] = dict(
        PartTechRequirement.objects.filter(part__competition_id=cid)
        .values_list("part_id").annotate(n=Count("id")).values_list("part_id", "n")
    )
    warnings = []
    no_mat = [p.name for p in rows if not mat_map.get(p.id)]
    if no_mat:
        warnings.append(
            f"{len(no_mat)} 个零件没有原料配比，合同的「所需原料」聚合结果为空：{_short_names(no_mat)}"
        )
    if not rows:
        warnings.append("尚未录入任何零件，产品配比将无从配置")
    material_names = {
        _id: name
        for _id, name in _materials_qs(cid).values_list("id", "name")
    }
    rows_mat = [
        [pm.part.name if pm.part else "", material_names.get(pm.material_id, f"#{pm.material_id}"), pm.ratio]
        for pm in PartMaterial.objects.filter(part__competition_id=cid).select_related("part").order_by("part_id", "id")
    ]
    return {
        "stats": [("零件", len(rows)), ("已配原料", len(rows) - len(no_mat))],
        "details": _detail("零件", ["ID", "名称", "原料配比项数", "科技需求项数"], [[p.id, p.name, mat_map.get(p.id, 0), tech_map.get(p.id, 0)] for p in rows]),
        "extra_tables": [
            {
                "title": "零件-原料配比",
                "columns": ["零件", "原料", "系数"],
                "rows": rows_mat,
            }
        ] if rows_mat else [],
        "warnings": warnings,
    }


def _c_products(cid: int) -> dict:
    from apps.products.models import Product, ProductPart, ProductTechRequirement

    rows = list(Product.objects.filter(competition_id=cid).order_by("id"))
    part_map: dict[int, int] = dict(
        ProductPart.objects.filter(product__competition_id=cid)
        .values_list("product_id").annotate(n=Count("id")).values_list("product_id", "n")
    )
    tech_map: dict[int, int] = dict(
        ProductTechRequirement.objects.filter(product__competition_id=cid)
        .values_list("product_id").annotate(n=Count("id")).values_list("product_id", "n")
    )
    warnings = []
    no_part = [p.name for p in rows if not part_map.get(p.id)]
    if no_part:
        warnings.append(
            f"{len(no_part)} 个产品没有零件配比，合同的「需要的零件」聚合结果为空：{_short_names(no_part)}"
        )
    if not rows:
        warnings.append("尚未录入任何产品，消费者需求将无从填写")

    part_names = {pid: nm for pid, nm in _parts_qs(cid).values_list("id", "name")}
    rows_part = [
        [pp.product.name if pp.product else "", part_names.get(pp.part_id, f"#{pp.part_id}"), pp.ratio]
        for pp in ProductPart.objects.filter(product__competition_id=cid).select_related("product").order_by("product_id", "id")
    ]
    return {
        "stats": [("产品", len(rows)), ("已配零件", len(rows) - len(no_part))],
        "details": _detail("产品", ["ID", "名称", "零件配比项数", "科技需求项数"], [[p.id, p.name, part_map.get(p.id, 0), tech_map.get(p.id, 0)] for p in rows]),
        "extra_tables": [
            {
                "title": "产品-零件配比",
                "columns": ["产品", "零件", "系数"],
                "rows": rows_part,
            }
        ] if rows_part else [],
        "warnings": warnings,
    }


def _c_production_lines(cid: int) -> dict:
    from apps.production_lines.models import ProductionLine

    d = _simple_named(cid, ProductionLine, [("单价", "price")])
    d["details"]["title"] = "生产线"
    return d


def _c_infrastructures(cid: int) -> dict:
    from apps.infrastructures.models import Infrastructure

    rows = list(Infrastructure.objects.filter(competition_id=cid).order_by("id"))
    warnings = []
    zero_price = [i.name for i in rows if not i.price]
    if zero_price:
        warnings.append(f"{len(zero_price)} 项基建单价为 0：{_short_names(zero_price)}")
    if not rows:
        warnings.append("尚未录入基建，合同基建类聚合端点与玩家购置都会为空")
    return {
        "stats": [("基建", len(rows))],
        "details": _detail("基建", ["ID", "名称", "单价", "占地面积", "启用费用", "就业率加成", "人口加成", "高素质人口加成", "幸福度加成", "人均收益加成", "减碳加成"], [
                [
                    i.id, i.name, i.price, i.footprint, i.activation_price,
                    i.employment_rate_bonus, i.population_bonus, i.high_quality_population_bonus,
                    i.happiness_index_bonus, i.per_capita_income_bonus, i.carbon_reduction_bonus,
                ]
                for i in rows
            ]),
        "warnings": warnings,
    }


def _c_vehicles(cid: int) -> dict:
    from apps.vehicles.models import Vehicle, VehiclePathType

    rows = list(Vehicle.objects.filter(competition_id=cid).select_related("fuel").order_by("id"))
    pt_map: dict[int, list[str]] = {}
    for vpt in VehiclePathType.objects.filter(vehicle__competition_id=cid).select_related("path_type"):
        pt_map.setdefault(vpt.vehicle_id, []).append(vpt.path_type.name if vpt.path_type else "")
    warnings = []
    no_pt = [v.name for v in rows if not pt_map.get(v.id)]
    if no_pt:
        warnings.append(f"{len(no_pt)} 种载具未勾选可通行路径类型，运输路径校验会失败：{_short_names(no_pt)}")
    no_fuel = [v.name for v in rows if v.fuel_id is None]
    if no_fuel:
        warnings.append(f"{len(no_fuel)} 种载具未绑定燃料：{_short_names(no_fuel)}")
    bad_cargo = [v.name for v in rows if not v.max_cargo]
    if bad_cargo:
        warnings.append(f"{len(bad_cargo)} 种载具载货量为 0：{_short_names(bad_cargo)}")
    if not rows:
        warnings.append("尚未录入载具，运输与物流相关玩法不可用")
    return {
        "stats": [("载具", len(rows)), ("已配路径类型", len(rows) - len(no_pt))],
        "details": _detail("载具", ["ID", "名称", "燃料", "载货量", "每公里油耗", "碳排放系数", "单价", "可通行路径类型"], [
                [
                    v.id, v.name, v.fuel.name if v.fuel else "", v.max_cargo,
                    v.fuel_consumption_per_km, v.carbon_emission, v.price,
                    _short_names(pt_map.get(v.id, [])),
                ]
                for v in rows
            ]),
        "warnings": warnings,
    }


def _c_warehouses(cid: int) -> dict:
    from apps.warehouses.models import Warehouse

    rows = list(Warehouse.objects.filter(competition_id=cid).order_by("id"))
    warnings = []
    kinds = {w.type for w in rows}
    missing = {"MATERIAL", "PART", "PRODUCT", "FUEL"} - kinds
    if rows and missing:
        warnings.append(f"缺少以下种类的仓库：{'、'.join(sorted(missing))}，对应物资无处存放")
    bad_cap = [w.name for w in rows if not w.capacity]
    if bad_cap:
        warnings.append(f"{len(bad_cap)} 个仓库容量为 0：{_short_names(bad_cap)}")
    if not rows:
        warnings.append("尚未录入仓库")
    return {
        "stats": [("仓库", len(rows)), ("覆盖种类", len(kinds))],
        "details": _detail("仓库", ["ID", "名称", "种类", "容量", "单价"], [[w.id, w.name, w.type, w.capacity, w.price] for w in rows]),
        "warnings": warnings,
    }


def _c_fuels(cid: int) -> dict:
    from apps.fuels.models import Fuel

    rows = list(Fuel.objects.filter(competition_id=cid).order_by("id"))
    warnings = []
    zero = [f.name for f in rows if not f.price_per_liter]
    if zero:
        warnings.append(f"{len(zero)} 种燃料单价为 0：{_short_names(zero)}")
    if not rows:
        warnings.append("尚未录入燃料，载具无法绑定燃料")
    return {
        "stats": [("燃料", len(rows))],
        "details": _detail("燃料", ["ID", "名称", "每升单价"], [[f.id, f.name, f.price_per_liter] for f in rows]),
        "warnings": warnings,
    }


def _c_regions(cid: int) -> dict:
    from apps.regions.models import Region

    rows = list(Region.objects.filter(competition_id=cid).order_by("id"))
    warnings = []
    if not rows:
        warnings.append("尚未创建区域，公司无法归属区域、区域总览为空")
    companies = list(Company.objects.filter(competition_id=cid).only("id", "name", "region_id"))
    no_region = [c.name for c in companies if c.region_id is None]
    if companies and no_region:
        warnings.append(f"{len(no_region)} 家公司未归属区域：{_short_names(no_region)}")
    return {
        "stats": [("区域", len(rows))],
        "details": _detail("区域", ["ID", "名称", "说明"], [[r.id, r.name, r.description or ""] for r in rows]),
        "warnings": warnings,
    }


def _c_map_node_types(cid: int) -> dict:
    from apps.maps.models import MapNodeType

    d = _simple_named(cid, MapNodeType, [("颜色", "color"), ("说明", "description")])
    d["details"]["title"] = "地图节点类型"
    return d


def _c_path_types(cid: int) -> dict:
    from apps.maps.models import PathType

    d = _simple_named(cid, PathType, [("颜色", "color"), ("说明", "description")])
    d["details"]["title"] = "路径类型"
    if not d["details"]["rows"]:
        d["warnings"] = ["尚未创建路径类型，地图连线与载具通行性都无法配置"]
    return d


def _map_nodes(cid: int):
    from apps.maps.models import MapNode

    return list(MapNode.objects.filter(competition_id=cid).select_related("node_type").order_by("id"))


def _c_map_nodes(cid: int) -> dict:
    rows = _map_nodes(cid)
    node_ids = {n.id for n in rows}
    from apps.maps.models import MapEdge

    connected: set[int] = set()
    for e in MapEdge.objects.filter(competition_id=cid).values("from_node_id", "to_node_id"):
        if e["from_node_id"] in node_ids:
            connected.add(e["from_node_id"])
        if e["to_node_id"] in node_ids:
            connected.add(e["to_node_id"])
    isolated = [n.name for n in rows if n.id not in connected]
    warnings = []
    if isolated:
        warnings.append(
            f"{len(isolated)} 个地图节点没有任何连线，不可达，会导致路程计算失败：{_short_names(isolated)}"
        )
    if not rows:
        warnings.append("尚未创建地图节点，运输与所在地玩法不可用")
    return {
        "stats": [("节点", len(rows)), ("已连线的节点", len(connected)), ("孤立节点", len(isolated))],
        "details": _detail("地图节点", ["ID", "名称", "区域", "节点类型", "X", "Y", "是否有连线"], [
                [n.id, n.name, n.region, n.node_type.name if n.node_type else "", n.x, n.y, "是" if n.id in connected else "否"]
                for n in rows
            ]),
        "warnings": warnings,
    }


def _c_map_edges(cid: int) -> dict:
    from apps.maps.models import MapEdge

    rows = list(
        MapEdge.objects.filter(competition_id=cid)
        .select_related("from_node", "to_node", "path_type")
        .order_by("id")
    )
    warnings = []
    zero_dist = [f"#{e.id}({e.from_node.name if e.from_node else '?'}→{e.to_node.name if e.to_node else '?'})" for e in rows if not e.distance]
    if zero_dist:
        warnings.append(f"{len(zero_dist)} 条连线距离为 0：{_short_names(zero_dist)}")
    no_type = [f"#{e.id}" for e in rows if e.path_type_id is None]
    if no_type:
        warnings.append(f"{len(no_type)} 条连线未设置路径类型：{_short_names(no_type)}")
    if not rows:
        warnings.append("尚未创建地图连线，所有节点都不可达")
    return {
        "stats": [("连线", len(rows)), ("总里程", round(sum(e.distance or 0 for e in rows), 4))],
        "details": _detail("地图连线", ["ID", "起点", "终点", "距离", "路径类型"], [
                [
                    e.id,
                    e.from_node.name if e.from_node else "",
                    e.to_node.name if e.to_node else "",
                    e.distance,
                    e.path_type.name if e.path_type else "",
                ]
                for e in rows
            ]),
        "warnings": warnings,
    }


def _c_tech_nodes(cid: int) -> dict:
    from apps.tech_tree.models import TechNode

    rows = list(TechNode.objects.filter(competition_id=cid).order_by("tier", "id"))
    warnings = []
    tiers = {t.tier for t in rows}
    zero_cost = [t.name for t in rows if not t.research_cost]
    if zero_cost:
        warnings.append(f"{len(zero_cost)} 个科技节点研发费用为 0：{_short_names(zero_cost)}")
    if rows and 0 in tiers:
        warnings.append("存在 tier=0 的科技节点（未分级），研发节奏可能不符合预期")
    if not rows:
        warnings.append("尚未创建科技节点，研发玩法与零件/产品科技需求为空")
    return {
        "stats": [("科技节点", len(rows)), ("层级数", len(tiers))],
        "details": _detail("科技节点", ["ID", "名称", "层级", "研发费用", "说明"], [[t.id, t.name, t.tier, t.research_cost, t.description or ""] for t in rows]),
        "warnings": warnings,
    }


def _c_tech_prerequisites(cid: int) -> dict:
    from apps.tech_tree.models import TechNode, TechPrerequisite

    nodes = list(TechNode.objects.filter(competition_id=cid).values("id", "name"))
    name_by_id = {n["id"]: n["name"] for n in nodes}
    prereqs = list(
        TechPrerequisite.objects.filter(node__competition_id=cid).values("node_id", "prerequisite_id")
    )
    # 邻接表：node -> 它的前置
    adj: dict[int, list[int]] = {}
    for p in prereqs:
        adj.setdefault(p["node_id"], []).append(p["prerequisite_id"])

    # 环检测（DFS 三色标记）
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {}
    cycles: list[str] = []

    def dfs(u: int, stack: list[int]) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                names = [name_by_id.get(x, f"#{x}") for x in stack[stack.index(v):]] + [name_by_id.get(v, f"#{v}")]
                cycles.append(" → ".join(names))
            elif color.get(v, WHITE) == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for n in nodes:
        if color.get(n["id"], WHITE) == WHITE:
            dfs(n["id"], [])

    warnings = []
    if cycles:
        warnings.append(f"科技前置存在 {len(cycles)} 处环路，相关科技将永远无法解锁：{_short_names(cycles, 3)}")
    if not prereqs:
        warnings.append("尚未配置任何科技前置依赖，所有科技可同时研发")
    orphan = [n["name"] for n in nodes if not adj.get(n["id"])]
    if prereqs and orphan:
        warnings.append(f"{len(orphan)} 个科技节点没有前置（作为起始科技）：{_short_names(orphan)}")

    return {
        "stats": [("前置关系", len(prereqs)), ("成环节点数", len(cycles))],
        "details": _detail("科技前置依赖", ["科技节点", "前置节点"], [
                [name_by_id.get(p["node_id"], f"#{p['node_id']}"), name_by_id.get(p["prerequisite_id"], f"#{p['prerequisite_id']}")]
                for p in prereqs
            ]),
        "warnings": warnings,
    }


def _c_consumer_demands(cid: int) -> dict:
    rows = list(
        ConsumerDemand.objects.filter(competition_id=cid).select_related("product").order_by("region", "id")
    )
    product_names = {p.name for p in _products_qs(cid)}
    warnings = []
    orphan = [d.product_type for d in rows if d.product_id is None]
    if orphan:
        warnings.append(
            f"{len(orphan)} 条需求未关联到产品记录（仅存了名称），玩家可能无法交付：{_short_names(orphan)}"
        )
    unknown = [d.product_type for d in rows if d.product_type and d.product_type not in product_names]
    if unknown:
        warnings.append(f"{len(unknown)} 条需求的产品名在本比赛产品中不存在：{_short_names(unknown)}")
    zero = [f"{d.region}·{d.product_type}" for d in rows if not d.quantity]
    if zero:
        warnings.append(f"{len(zero)} 条需求数量为 0：{_short_names(zero)}")
    regions = {d.region for d in rows}
    all_regions = {r.name for r in _regions_qs(cid)}
    if all_regions and regions - all_regions:
        warnings.append(f"需求中的区域名不是本比赛区域：{_short_names(sorted(regions - all_regions))}")
    if not rows:
        warnings.append("尚未录入消费者需求，订单来源为空")
    return {
        "stats": [("需求条目", len(rows)), ("覆盖区域", len(regions)), ("总需求量", sum(d.quantity or 0 for d in rows))],
        "details": _detail("消费者需求", ["ID", "区域", "产品类型", "关联产品", "数量", "备注"], [
                [d.id, d.region, d.product_type, d.product.name if d.product else "", d.quantity, d.note or ""]
                for d in rows
            ]),
        "warnings": warnings,
    }


def _c_acceptance_api_smoke(cid: int) -> dict:
    """开赛前接口/部署自检：迁移是否全部应用 + 后端版本信息。

    只做只读检查（比对 migration 文件与 django_migrations 表），不执行迁移。
    """
    from django.conf import settings
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    warnings: list[str] = []
    pending: list[str] = []
    try:
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        applied = set(loader.applied_migrations)
        for key, migration in sorted(loader.disk_migrations.items()):
            if key in applied:
                continue
            # 只关心本仓库自己的 app，第三方残留迁移不作为开赛阻断项
            if not str(key[0]).startswith("apps."):
                continue
            if not migration.operations:
                continue
            pending.append(f"{key[0]}.{key[1]}")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"迁移状态检查失败：{type(e).__name__}: {e}")

    if pending:
        warnings.append(
            f"存在 {len(pending)} 个未应用的迁移，请在开赛前执行 python manage.py migrate：{_short_names(pending)}"
        )

    db = settings.DATABASES.get("default", {})
    db_engine = db.get("ENGINE", "")
    version_path = settings.BASE_DIR / "VERSION.json"
    version = ""
    if version_path.exists():
        try:
            version = str((_json_obj(version_path.read_text(encoding="utf-8")) or {}).get("version") or "")
        except Exception:  # noqa: BLE001
            version = ""

    return {
        "stats": [
            ("检查项", 4),
            ("未应用迁移", len(pending)),
            ("数据库引擎", db_engine.rsplit(".", 1)[-1] or "-"),
            ("DEBUG", settings.DEBUG),
        ],
        "details": _detail(
            "后端自检",
            ["检查项", "结果"],
            [
                ["未应用的迁移（本仓库 app）", "、".join(pending) if pending else "无"],
                ["数据库引擎", db_engine],
                ["DEBUG", settings.DEBUG],
                ["后端版本(VERSION.json)", version or "未读取到"],
            ],
        ),
        "warnings": warnings,
        "notes": [
            "其余冒烟项需在终端手工执行：python manage.py check、npm run typecheck、以及 health/login/me 等接口连通性验证。",
        ],
    }


def _c_acceptance_backup(cid: int) -> dict:
    """备份与归档提示：记录当前数据库体量，便于对照备份是否完整。"""
    from django.conf import settings

    db = settings.DATABASES.get("default", {})
    name = str(db.get("NAME") or "")
    engine = str(db.get("ENGINE") or "")
    is_sqlite = "sqlite" in engine
    info: list[list] = [["数据库引擎", engine], ["数据库位置", name]]
    warnings: list[str] = []
    if is_sqlite:
        from pathlib import Path

        p = Path(name)
        if p.exists():
            stat = p.stat()
            info.append(["数据库文件大小(MB)", round(stat.st_size / 1024 / 1024, 2)])
            info.append(["数据库文件修改时间", _fmt_dt(datetime.datetime.fromtimestamp(stat.st_mtime))])
        else:
            warnings.append(f"未找到 SQLite 数据库文件：{name}")

    return {
        "stats": [("记录项", len(info)), ("数据库", "SQLite" if is_sqlite else "PostgreSQL/其它")],
        "details": _detail("备份对象", ["项目", "值"], info),
        "warnings": warnings,
        "notes": [
            "导出本报告后请一并备份数据库：SQLite 直接复制 db.sqlite3；PostgreSQL 使用 pg_dump。",
            "导出文件本身即为本次准备的凭证，建议与数据库备份放在同一归档目录。",
        ],
    }


def _c_stocks_impl(cid: int) -> dict:
    from apps.stock.models import Stock

    rows = list(Stock.objects.filter(competition_id=cid).select_related("company").order_by("code"))
    warnings = []
    no_price = [s.name for s in rows if not s.init_price]
    if no_price:
        warnings.append(f"{len(no_price)} 只股票初始价为 0：{_short_names(no_price)}")
    no_shares = [s.name for s in rows if not s.total_shares]
    if no_shares:
        warnings.append(f"{len(no_shares)} 只股票总股本为 0：{_short_names(no_shares)}")
    if not rows:
        warnings.append("尚未创建股票；若本次比赛不使用股票系统可忽略")

    # 卡片引用校验（跨表体检）：股票的碳排/幸福度/行业均值指标引用区域卡片 id
    card_ids = _overview_card_ids(cid)
    bad_refs: list[str] = []
    ref_count = 0
    for s in rows:
        refs: list[Any] = []
        for raw in (s.carbon_field_ref, s.happiness_field_ref):
            if raw:
                refs.append(_json_obj(raw))
        refs.extend(_json_list(s.industry_avg_carbon_refs))
        for obj in refs:
            if not isinstance(obj, dict):
                continue
            ref_count += 1
            card_id = obj.get("cardId")
            if card_id is not None and card_ids and card_id not in card_ids:
                bad_refs.append(f"{s.name}→卡片#{card_id}")
    if bad_refs:
        warnings.append(f"{len(bad_refs)} 处股票指标引用了不存在的区域卡片：{_short_names(bad_refs)}")

    return {
        "stats": [("股票", len(rows)), ("指标卡片引用", ref_count)],
        "details": _detail(
            "股票",
            ["ID", "代码", "名称", "关联公司", "总股本", "初始净利润", "初始价", "当前价", "轮次", "碳排卡片", "幸福度卡片"],
            [
                [
                    s.id, s.code, s.name, s.company.name if s.company else "", s.total_shares,
                    s.init_net_profit, s.init_price, s.current_price, s.round,
                    s.carbon_field_ref or "", s.happiness_field_ref or "",
                ]
                for s in rows
            ],
        ),
        "warnings": warnings,
    }


def _c_funds_accounts(cid: int) -> dict:
    from apps.stock.models import StockFundsAccount

    rows = list(StockFundsAccount.objects.filter(competition_id=cid).order_by("id"))
    companies = list(Company.objects.filter(competition_id=cid).values("id", "name"))
    company_ids = {c["id"] for c in companies}
    company_name = {c["id"]: c["name"] for c in companies}
    covered = {a.company_id for a in rows if a.owner_type == "COMPANY" and a.company_id}
    missing = [company_name[cid_] for cid_ in company_ids - covered]

    warnings = []
    if missing:
        warnings.append(f"{len(missing)} 家公司没有资金账户，其股票买卖无法进行：{_short_names(missing)}")
    no_cash = [a.name for a in rows if a.cash_balance is not None and a.cash_balance == 0]
    if no_cash:
        warnings.append(f"{len(no_cash)} 个账户初始现金为 0：{_short_names(no_cash)}")
    if not rows:
        warnings.append("尚未创建任何资金账户")
    return {
        "stats": [("账户", len(rows)), ("覆盖公司", len(covered & company_ids))],
        "details": _detail("资金账户", ["ID", "名称", "所有者类型", "公司ID", "公司", "用户ID", "现金余额", "绑定字段"], [
                [
                    a.id, a.name, a.owner_type, a.company_id or "",
                    company_name.get(a.company_id, "") if a.company_id else "",
                    a.user_id or "", a.cash_balance, a.bind_field_id or "",
                ]
                for a in rows
            ]),
        "warnings": warnings,
    }


def _overview_card_ids(cid: int) -> set:
    from apps.regions.models import Region

    ids = set()
    for r in Region.objects.filter(competition_id=cid).values_list("overview_cards", flat=True):
        for card in _json_list(r):
            if isinstance(card, dict) and card.get("id") is not None:
                ids.add(card.get("id"))
    return ids


def _c_overview_cards(cid: int) -> dict:
    from apps.regions.models import Region

    rows = []
    for r in Region.objects.filter(competition_id=cid).order_by("id"):
        for card in _json_list(r.overview_cards):
            if isinstance(card, dict):
                rows.append([r.name, card.get("id"), card.get("displayName"), card.get("companyId"), card.get("industryFieldId"), card.get("zone") or ""])
    warnings = []
    if not rows:
        warnings.append("尚未配置任何区域总览卡片；股票的碳排/幸福度指标绑定将无卡片可用")
    return {
        "stats": [("卡片", len(rows)), ("涉及区域", len({r[0] for r in rows}))],
        "details": _detail("区域总览卡片", ["区域", "卡片ID", "显示名", "公司ID", "产业字段ID", "分区"], rows),
        "warnings": warnings,
    }


def _c_contract_types(cid: int) -> dict:
    from apps.industry_types.models import IndustryField

    types = list(ContractType.objects.all().order_by("id"))
    known_keys = set(IndustryField.objects.values_list("field_key", flat=True))
    warnings = []
    rows = []
    for ct in types:
        roles = _json_list(ct.party_roles)
        schema = _json_list(ct.input_schema)
        effects = _json_list(ct.effects)
        conds = _json_list(ct.conditions)

        # 递归收集效果树里的字段引用
        def walk(effs: list) -> list[dict]:
            out = []
            for e in effs:
                if not isinstance(e, dict):
                    continue
                if e.get("kind") == "FIELD":
                    out.append(e)
                elif e.get("kind") == "IF":
                    out += walk(e.get("then") or [])
                    out += walk(e.get("else") or [])
                elif e.get("kind") == "FOREACH":
                    out += walk(e.get("body") or [])
            return out

        leaves = walk(effects)
        missing_fields = [
            f"{leaf.get('party') or '?'}·{leaf.get('fieldKey') or '?'}"
            for leaf in leaves
            if leaf.get("fieldKey") and leaf["fieldKey"] not in known_keys
        ]
        if ct.enabled and not roles:
            warnings.append(f"合同类型「{ct.name}」已启用但没有参与方角色，无法创建合同")
        if ct.enabled and not leaves:
            warnings.append(f"合同类型「{ct.name}」已启用但没有任何产业字段效果，执行后不会改变数据")
        if missing_fields:
            warnings.append(
                f"合同类型「{ct.name}」引用了不存在的产业字段：{_short_names(missing_fields)}"
            )
        rows.append([
            ct.id, ct.key, ct.name, ct.enabled, len(roles), len(schema), len(leaves), len(conds),
        ])
    if not types:
        warnings.append("尚未创建任何合同类型；若本次比赛不使用合同系统可忽略")
    return {
        "stats": [("合同类型", len(types)), ("启用中", len([t for t in types if t.enabled]))],
        "details": _detail("合同类型（全局库）", ["ID", "key", "名称", "启用", "参与方角色数", "输入字段数", "字段效果数", "检查数"], rows),
        "warnings": warnings,
        "notes": ["合同类型为全局资源（无比赛归属），导出为整个库，供复用到其它比赛。"],
    }


def _c_contract_instances(cid: int) -> dict:
    rows = list(
        Contract.objects.filter(competition_id=cid).select_related("contract_type").order_by("id")
    )
    warnings = []
    draft = [c.name for c in rows if c.status == "DRAFT"]
    executed = [c.name for c in rows if c.status == "EXECUTED"]
    if executed:
        warnings.append(
            f"{len(executed)} 份合同已执行并落账（会改写公司字段）：{_short_names(executed)}；若这是开赛前的比赛，请确认是否应回退"
        )
    return {
        "stats": [
            ("合同", len(rows)),
            ("草稿", len(draft)),
            ("待执行", len([c for c in rows if c.status == "PENDING_EXEC"])),
            ("已执行", len(executed)),
        ],
        "details": _detail("合同实例", ["ID", "合同类型", "状态", "参与方", "签订时间", "执行时间"], [
                [
                    c.id,
                    c.contract_type.name if c.contract_type else "",
                    c.status,
                    _short_names([p.get("label") or p.get("role") or "" for p in _json_list(c.parties)]),
                    _fmt_dt(c.signed_at),
                    _fmt_dt(c.executed_at),
                ]
                for c in rows
            ]),
        "warnings": warnings,
    }


def _c_messages(cid: int) -> dict:
    from apps.messages.models import Message

    rows = list(Message.objects.filter(competition_id=cid).order_by("-created_at", "-id"))
    warnings = []
    if rows:
        all_target = len([m for m in rows if m.targets_all])
        if all_target == 0:
            warnings.append("尚未发布过面向全体玩家的消息")
    return {
        "stats": [("消息", len(rows)), ("面向全体", len([m for m in rows if m.targets_all]))],
        "details": _detail("比赛内消息", ["ID", "标题", "面向全体", "指定人数", "创建时间"], [
                [m.id, m.title, m.targets_all, len(_json_list(m.target_user_ids)), _fmt_dt(m.created_at)]
                for m in rows
            ]),
        "warnings": warnings,
    }


def _c_users(cid: int) -> dict:
    from apps.users.models import User

    rows = list(
        User.objects.filter(competition_id=cid).order_by("role", "username")
    )
    by_role: dict[str, int] = {}
    for u in rows:
        by_role[u.role] = by_role.get(u.role, 0) + 1
    warnings = []
    if by_role.get("PLAYER", 0) == 0:
        warnings.append("本比赛下没有任何 PLAYER（选手）账号")
    if by_role.get("COMPETITION_ADMIN", 0) == 0:
        warnings.append("本比赛没有 COMPETITION_ADMIN（比赛管理员），日常运营需超管代劳")
    inactive = [u.username for u in rows if not u.is_active]
    if inactive:
        warnings.append(f"{len(inactive)} 个账号已停用：{_short_names(inactive)}")
    return {
        "stats": [
            ("账号", len(rows)),
            ("超管", by_role.get("SUPER_ADMIN", 0)),
            ("比赛管理员", by_role.get("COMPETITION_ADMIN", 0)),
            ("选手", by_role.get("PLAYER", 0)),
        ],
        "details": _detail("参赛账号", ["ID", "用户名", "显示名", "角色", "启用", "首登需改密"], [
                [u.id, u.username, u.display_name or "", u.role, u.is_active, u.must_change_password]
                for u in rows
            ]),
        "warnings": warnings,
        "notes": ["SUPER_ADMIN 为全局账号（无比赛归属），不在此列表中。"],
    }


def _c_scopes(cid: int) -> dict:
    from apps.users.models import User

    rows = list(User.objects.filter(competition_id=cid).order_by("username"))
    company_ids = {c.id for c in Company.objects.filter(competition_id=cid).only("id")}
    company_names = {c.id: c.name for c in Company.objects.filter(competition_id=cid).only("id", "name")}
    warnings = []
    table = []
    for u in rows:
        c_scopes = _json_list(u.company_scopes)
        v_scopes = _json_list(u.view_company_scopes)
        ct_scopes = _json_list(u.contract_view_company_scopes)
        st_scopes = _json_list(u.stock_company_scopes)
        if u.role == "PLAYER" and not c_scopes and not v_scopes:
            warnings.append(f"选手「{u.username}」未配置任何公司范围，登录后公司/合同/股票列表都会是空的")
        unknown = [s for s in (c_scopes + v_scopes + ct_scopes + st_scopes) if isinstance(s, int) and s not in company_ids]
        if unknown:
            warnings.append(
                f"账号「{u.username}」的范围引用了本比赛不存在的公司 id：{_short_names([str(x) for x in unknown])}"
            )
        table.append([
            u.username, u.role,
            _short_names([company_names.get(i, f"#{i}") for i in c_scopes]),
            _short_names([company_names.get(i, f"#{i}") for i in v_scopes]),
            _short_names([company_names.get(i, f"#{i}") for i in ct_scopes]),
            _short_names([company_names.get(i, f"#{i}") for i in st_scopes]),
        ])
    if not rows:
        warnings.append("本比赛下没有账号，无法开赛")
    return {
        "stats": [("账号", len(rows)), ("已配公司管理范围", len([u for u in rows if _json_list(u.company_scopes)]))],
        "details": _detail("账号公司范围", ["用户名", "角色", "公司管理范围", "公司查看范围", "合同查看范围", "股票范围"], table),
        "warnings": warnings,
    }


# ==================== 收集器注册表 ====================

_COLLECTORS: dict[str, Callable[[int], dict]] = {
    "competition.base": _c_competition_base,
    "competition.map_background": _c_map_background,
    "competition.fiscal_year": _c_fiscal_year,
    "competition.stock_config": _c_stock_config,
    "industry.types": _c_industry_types,
    "industry.fields": _c_industry_fields,
    "company.companies": _c_companies,
    "company.field_values": _c_company_field_values,
    "supply.materials": _c_materials,
    "supply.parts": _c_parts,
    "supply.products": _c_products,
    "supply.production_lines": _c_production_lines,
    "supply.infrastructures": _c_infrastructures,
    "supply.vehicles": _c_vehicles,
    "supply.warehouses": _c_warehouses,
    "supply.fuels": _c_fuels,
    "geo.regions": _c_regions,
    "geo.map_node_types": _c_map_node_types,
    "geo.path_types": _c_path_types,
    "geo.map_nodes": _c_map_nodes,
    "geo.map_edges": _c_map_edges,
    "tech.nodes": _c_tech_nodes,
    "tech.prerequisites": _c_tech_prerequisites,
    "demand.consumer_demands": _c_consumer_demands,
    "market.stocks": _c_stocks_impl,
    "market.funds_accounts": _c_funds_accounts,
    "market.overview_cards": _c_overview_cards,
    "contract.types": _c_contract_types,
    "contract.instances": _c_contract_instances,
    "market.messages": _c_messages,
    "access.users": _c_users,
    "access.scopes": _c_scopes,
    "acceptance.api_smoke": _c_acceptance_api_smoke,
    "acceptance.backup": _c_acceptance_backup,
}


# ==================== 统计辅助（供验收事项引用上文结果） ====================

def _materials_qs(cid: int):
    from apps.materials.models import Material

    return Material.objects.filter(competition_id=cid)


def _parts_qs(cid: int):
    from apps.parts.models import Part

    return Part.objects.filter(competition_id=cid)


def _products_qs(cid: int):
    from apps.products.models import Product

    return Product.objects.filter(competition_id=cid)


def _regions_qs(cid: int):
    from apps.regions.models import Region

    return Region.objects.filter(competition_id=cid)


# ==================== 汇总 ====================

def _status_of(item: PrepItem, warnings: list[str], stats: list[tuple]) -> str:
    if warnings:
        return STATUS_WARNING
    counts = [v for _, v in stats if isinstance(v, int)]
    if item.required and (not counts or all(v == 0 for v in counts)):
        return STATUS_EMPTY
    return STATUS_READY


def collect(competition_id: int) -> dict:
    """收集某场比赛的全部准备数据与体检结果。"""
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=competition_id).first()
    collected: list[dict] = []
    for item in ALL_ITEMS:
        if item.key == "acceptance.data_check":
            # 该事项的统计在全部收集完成后回填
            collected.append({"item": item, "data": {"stats": [], "warnings": []}})
            continue
        fn = _COLLECTORS.get(item.key)
        if fn is None:  # pragma: no cover - 目录与注册表不一致时防御
            collected.append(
                {"item": item, "data": {"stats": [], "warnings": [f"未实现收集器：{item.key}"]}}
            )
            continue
        try:
            collected.append({"item": item, "data": fn(competition_id)})
        except Exception as e:  # noqa: BLE001 - 单事项失败不影响整体导出
            collected.append(
                {"item": item, "data": {"stats": [], "warnings": [f"统计失败：{type(e).__name__}: {e}"]}}
            )

    warning_items = [
        c for c in collected
        if c["item"].key != "acceptance.data_check" and (c["data"].get("warnings") or [])
    ]
    # 回填「体检结果清零」
    for c in collected:
        if c["item"].key == "acceptance.data_check":
            c["data"] = {
                "stats": [("体检提醒", len(warning_items))],
                "warnings": (
                    [f"仍有 {len(warning_items)} 个准备事项存在提醒，请逐项处理后再开始财年"]
                    if warning_items
                    else []
                ),
                "notes": ["全部准备事项均无提醒。" if not warning_items else ""],
            }
            break

    # 组装
    items_out: list[dict] = []
    for c in collected:
        item: PrepItem = c["item"]
        data = c["data"] or {}
        stats = data.get("stats") or []
        warnings = data.get("warnings") or []
        status = _status_of(item, warnings, stats)
        items_out.append(
            {
                **item.to_dict(),
                "status": status,
                "statusLabel": STATUS_LABEL[status],
                "stats": [{"label": str(lb), "value": val} for lb, val in stats],
                "warnings": warnings,
                "notes": [n for n in (data.get("notes") or []) if n],
                "details": data.get("details"),
                "extraTables": data.get("extra_tables") or [],
            }
        )

    by_category = []
    for cat in CATEGORIES:
        cat_items = [i for i in items_out if i["categoryKey"] == cat.key]
        if not cat_items:
            continue
        by_category.append(
            {
                **cat.to_dict(),
                "items": cat_items,
                "summary": _summarize(cat_items),
            }
        )

    required_items = [i for i in items_out if i["required"]]
    summary = {
        "total": len(items_out),
        "required": len(required_items),
        "ready": len([i for i in items_out if i["status"] == STATUS_READY]),
        "warning": len([i for i in items_out if i["status"] == STATUS_WARNING]),
        "empty": len([i for i in items_out if i["status"] == STATUS_EMPTY]),
        "requiredWarning": len([i for i in required_items if i["status"] == STATUS_WARNING]),
        "requiredEmpty": len([i for i in required_items if i["status"] == STATUS_EMPTY]),
        "warningCount": sum(len(i["warnings"]) for i in items_out),
    }

    return {
        "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "competition": (
            {"id": comp.id, "name": comp.name, "status": comp.status} if comp else None
        ),
        "summary": summary,
        "categories": by_category,
    }


def _summarize(items: list[dict]) -> dict:
    return {
        "ready": len([i for i in items if i["status"] == STATUS_READY]),
        "warning": len([i for i in items if i["status"] == STATUS_WARNING]),
        "empty": len([i for i in items if i["status"] == STATUS_EMPTY]),
    }


# ==================== 渲染：Markdown ====================

def render_markdown(plan: dict) -> str:
    """把准备计划渲染为 Markdown 归档报告。"""
    comp = plan.get("competition") or {}
    summary = plan.get("summary") or {}
    lines: list[str] = []
    lines.append(f"# 比赛准备清单与归档 · {comp.get('name') or '(未知比赛)'}")
    lines.append("")
    lines.append(f"- 比赛 ID：{comp.get('id')}")
    lines.append(f"- 比赛状态：{comp.get('status')}")
    lines.append(f"- 导出时间：{plan.get('generatedAt')}")
    lines.append(f"- 生成方式：Gipfel 商赛系统「系统设置 → 比赛准备总览 → 导出」自动生成（只读快照）")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 准备事项总数 | {summary.get('total')} |")
    lines.append(f"| 其中开赛前必须完成 | {summary.get('required')} |")
    lines.append(f"| 状态：就绪 | {summary.get('ready')} |")
    lines.append(f"| 状态：提醒 | {summary.get('warning')} |")
    lines.append(f"| 状态：待准备 | {summary.get('empty')} |")
    lines.append(f"| 提醒条目合计 | {summary.get('warningCount')} |")
    lines.append("")
    lines.append("> 状态含义：「就绪」= 数据已具备且无提醒；「提醒」= 已具备但存在风险项；「待准备」= 必填项尚无数据。")
    lines.append("")

    for cat in plan.get("categories") or []:
        s = cat.get("summary") or {}
        lines.append(f"## {cat.get('title')}")
        lines.append("")
        if cat.get("description"):
            lines.append(f"{cat['description']}")
            lines.append("")
        lines.append(
            f"本组 {len(cat.get('items') or [])} 项：就绪 {s.get('ready', 0)} / 提醒 {s.get('warning', 0)} / 待准备 {s.get('empty', 0)}"
        )
        lines.append("")
        for item in cat.get("items") or []:
            lines.extend(_render_item(item))
    lines.append("---")
    lines.append("")
    lines.append(
        "本文件由系统自动生成，内容为导出时刻的只读快照；"
        "其中的数据统计可直接用于复用比赛设置与赛后归档，但导入新比赛仍需按本文档逐项配置。"
    )
    lines.append("")
    return "\n".join(lines)


def _render_item(item: dict) -> list[str]:
    out: list[str] = []
    flag = "（开赛前必须完成）" if item.get("required") else "（可选）"
    out.append(f"### {item.get('title')} {flag}")
    out.append("")
    out.append(f"- 状态：**{item.get('statusLabel')}**　入口：`{item.get('route')}`")
    if item.get("description"):
        out.append(f"- 说明：{item['description']}")
    stats = item.get("stats") or []
    if stats:
        out.append("- 统计：" + "；".join(f"{s['label']} {s['value']}" for s in stats))
    for w in item.get("warnings") or []:
        out.append(f"- ⚠ 提醒：{w}")
    for n in item.get("notes") or []:
        out.append(f"- 备注：{n}")
    out.append("")
    if item.get("steps"):
        out.append("操作步骤：")
        out.append("")
        for idx, step in enumerate(item["steps"], 1):
            out.append(f"{idx}. {step}")
        out.append("")
    for table in [item.get("details")] + list(item.get("extraTables") or []):
        if not table or not table.get("rows"):
            continue
        out.append(f"**{table.get('title') or '明细'}**")
        out.append("")
        out.append("| " + " | ".join(_text(c) for c in table.get("columns") or []) + " |")
        out.append("| " + " | ".join("---" for _ in table.get("columns") or []) + " |")
        for row in table["rows"]:
            out.append("| " + " | ".join(_cell(v) for v in row) + " |")
        total = table.get("total")
        if isinstance(total, int) and total > len(table["rows"]):
            out.append("")
            out.append(f"（仅列出前 {len(table['rows'])} 条，共 {total} 条）")
        out.append("")
    return out


def render_json(plan: dict) -> str:
    """把准备计划渲染为 JSON 快照。"""
    return json.dumps(plan, ensure_ascii=False, indent=2, default=str)
