"""比赛准备归档：按分组导出 / 导入准备数据。

与 plan.py 的分工：
- plan.py    —— 「体检」视角：统计数量、检查配置风险、渲染人类可读报告（只读）。
- archive.py —— 「搬运」视角：把准备数据导出成可再导入的 JSON，并可导回另一场比赛。

导出文件结构（schemaVersion=1）：
    {
      "schemaVersion": 1,
      "generator": "gipfel-preparation-archive",
      "exportedAt": "YYYY-MM-DD HH:MM:SS",
      "scope": "supply",                     # 分组 key，"all" 表示全部
      "scopeLabel": "④ 物资与产能",
      "sourceCompetition": {"id": 4, "name": "test"},
      "resources": { "<resource>": {"label": "...", "count": 12, "rows": [ ... ]} }
    }

导入约定：
- 目标比赛只允许是「空比赛」（无业务数据），否则需显式 allowNonEmpty=true 走合并模式。
- 依赖按 IMPORT_ORDER 顺序解析，行内以 **旧 id** 保存引用（如 vehicle.fuelId），
  导入时通过 id 映射表换成新主键；引用缺失只记录问题并跳过该行，不中断整批。
- 全局资源（产业类型/字段、合同类型）按自然键（code / key）复用已有记录，不新建重复项。
- 全程只读「校验」可通过 dry_run 完成：dry_run 时用事务回滚，不留任何数据。
"""
from __future__ import annotations

import datetime
import json
from typing import Any, Callable

from django.db import transaction

from .checklist import CATEGORIES, CATEGORY_BY_KEY

SCHEMA_VERSION = 1
GENERATOR = "gipfel-preparation-archive"

# 明细上限：与 plan.py 保持一致，避免导出文件失控（导入不受此限制影响）
_DETAIL_LIMIT = 2000


# ==================== 分组（scope）定义 ====================

# 每个 scope 声明它包含的资源 key 列表（顺序即导出顺序）
SCOPES: dict[str, dict[str, Any]] = {
    "competition": {
        "label": "① 比赛基础",
        # 注意：这里必须用 IMPORT_ORDER 里的资源名（competitionMeta），否则 resources_of_scope 会把它过滤掉
        "resources": ["competitionMeta", "fiscalYears", "stockConfig"],
    },
    "industry": {
        "label": "② 行业口径",
        "resources": ["industryTypes", "industryFields"],
    },
    "company": {
        "label": "③ 参赛主体",
        "resources": ["companies", "companyFieldValues"],
    },
    "supply": {
        "label": "④ 物资与产能",
        # 含 techNodes/techPrerequisites 与 pathTypes：
        #  - 零件的「科技需求」引用科技节点；
        #  - 载具的「可通行路径类型」引用路径类型。
        # 不带过来会让配比/科技需求/通行性落不了地（导入时会被明确提示为 problem）。
        "resources": [
            "fuels",
            "materials",
            "techNodes",
            "techPrerequisites",
            "parts",
            "partMaterials",
            "partTechRequirements",
            "products",
            "productParts",
            "productTechRequirements",
            "productionLines",
            "infrastructures",
            "vehicles",
            "vehiclePathTypes",
            "warehouses",
            "pathTypes",
        ],
    },
    "geo": {
        "label": "⑤ 地理与物流",
        "resources": [
            "regions",
            "mapNodeTypes",
            "pathTypes",
            "mapNodes",
            "mapEdges",
        ],
    },
    "tech": {
        "label": "⑥ 科技与需求",
        "resources": ["techNodes", "techPrerequisites", "consumerDemands"],
    },
    "market": {
        "label": "⑦ 市场与规则",
        "resources": [
            "contractTypes",
            "contractInstances",
            "stocks",
            "stockFundsAccounts",
            "overviewCards",
            "messages",
        ],
    },
    "access": {
        "label": "⑧ 账号与权限",
        "resources": ["users"],
    },
}

SCOPE_ALL = "all"

# 全部资源顺序（依赖优先：被引用的先导入）
#   techNodes 必须在 parts/products 之前（科技需求引用它）
#   materials 必须在 parts 之前（配比引用它）
#   parts 必须在 products 之前（产品配比引用它）
#   pathTypes 必须在 vehicles 之前（载具可通行路径引用它）
#   mapNodeTypes 必须在 mapNodes 之前；mapNodes 必须在 mapEdges 之前
#   regions 必须在 mapNodes 之前（节点按名称记录区域，无外键，但仍先建便于对照）
IMPORT_ORDER: list[str] = [
    # 全局库
    "industryTypes",
    "industryFields",
    "contractTypes",
    # 比赛自身配置
    "competitionMeta",
    "fiscalYears",
    "stockConfig",
    "regions",
    # 公司
    "companies",
    "companyFieldValues",
    # 地理
    "mapNodeTypes",
    "pathTypes",
    "mapNodes",
    "mapEdges",
    # 物资与产能
    "fuels",
    "materials",
    "techNodes",
    "infrastructures",
    "productionLines",
    "warehouses",
    "parts",
    "partMaterials",
    "partTechRequirements",
    "products",
    "productParts",
    "productTechRequirements",
    "vehicles",
    "vehiclePathTypes",
    # 科技与需求
    "techPrerequisites",
    "consumerDemands",
    # 市场
    "stocks",
    "stockFundsAccounts",
    "contractInstances",
    "overviewCards",
    "messages",
    # 账号
    "users",
]

# 全局资源（不属于任何比赛，跨比赛共享）
GLOBAL_RESOURCES = {"industryTypes", "industryFields", "contractTypes"}

# 资源中文名（导出文件与导入结果里展示）
RESOURCE_LABELS: dict[str, str] = {
    "competitionMeta": "比赛名称与状态",
    "fiscalYears": "财年",
    "stockConfig": "股票系统参数",
    "industryTypes": "产业类型（全局）",
    "industryFields": "产业字段（全局）",
    "companies": "公司",
    "companyFieldValues": "公司字段初始值",
    "regions": "区域",
    "mapNodeTypes": "地图节点类型",
    "pathTypes": "路径类型",
    "mapNodes": "地图节点",
    "mapEdges": "地图连线",
    "fuels": "燃料",
    "materials": "原料",
    "techNodes": "科技节点",
    "techPrerequisites": "科技前置依赖",
    "infrastructures": "基建",
    "productionLines": "生产线",
    "warehouses": "仓库",
    "parts": "零件",
    "partMaterials": "零件-原料配比",
    "partTechRequirements": "零件-科技需求",
    "products": "产品",
    "productParts": "产品-零件配比",
    "productTechRequirements": "产品-科技需求",
    "vehicles": "载具",
    "vehiclePathTypes": "载具-可通行路径类型",
    "consumerDemands": "消费者需求",
    "stocks": "股票",
    "stockFundsAccounts": "资金账户",
    "contractInstances": "合同实例",
    "overviewCards": "区域总览卡片",
    "messages": "比赛内消息",
    "users": "参赛账号与范围",
}


def is_valid_scope(scope: str) -> bool:
    return scope == SCOPE_ALL or scope in SCOPES


def resources_of_scope(scope: str) -> list[str]:
    """某 scope 包含的资源（按 IMPORT_ORDER 的依赖顺序返回）。"""
    if scope == SCOPE_ALL:
        wanted = set(IMPORT_ORDER)
    else:
        wanted = set(SCOPES[scope]["resources"])
    return [r for r in IMPORT_ORDER if r in wanted]


def scope_label(scope: str) -> str:
    if scope == SCOPE_ALL:
        return "全部准备数据"
    cat = CATEGORY_BY_KEY.get(scope)
    return SCOPES[scope]["label"] if scope in SCOPES else (cat.title if cat else scope)


def scope_options() -> list[dict[str, str]]:
    """给前端渲染下拉用：全部分组 + 全部。"""
    out = [{"value": SCOPE_ALL, "label": scope_label(SCOPE_ALL), "description": "导出/导入全部准备数据"}]
    for cat in CATEGORIES:
        if cat.key not in SCOPES:
            continue
        out.append(
            {
                "value": cat.key,
                "label": SCOPES[cat.key]["label"],
                "description": cat.description,
            }
        )
    return out


# ==================== 小工具 ====================

def _text(value: Any) -> Any:
    """Decimal / datetime 等 → 可 JSON 序列化的值。"""
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.isoformat()
    from decimal import Decimal

    if isinstance(value, Decimal):
        # 用字符串保精度（float 会丢大数精度：本项目价格字段 max_digits=60）
        return str(value)
    return value


def _json_obj(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _json_list(raw: Any) -> list:
    v = _json_obj(raw, [])
    return v if isinstance(v, list) else []


def _json_dict(raw: Any) -> dict:
    v = _json_obj(raw, {})
    return v if isinstance(v, dict) else {}


def _row(**kwargs: Any) -> dict:
    """构造导出行：剔除 None 以减少体积（导入侧一律用 .get 取值）。"""
    return {k: _text(v) for k, v in kwargs.items() if v is not None}


# ==================== ID 映射（导入用） ====================
class IdMap:
    """导入期间的旧 id → 新 id 映射表，按资源类型隔离。"""

    def __init__(self) -> None:
        self._maps: dict[str, dict[Any, Any]] = {}
        # 追加模式下「被保留未改动」的记录集合：resource -> {new_id}
        self._kept: dict[str, set] = {}

    def put(self, resource: str, old_id: Any, new_id: Any) -> None:
        if old_id is None:
            return
        self._maps.setdefault(resource, {})[old_id] = new_id

    def get(self, resource: str, old_id: Any) -> Any:
        if old_id is None:
            return None
        return self._maps.get(resource, {}).get(old_id)

    def has(self, resource: str, old_id: Any) -> bool:
        return old_id in self._maps.get(resource, {})

    def mark_kept(self, resource: str, new_id: Any) -> None:
        """记录「该记录在追加模式下被保留未改动」。"""
        if new_id is not None:
            self._kept.setdefault(resource, set()).add(new_id)

    def kept(self, resource: str, old_id: Any) -> bool:
        """按归档里的旧 id 查询其对应记录是否被保留。"""
        if old_id is None:
            return False
        new_id = self.get(resource, old_id)
        if new_id is None:
            return False
        return new_id in self._kept.get(resource, set())


# ==================== 跨分组引用的兜底解析 ====================
# 场景：用户只导入「物资与产能」分组（其中载具引用燃料、零件配比引用原料），
# 但被引用对象属于别的分组、当时并未一起导入；或目标比赛已由更早的分组导入过这些对象。
# 此时 id 映射表里没有记录，若直接判为缺失会丢引用。
# 因此对每类被引用资源定义「按自然键在目标比赛里找已有记录」的兜底解析：
#   resource -> (模型路径, 用于回填的字段名, 名称字段名)
_REF_FALLBACKS: dict[str, tuple[str, str, str]] = {
    "companies": ("companies.Company", "company_id", "name"),
    "fuels": ("fuels.Fuel", "fuel_id", "name"),
    "materials": ("materials.Material", "material_id", "name"),
    "parts": ("parts.Part", "part_id", "name"),
    "products": ("products.Product", "product_id", "name"),
    "techNodes": ("tech_tree.TechNode", "tech_node_id", "name"),
    "pathTypes": ("maps.PathType", "path_type_id", "name"),
    "mapNodeTypes": ("maps.MapNodeType", "node_type_id", "name"),
    "mapNodes": ("maps.MapNode", "from_node_id", "name"),
    "regions": ("regions.Region", "region_id", "name"),
    "vehicles": ("vehicles.Vehicle", "vehicle_id", "name"),
    "stocks": ("stock.Stock", "stock_id", "code"),
}


def _ref_name_of(resource: str, row: dict, lookups: dict) -> str | None:
    """从行数据里推断被引用对象的自然键名称。

    lookups：{资源: 该行的哪个字段持有自然键名}，由各导入函数按需传入。
    例：地图连线用 pathTypeName、零件配比用 materialName（若导出侧提供）。
    """
    key = lookups.get(resource)
    if key and row.get(key):
        return str(row[key]).strip() or None
    return None


class RefResolver:
    """把「归档里的旧 id」解析成目标库里的真实 id，带跨分组兜底。"""

    def __init__(self, ctx: "ImportContext") -> None:
        self.ctx = ctx

    def resolve(
        self,
        resource: str,
        old_id: Any,
        *,
        name: str | None = None,
        row: dict | None = None,
    ) -> Any:
        """优先用 id 映射；查不到再按名称在目标比赛里查找已有记录。"""
        mapped = self.ctx.ids.get(resource, old_id)
        if mapped is not None:
            return mapped
        if old_id is None and not name:
            return None

        spec = _REF_FALLBACKS.get(resource)
        if spec is None:
            return None
        model_path, _field, name_field = spec
        from django.apps import apps as django_apps

        model = django_apps.get_model(model_path)

        # 名称优先：跨分组导入时名称是唯一可靠的线索
        if name:
            qs = model.objects.filter(**{name_field: name})
            try:
                qs = qs.filter(competition_id=self.ctx.competition_id)
            except Exception:  # noqa: BLE001 - 模型无 competition 字段
                pass
            found = qs.values_list("id", flat=True).first()
            if found is not None:
                self.ctx.ids.put(resource, old_id, found)
                return found

        # 退一步：old_id 恰好就是目标比赛的 id（例如重复导入同一份数据）
        if old_id is not None:
            qs = model.objects.filter(pk=old_id)
            try:
                qs = qs.filter(competition_id=self.ctx.competition_id)
            except Exception:  # noqa: BLE001
                pass
            if qs.exists():
                self.ctx.ids.put(resource, old_id, old_id)
                return old_id
        return None

    def name_from_row(self, resource: str, row: dict, *keys: str) -> str | None:
        """按候选字段名从行里取自然键名称。"""
        for k in keys:
            v = row.get(k)
            if v:
                return str(v).strip() or None
        return None


# ==================== 导入策略 ====================

# 追加：只补目标比赛缺的数据，已存在的同键记录原样保留（含其关联数据）
MODE_APPEND = "append"
# 覆盖：已存在的同键记录按归档内容更新（保留主键与关联关系，不做删除）
MODE_OVERWRITE = "overwrite"
IMPORT_MODES = (MODE_APPEND, MODE_OVERWRITE)
MODE_LABELS = {MODE_APPEND: "追加（已存在的保留不动）", MODE_OVERWRITE: "覆盖（已存在的按归档更新）"}


class ImportContext:
    """导入上下文：目标比赛、导入策略、ID 映射、统计与问题收集。"""

    def __init__(
        self,
        competition_id: int,
        *,
        dry_run: bool,
        allow_non_empty: bool,
        mode: str = MODE_APPEND,
        only_resources: set[str] | None = None,
        user=None,
    ) -> None:
        self.competition_id = competition_id
        self.dry_run = dry_run
        self.allow_non_empty = allow_non_empty
        self.mode = mode if mode in IMPORT_MODES else MODE_APPEND
        # 仅导入这些资源；None = 归档里有什么就导什么
        self.only_resources = only_resources
        self.user = user
        self.ids = IdMap()
        # 引用解析器（含跨分组按名兜底），供各导入函数解析外键
        self.ref = RefResolver(self)
        # 归档里「旧公司 id → 公司名」，供账号公司范围按名兜底映射（见 _imp_users）
        self.old_company_names: dict[Any, str] = {}
        # resource -> {"created": n, "updated": n, "skipped": n, "kept": n}
        self.stats: dict[str, dict[str, int]] = {}
        # problems：需要用户处理或知晓的风险（影响导入完整性）
        self.problems: list[str] = []
        # notes：中性提示（如「已存在故只同步范围」这类幂等行为说明）
        self.notes: list[str] = []

    # ---------- 策略查询 ----------

    @property
    def is_overwrite(self) -> bool:
        return self.mode == MODE_OVERWRITE

    def wants(self, resource: str) -> bool:
        """该资源是否在本次导入范围内。"""
        return self.only_resources is None or resource in self.only_resources

    def keep_existing(self, resource: str, label: str) -> bool:
        """追加模式下遇到已存在记录：保留不动并记一条 kept。

        返回 True 表示调用方应直接跳过该记录的写入（含其关联数据）。
        """
        if self.is_overwrite:
            return False
        self.bump(resource, "kept")
        self.note(f"{label}：追加模式下已存在，保留原数据未改动")
        return True

    def keep_existing_id(self, resource: str, old_id: Any, new_id: Any, label: str) -> bool:
        """同 keep_existing，但额外登记「该记录被保留」以便其子资源一并跳过。"""
        if not self.keep_existing(resource, label):
            return False
        self.ids.mark_kept(resource, new_id)
        return True

    # ---------- 统计 ----------

    def bump(self, resource: str, field: str, n: int = 1) -> None:
        st = self.stats.setdefault(
            resource, {"created": 0, "updated": 0, "skipped": 0, "kept": 0}
        )
        st[field] = st.get(field, 0) + n

    def problem(self, msg: str) -> None:
        if len(self.problems) < 200:
            self.problems.append(msg)

    def note(self, msg: str) -> None:
        if len(self.notes) < 200:
            self.notes.append(msg)

    def result(self) -> dict:
        rows = []
        for res, st in self.stats.items():
            if not any(st.values()):
                continue
            rows.append(
                {
                    "resource": res,
                    "label": RESOURCE_LABELS.get(res, res),
                    "created": st.get("created", 0),
                    "updated": st.get("updated", 0),
                    "skipped": st.get("skipped", 0),
                    "kept": st.get("kept", 0),
                }
            )
        rows.sort(key=lambda r: IMPORT_ORDER.index(r["resource"]) if r["resource"] in IMPORT_ORDER else 999)
        return {
            "created": sum(r["created"] for r in rows),
            "updated": sum(r["updated"] for r in rows),
            "skipped": sum(r["skipped"] for r in rows),
            "kept": sum(r["kept"] for r in rows),
            "resources": rows,
            "problems": self.problems,
            "notes": self.notes,
            "mode": self.mode,
            "modeLabel": MODE_LABELS.get(self.mode, self.mode),
        }


# ==================== 导出：逐资源取数 ====================
# 每个导出函数返回行列表；行内一律用「旧 id」表达引用（如 materialId / fuelId）。

_ExportFn = Callable[[int], list[dict]]
_ImportFn = Callable[[list[dict], ImportContext], None]


def _exp_competition_meta(cid: int) -> list[dict]:
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=cid).first()
    if comp is None:
        return []
    return [
        _row(
            _id=comp.id,
            name=comp.name,
            status=comp.status,
            mapBackground=_json_dict(comp.map_background) or None,
        )
    ]


def _exp_fiscal_years(cid: int) -> list[dict]:
    from apps.competitions.models import FiscalYear

    return [
        _row(_id=fy.id, year=fy.year, status=fy.status)
        for fy in FiscalYear.objects.filter(competition_id=cid).order_by("year")
    ]


def _exp_stock_config(cid: int) -> list[dict]:
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=cid).first()
    if comp is None:
        return []
    cfg = comp.stock_config if isinstance(comp.stock_config, dict) else None
    return [_row(_id=comp.id, custom=cfg or {}, isDefault=cfg is None)]


def _exp_industry_types(cid: int) -> list[dict]:
    from apps.industry_types.models import IndustryType

    return [
        _row(_id=t.id, code=t.code, name=t.name, description=t.description, icon=t.icon)
        for t in IndustryType.objects.all().order_by("code")
    ]


def _exp_industry_fields(cid: int) -> list[dict]:
    from apps.industry_types.models import IndustryField

    return [
        _row(
            _id=f.id,
            industryTypeCode=f.industry_type.code if f.industry_type else None,
            name=f.name,
            fieldKey=f.field_key,
            fieldType=f.field_type,
            config=_json_dict(f.config),
            defaultValue=f.default_value,
            isCalculated=f.is_calculated,
            calcGraph=_json_obj(f.calc_graph),
            sortOrder=f.sort_order,
            visible=f.visible,
            timerEnabled=f.timer_enabled,
            timerTrigger=f.timer_trigger,
            timerValue=f.timer_value,
        )
        for f in IndustryField.objects.select_related("industry_type").order_by(
            "industry_type__code", "sort_order", "id"
        )
    ]


def _exp_companies(cid: int) -> list[dict]:
    from apps.companies.models import Company

    return [
        _row(
            _id=c.id,
            name=c.name,
            industryTypeCode=c.industry_type.code if c.industry_type else None,
            regionName=c.region.name if c.region else None,
            status=c.status,
        )
        for c in Company.objects.filter(competition_id=cid)
        .select_related("industry_type", "region")
        .order_by("id")
    ]


def _exp_company_field_values(cid: int) -> list[dict]:
    from apps.companies.models import CompanyFieldValue

    return [
        _row(
            _id=v.id,
            companyId=v.company_id,
            # companyName：跨分组导入（company 分组未一起导入）时按名兜底解析
            companyName=v.company.name if v.company else None,
            industryTypeCode=v.industry_field.industry_type.code if v.industry_field else None,
            fieldKey=v.industry_field.field_key if v.industry_field else None,
            value=v.value,
            version=v.version,
        )
        for v in CompanyFieldValue.objects.filter(company__competition_id=cid)
        .select_related("company", "industry_field", "industry_field__industry_type")
        .order_by("id")
    ]


def _exp_regions(cid: int) -> list[dict]:
    from apps.regions.models import Region

    return [
        _row(_id=r.id, name=r.name, description=r.description, overviewCards=_json_list(r.overview_cards))
        for r in Region.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_map_node_types(cid: int) -> list[dict]:
    from apps.maps.models import MapNodeType

    return [
        _row(_id=t.id, name=t.name, description=t.description, color=t.color)
        for t in MapNodeType.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_path_types(cid: int) -> list[dict]:
    from apps.maps.models import PathType

    return [
        _row(_id=t.id, name=t.name, description=t.description, color=t.color)
        for t in PathType.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_map_nodes(cid: int) -> list[dict]:
    from apps.maps.models import MapNode

    return [
        _row(
            _id=n.id,
            name=n.name,
            region=n.region,
            nodeTypeName=n.node_type.name if n.node_type else None,
            x=n.x,
            y=n.y,
        )
        for n in MapNode.objects.filter(competition_id=cid).select_related("node_type").order_by("id")
    ]


def _exp_map_edges(cid: int) -> list[dict]:
    from apps.maps.models import MapEdge

    return [
        _row(
            _id=e.id,
            fromNodeId=e.from_node_id,
            fromNodeName=e.from_node.name if e.from_node else None,
            toNodeId=e.to_node_id,
            toNodeName=e.to_node.name if e.to_node else None,
            distance=e.distance,
            pathTypeId=e.path_type_id,
            pathTypeName=e.path_type.name if e.path_type else None,
        )
        for e in MapEdge.objects.filter(competition_id=cid)
        .select_related("from_node", "to_node", "path_type")
        .order_by("id")
    ]


def _exp_fuels(cid: int) -> list[dict]:
    from apps.fuels.models import Fuel

    return [
        _row(_id=f.id, name=f.name, pricePerLiter=f.price_per_liter)
        for f in Fuel.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_materials(cid: int) -> list[dict]:
    from apps.maps.models import MapNode
    from apps.materials.models import Material

    # 地点价库内以「地图节点 id」为键；导出时额外给出「节点名 → 价格」，
    # 使「物资与产能」分组能脱离「地理与物流」分组独立导入（id 换比赛会变，名称不会）。
    node_names = {
        n["id"]: n["name"] for n in MapNode.objects.filter(competition_id=cid).values("id", "name")
    }
    rows: list[dict] = []
    for m in Material.objects.filter(competition_id=cid).order_by("id"):
        prices = _json_dict(m.node_prices)
        prices_by_name = {
            node_names[int(k)]: v for k, v in prices.items() if str(k).isdigit() and int(k) in node_names
        }
        rows.append(
            _row(
                _id=m.id,
                name=m.name,
                origin=m.origin,
                carbonEmissionCoefficient=m.carbon_emission_coefficient,
                nodePrices=prices,
                nodePricesByName=prices_by_name,
                type=m.type,
            )
        )
    return rows


def _exp_tech_nodes(cid: int) -> list[dict]:
    from apps.tech_tree.models import TechNode

    return [
        _row(_id=t.id, name=t.name, description=t.description, tier=t.tier, researchCost=t.research_cost)
        for t in TechNode.objects.filter(competition_id=cid).order_by("tier", "id")
    ]


def _exp_tech_prerequisites(cid: int) -> list[dict]:
    from apps.tech_tree.models import TechPrerequisite

    return [
        _row(_id=p.id, nodeId=p.node_id, prerequisiteId=p.prerequisite_id)
        for p in TechPrerequisite.objects.filter(node__competition_id=cid).order_by("id")
    ]


def _exp_infrastructures(cid: int) -> list[dict]:
    from apps.infrastructures.models import Infrastructure

    return [
        _row(
            _id=i.id,
            name=i.name,
            footprint=i.footprint,
            price=i.price,
            activationPrice=i.activation_price,
            employmentRateBonus=i.employment_rate_bonus,
            populationBonus=i.population_bonus,
            highQualityPopulationBonus=i.high_quality_population_bonus,
            happinessIndexBonus=i.happiness_index_bonus,
            perCapitaIncomeBonus=i.per_capita_income_bonus,
            carbonReductionBonus=i.carbon_reduction_bonus,
        )
        for i in Infrastructure.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_production_lines(cid: int) -> list[dict]:
    from apps.production_lines.models import ProductionLine

    return [
        _row(
            _id=p.id,
            name=p.name,
            price=p.price,
            laborCount=p.labor_count,
            maxPerYear=p.max_per_year,
        )
        for p in ProductionLine.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_warehouses(cid: int) -> list[dict]:
    from apps.warehouses.models import Warehouse

    return [
        _row(_id=w.id, name=w.name, type=w.type, capacity=w.capacity, price=w.price)
        for w in Warehouse.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_parts(cid: int) -> list[dict]:
    from apps.parts.models import Part

    return [
        _row(_id=p.id, name=p.name) for p in Part.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_part_materials(cid: int) -> list[dict]:
    from apps.parts.models import PartMaterial

    return [
        _row(
            _id=pm.id,
            partId=pm.part_id,
            partName=pm.part.name if pm.part else None,
            materialId=pm.material_id,
            materialName=pm.material.name if pm.material else None,
            ratio=pm.ratio,
        )
        for pm in PartMaterial.objects.filter(part__competition_id=cid)
        .select_related("part", "material")
        .order_by("id")
    ]


def _exp_part_tech_requirements(cid: int) -> list[dict]:
    from apps.parts.models import PartTechRequirement

    return [
        _row(
            _id=r.id,
            partId=r.part_id,
            partName=r.part.name if r.part else None,
            techNodeId=r.tech_node_id,
            techNodeName=r.tech_node.name if r.tech_node else None,
        )
        for r in PartTechRequirement.objects.filter(part__competition_id=cid)
        .select_related("part", "tech_node")
        .order_by("id")
    ]


def _exp_products(cid: int) -> list[dict]:
    from apps.products.models import Product

    return [
        _row(_id=p.id, name=p.name) for p in Product.objects.filter(competition_id=cid).order_by("id")
    ]


def _exp_product_parts(cid: int) -> list[dict]:
    from apps.products.models import ProductPart

    return [
        _row(
            _id=pp.id,
            productId=pp.product_id,
            productName=pp.product.name if pp.product else None,
            partId=pp.part_id,
            partName=pp.part.name if pp.part else None,
            ratio=pp.ratio,
        )
        for pp in ProductPart.objects.filter(product__competition_id=cid)
        .select_related("product", "part")
        .order_by("id")
    ]


def _exp_product_tech_requirements(cid: int) -> list[dict]:
    from apps.products.models import ProductTechRequirement

    return [
        _row(
            _id=r.id,
            productId=r.product_id,
            productName=r.product.name if r.product else None,
            techNodeId=r.tech_node_id,
            techNodeName=r.tech_node.name if r.tech_node else None,
        )
        for r in ProductTechRequirement.objects.filter(product__competition_id=cid)
        .select_related("product", "tech_node")
        .order_by("id")
    ]


def _exp_vehicles(cid: int) -> list[dict]:
    from apps.vehicles.models import Vehicle

    return [
        _row(
            _id=v.id,
            name=v.name,
            fuelId=v.fuel_id,
            fuelName=v.fuel.name if v.fuel else None,
            fuelConsumptionPerKm=v.fuel_consumption_per_km,
            maxCargo=v.max_cargo,
            price=v.price,
            carbonEmission=v.carbon_emission,
        )
        for v in Vehicle.objects.filter(competition_id=cid).select_related("fuel").order_by("id")
    ]


def _exp_vehicle_path_types(cid: int) -> list[dict]:
    from apps.vehicles.models import VehiclePathType

    return [
        _row(
            _id=v.id,
            vehicleId=v.vehicle_id,
            vehicleName=v.vehicle.name if v.vehicle else None,
            pathTypeId=v.path_type_id,
            pathTypeName=v.path_type.name if v.path_type else None,
        )
        for v in VehiclePathType.objects.filter(vehicle__competition_id=cid)
        .select_related("vehicle", "path_type")
        .order_by("id")
    ]


def _exp_consumer_demands(cid: int) -> list[dict]:
    from apps.consumer_demands.models import ConsumerDemand

    return [
        _row(
            _id=d.id,
            region=d.region,
            productType=d.product_type,
            productId=d.product_id,
            # productName 即 product_type（导出侧冗余存储产品名，作为跨分组兜底线索）
            productName=d.product.name if d.product else (d.product_type or None),
            quantity=d.quantity,
            note=d.note,
        )
        for d in ConsumerDemand.objects.filter(competition_id=cid).select_related("product").order_by("id")
    ]


def _exp_contract_types(cid: int) -> list[dict]:
    from apps.contracts.models import ContractType

    return [
        _row(
            _id=t.id,
            key=t.key,
            name=t.name,
            description=t.description,
            partyRoles=_json_list(t.party_roles),
            inputSchema=_json_list(t.input_schema),
            effects=_json_list(t.effects),
            conditions=_json_list(t.conditions),
            graph=_json_obj(t.graph),
            schemaVersion=t.schema_version,
            enabled=t.enabled,
        )
        for t in ContractType.objects.all().order_by("id")
    ]


def _exp_contract_instances(cid: int) -> list[dict]:
    from apps.companies.models import Company
    from apps.contracts.models import Contract

    # 参与方公司名一并导出：跨分组导入（company 分组未一起导入）时按名兜底解析
    name_by_id = {
        c["id"]: c["name"]
        for c in Company.objects.filter(competition_id=cid).values("id", "name")
    }
    rows: list[dict] = []
    for c in (
        Contract.objects.filter(competition_id=cid).select_related("contract_type").order_by("id")
    ):
        parties = _json_list(c.parties)
        for p in parties:
            if isinstance(p, dict) and p.get("companyId") is not None:
                p["companyName"] = name_by_id.get(p["companyId"])
        rows.append(
            _row(
                _id=c.id,
                contractTypeId=c.contract_type_id,
                contractTypeKey=c.contract_type.key if c.contract_type else None,
                name=c.name,
                status=c.status,
                parties=parties,
                inputs=_json_dict(c.inputs),
            )
        )
    return rows

def _exp_stocks(cid: int) -> list[dict]:
    from apps.stock.models import Stock

    return [
        _row(
            _id=s.id,
            code=s.code,
            name=s.name,
            companyId=s.company_id,
            companyName=s.company.name if s.company else None,
            totalShares=s.total_shares,
            initNetProfit=s.init_net_profit,
            initPrice=s.init_price,
            currentPrice=s.current_price,
            industryPe=s.industry_pe,
            currentCarbon=s.current_carbon,
            industryAvgCarbon=s.industry_avg_carbon,
            happiness=s.happiness,
            round=s.round,
            carbonFieldRef=s.carbon_field_ref,
            happinessFieldRef=s.happiness_field_ref,
            industryAvgCarbonRefs=s.industry_avg_carbon_refs,
            pbCompanyId=s.pb_company_id,
            pbFieldId=s.pb_field_id,
            pbRandom=s.pb_random,
        )
        for s in Stock.objects.filter(competition_id=cid).select_related("company").order_by("code")
    ]


def _exp_stock_funds_accounts(cid: int) -> list[dict]:
    from apps.companies.models import Company
    from apps.stock.models import StockFundsAccount
    from apps.users.models import User

    rows: list[dict] = []
    for a in StockFundsAccount.objects.filter(competition_id=cid).order_by("id"):
        owner_name = None
        if a.owner_type == "COMPANY" and a.company_id:
            owner_name = Company.objects.filter(pk=a.company_id).values_list("name", flat=True).first()
        elif a.owner_type == "USER" and a.user_id:
            owner_name = User.objects.filter(pk=a.user_id).values_list("username", flat=True).first()
        rows.append(
            _row(
                _id=a.id,
                name=a.name,
                ownerType=a.owner_type,
                companyId=a.company_id,
                companyName=owner_name if a.owner_type == "COMPANY" else None,
                userId=a.user_id,
                username=owner_name if a.owner_type == "USER" else None,
                cashBalance=a.cash_balance,
                bindFieldId=a.bind_field_id,
            )
        )
    return rows


def _exp_overview_cards(cid: int) -> list[dict]:
    """区域总览卡片以（区域名 → 卡片数组）表达，导入时按区域名写回。"""
    from apps.regions.models import Region

    out: list[dict] = []
    for r in Region.objects.filter(competition_id=cid).order_by("id"):
        cards = _json_list(r.overview_cards)
        if cards:
            out.append(_row(_id=r.id, regionName=r.name, cards=cards))
    return out


def _exp_messages(cid: int) -> list[dict]:
    from apps.messages.models import Message

    return [
        _row(
            _id=m.id,
            title=m.title,
            content=m.content,
            senderUsername=m.sender.username if m.sender else None,
            targetsAll=m.targets_all,
            targetUserIds=_json_list(m.target_user_ids),
        )
        for m in Message.objects.filter(competition_id=cid).select_related("sender").order_by("id")
    ]


def _exp_users(cid: int) -> list[dict]:
    """账号导出：**不含密码**（bcrypt 哈希不跨比赛搬运），导入后需重置密码。

    公司范围除 id 外同时给出「同下标的公司名」，使「账号与权限」分组可单独导入
    （目标比赛按同名公司兜底解析范围）。
    """
    from apps.companies.models import Company
    from apps.users.models import User

    name_by_id = {
        c["id"]: c["name"]
        for c in Company.objects.filter(competition_id=cid).values("id", "name")
    }

    def _names(ids: list) -> list:
        return [name_by_id.get(i, "") for i in ids]

    rows: list[dict] = []
    for u in User.objects.filter(competition_id=cid).order_by("username"):
        company_scopes = _json_list(u.company_scopes)
        view_scopes = _json_list(u.view_company_scopes)
        contract_scopes = _json_list(u.contract_view_company_scopes)
        stock_scopes = _json_list(u.stock_company_scopes)
        rows.append(
            _row(
                _id=u.id,
                username=u.username,
                displayName=u.display_name,
                role=u.role,
                isActive=u.is_active,
                permissions=_json_list(u.permissions),
                companyScopes=company_scopes,
                companyScopeNames=_names(company_scopes),
                viewCompanyScopes=view_scopes,
                viewCompanyScopeNames=_names(view_scopes),
                contractViewCompanyScopes=contract_scopes,
                contractViewCompanyScopeNames=_names(contract_scopes),
                stockCompanyScopes=stock_scopes,
                stockCompanyScopeNames=_names(stock_scopes),
            )
        )
    return rows


_EXPORTERS: dict[str, _ExportFn] = {
    "competitionMeta": _exp_competition_meta,
    "fiscalYears": _exp_fiscal_years,
    "stockConfig": _exp_stock_config,
    "industryTypes": _exp_industry_types,
    "industryFields": _exp_industry_fields,
    "companies": _exp_companies,
    "companyFieldValues": _exp_company_field_values,
    "regions": _exp_regions,
    "mapNodeTypes": _exp_map_node_types,
    "pathTypes": _exp_path_types,
    "mapNodes": _exp_map_nodes,
    "mapEdges": _exp_map_edges,
    "fuels": _exp_fuels,
    "materials": _exp_materials,
    "techNodes": _exp_tech_nodes,
    "techPrerequisites": _exp_tech_prerequisites,
    "infrastructures": _exp_infrastructures,
    "productionLines": _exp_production_lines,
    "warehouses": _exp_warehouses,
    "parts": _exp_parts,
    "partMaterials": _exp_part_materials,
    "partTechRequirements": _exp_part_tech_requirements,
    "products": _exp_products,
    "productParts": _exp_product_parts,
    "productTechRequirements": _exp_product_tech_requirements,
    "vehicles": _exp_vehicles,
    "vehiclePathTypes": _exp_vehicle_path_types,
    "consumerDemands": _exp_consumer_demands,
    "contractTypes": _exp_contract_types,
    "contractInstances": _exp_contract_instances,
    "stocks": _exp_stocks,
    "stockFundsAccounts": _exp_stock_funds_accounts,
    "overviewCards": _exp_overview_cards,
    "messages": _exp_messages,
    "users": _exp_users,
}


def build_export(cid: int, scope: str) -> dict:
    """构造导出数据（不含 Markdown 报告）。"""
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=cid).first()
    resources: dict[str, Any] = {}
    for res in resources_of_scope(scope):
        fn = _EXPORTERS.get(res)
        if fn is None:
            continue
        try:
            rows = fn(cid)
        except Exception as e:  # noqa: BLE001 - 单资源失败不影响整包导出
            resources[res] = {
                "label": RESOURCE_LABELS.get(res, res),
                "count": 0,
                "rows": [],
                "error": f"{type(e).__name__}: {e}",
            }
            continue
        resources[res] = {
            "label": RESOURCE_LABELS.get(res, res),
            "count": len(rows),
            "rows": rows[:_DETAIL_LIMIT],
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generator": GENERATOR,
        "exportedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope,
        "scopeLabel": scope_label(scope),
        "sourceCompetition": {"id": comp.id, "name": comp.name} if comp else None,
        "resources": resources,
    }


# ==================== 导入：逐资源写入 ====================
# 约定：
# - 行内以旧 id 表示引用；用 ctx.ids 映射到新主键。
# - 依赖缺失 → ctx.problem 并跳过该行（计 skipped），不中断整批。
# - 比赛级资源按「同比赛内名称」去重（已存在则更新），全局资源按 code/key 去重。

# 需要用户显式重置密码的账号（导出不含密码）
_IMPORT_RESET_PASSWORD_NOTE = "（密码未导出，导入后需由超管重置）"


def _imp_competition_meta(rows: list[dict], ctx: ImportContext) -> None:
    """比赛名称/状态/背景图：导入时只在目标比赛上补空缺，不覆盖已有名称。"""
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=ctx.competition_id).first()
    if comp is None or not rows:
        return
    src = rows[0]
    changed = []
    # 名称：目标为空占位名（无公司无数据的新比赛常为默认名）时不强行改名，仅记录提示
    src_name = (src.get("name") or "").strip()
    if src_name and comp.name != src_name:
        ctx.note(
            f"源比赛名称为「{src_name}」，目标比赛名称为「{comp.name}」；为避免重名冲突未自动改名，"
            "如需一致请手动修改比赛名称。"
        )
    if src.get("status") and comp.status != src["status"]:
        comp.status = src["status"]
        changed.append("status")
    bg = src.get("mapBackground")
    if bg and not comp.map_background:
        comp.map_background = json.dumps(bg, ensure_ascii=False)
        changed.append("map_background")
    if changed:
        comp.save(update_fields=changed + ["updated_at"])
        ctx.bump("competitionMeta", "updated")
    else:
        ctx.bump("competitionMeta", "skipped")


def _imp_fiscal_years(rows: list[dict], ctx: ImportContext) -> None:
    from apps.competitions.models import FiscalYear

    for row in rows:
        year = row.get("year")
        if year is None:
            ctx.bump("fiscalYears", "skipped")
            continue
        obj, created = FiscalYear.objects.get_or_create(
            competition_id=ctx.competition_id,
            year=year,
            defaults={"status": row.get("status") or "ACTIVE"},
        )
        if created:
            ctx.bump("fiscalYears", "created")
        else:
            new_status = row.get("status")
            if new_status and obj.status != new_status:
                obj.status = new_status
                obj.save(update_fields=["status", "updated_at"])
                ctx.bump("fiscalYears", "updated")
            else:
                ctx.bump("fiscalYears", "skipped")
        ctx.ids.put("fiscalYears", row.get("_id"), obj.id)


def _imp_stock_config(rows: list[dict], ctx: ImportContext) -> None:
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=ctx.competition_id).first()
    if comp is None or not rows:
        return
    src = rows[0]
    if src.get("isDefault"):
        # 源比赛用系统默认：目标也置回默认（null）
        if comp.stock_config is not None:
            comp.stock_config = None
            comp.save(update_fields=["stock_config", "updated_at"])
            ctx.bump("stockConfig", "updated")
        else:
            ctx.bump("stockConfig", "skipped")
        return
    cfg = src.get("custom") or {}
    if not isinstance(cfg, dict) or not cfg:
        ctx.bump("stockConfig", "skipped")
        return
    comp.stock_config = cfg
    comp.save(update_fields=["stock_config", "updated_at"])
    ctx.bump("stockConfig", "updated")


def _imp_industry_types(rows: list[dict], ctx: ImportContext) -> None:
    """全局资源：按 code 复用/更新，不重复建。"""
    from apps.industry_types.models import IndustryType

    for row in rows:
        code = row.get("code")
        if code is None:
            ctx.bump("industryTypes", "skipped")
            continue
        obj, created = IndustryType.objects.get_or_create(
            code=code,
            defaults={
                "name": row.get("name") or f"产业{code}",
                "description": row.get("description"),
                "icon": row.get("icon"),
            },
        )
        if created:
            ctx.bump("industryTypes", "created")
        elif ctx.keep_existing_id("industryTypes", row.get("_id"), obj.id, f"产业类型「{obj.name}」"):
            ctx.ids.put("industryTypes", row.get("_id"), obj.id)
            ctx.ids.put("industryTypeByCode", code, obj.id)
            continue
        else:
            touched = False
            for field, key in (("name", "name"), ("description", "description"), ("icon", "icon")):
                val = row.get(key)
                if val is not None and getattr(obj, field) != val:
                    setattr(obj, field, val)
                    touched = True
            if touched:
                obj.save()
                ctx.bump("industryTypes", "updated")
            else:
                ctx.bump("industryTypes", "skipped")
        ctx.ids.put("industryTypes", row.get("_id"), obj.id)
        ctx.ids.put("industryTypeByCode", code, obj.id)


def _imp_industry_fields(rows: list[dict], ctx: ImportContext) -> None:
    """全局资源：按 (产业类型, fieldKey) 复用/更新。"""
    from apps.industry_types.models import IndustryField, IndustryType

    for row in rows:
        code = row.get("industryTypeCode")
        field_key = row.get("fieldKey")
        if code is None or not field_key:
            ctx.bump("industryFields", "skipped")
            continue
        type_id = ctx.ids.get("industryTypeByCode", code)
        if type_id is None:
            type_id = IndustryType.objects.filter(code=code).values_list("id", flat=True).first()
        if type_id is None:
            ctx.problem(f"产业字段「{field_key}」引用的产业类型 code={code} 不存在，已跳过")
            ctx.bump("industryFields", "skipped")
            continue
        payload = {
            "name": row.get("name") or field_key,
            "field_type": row.get("fieldType") or "NUMBER",
            "config": json.dumps(row.get("config") or {}, ensure_ascii=False),
            "default_value": row.get("defaultValue"),
            "is_calculated": bool(row.get("isCalculated")),
            "calc_graph": (
                json.dumps(row.get("calcGraph"), ensure_ascii=False)
                if row.get("calcGraph") is not None
                else None
            ),
            "sort_order": row.get("sortOrder") or 0,
            "visible": True if row.get("visible") is None else bool(row.get("visible")),
            "timer_enabled": bool(row.get("timerEnabled")),
            "timer_trigger": row.get("timerTrigger"),
            "timer_value": row.get("timerValue"),
        }
        obj, created = IndustryField.objects.get_or_create(
            industry_type_id=type_id, field_key=field_key, defaults=payload
        )
        if created:
            ctx.bump("industryFields", "created")
        elif ctx.keep_existing_id(
            "industryFields", row.get("_id"), obj.id, f"产业字段「{payload['name']}」"
        ):
            ctx.ids.put("industryFields", row.get("_id"), obj.id)
            ctx.ids.put("industryFieldByKey", (code, field_key), obj.id)
            continue
        else:
            for k, v in payload.items():
                setattr(obj, k, v)
            obj.save()
            ctx.bump("industryFields", "updated")
        ctx.ids.put("industryFields", row.get("_id"), obj.id)
        ctx.ids.put("industryFieldByKey", (code, field_key), obj.id)


def _imp_companies(rows: list[dict], ctx: ImportContext) -> None:
    from apps.companies.models import Company
    from apps.industry_types.models import IndustryType
    from apps.regions.models import Region

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("companies", "skipped")
            continue
        type_id = None
        code = row.get("industryTypeCode")
        if code is not None:
            type_id = ctx.ids.get("industryTypeByCode", code) or IndustryType.objects.filter(
                code=code
            ).values_list("id", flat=True).first()
        region_id = None
        region_name = row.get("regionName")
        if region_name:
            region_id = ctx.ids.get("regions", row.get("regionId")) or Region.objects.filter(
                competition_id=ctx.competition_id, name=region_name
            ).values_list("id", flat=True).first()
            if region_id is None:
                # 区域不在本包内（只导了 company 分组）：按名建一个，保证归属不丢
                region_id = Region.objects.create(competition_id=ctx.competition_id, name=region_name).id
                ctx.note(f"区域「{region_name}」不在导入包内，已按名称自动创建")
        obj, created = Company.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={
                "industry_type_id": type_id,
                "region_id": region_id,
                "status": row.get("status") or "ACTIVE",
            },
        )
        if created:
            ctx.bump("companies", "created")
        else:
            if ctx.keep_existing_id("companies", row.get("_id"), obj.id, f"公司「{name}」"):
                ctx.ids.put("companies", row.get("_id"), obj.id)
                continue
            touched = False
            if type_id is not None and obj.industry_type_id != type_id:
                obj.industry_type_id = type_id
                touched = True
            if region_id is not None and obj.region_id != region_id:
                obj.region_id = region_id
                touched = True
            st = row.get("status")
            if st and obj.status != st:
                obj.status = st
                touched = True
            if touched:
                obj.save()
                ctx.bump("companies", "updated")
            else:
                ctx.bump("companies", "skipped")
        ctx.ids.put("companies", row.get("_id"), obj.id)


def _imp_company_field_values(rows: list[dict], ctx: ImportContext) -> None:
    from apps.companies.models import Company, CompanyFieldValue
    from apps.industry_types.models import IndustryField

    for row in rows:
        company_id = ctx.ref.resolve("companies", row.get("companyId"), name=row.get("companyName"))
        if company_id is None:
            ctx.problem(f"公司字段值引用的公司 #{row.get('companyId')} 未在本包中导入，已跳过")
            ctx.bump("companyFieldValues", "skipped")
            continue
        if not Company.objects.filter(pk=company_id).exists():
            ctx.bump("companyFieldValues", "skipped")
            continue
        code = row.get("industryTypeCode")
        field_key = row.get("fieldKey")
        field_id = ctx.ids.get("industryFieldByKey", (code, field_key))
        if field_id is None:
            field_id = (
                IndustryField.objects.filter(industry_type__code=code, field_key=field_key)
                .values_list("id", flat=True)
                .first()
            )
        if field_id is None:
            ctx.problem(f"公司字段值引用的产业字段 {code}/{field_key} 不存在，已跳过")
            ctx.bump("companyFieldValues", "skipped")
            continue
        obj, created = CompanyFieldValue.objects.get_or_create(
            company_id=company_id,
            industry_field_id=field_id,
            defaults={"value": row.get("value") or "", "version": row.get("version") or 0},
        )
        if created:
            ctx.bump("companyFieldValues", "created")
        else:
            new_value = row.get("value") or ""
            if obj.value != new_value:
                obj.value = new_value
                obj.version = (obj.version or 0) + 1
                obj.save()
                ctx.bump("companyFieldValues", "updated")
            else:
                ctx.bump("companyFieldValues", "skipped")


def _imp_regions(rows: list[dict], ctx: ImportContext) -> None:
    from apps.regions.models import Region

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("regions", "skipped")
            continue
        obj, created = Region.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={"description": row.get("description")},
        )
        if created:
            ctx.bump("regions", "created")
        elif ctx.keep_existing_id("regions", row.get("_id"), obj.id, f"区域「{name}」"):
            ctx.ids.put("regions", row.get("_id"), obj.id)
            continue
        else:
            ctx.bump("regions", "skipped")
        ctx.ids.put("regions", row.get("_id"), obj.id)


# 追加模式下「父记录被保留」时需要一并跳过的子资源（否则会往既有父记录里混入新关联数据）。
# 统一在 apply_import 的导入循环里按此表过滤行，避免每个导入函数各写一遍。
_CHILD_OF: dict[str, tuple[tuple[str, str], ...]] = {
    # 子资源: ((父资源, 该行里指向父的字段名), ...)
    "partMaterials": (("parts", "partId"),),
    "partTechRequirements": (("parts", "partId"),),
    "productParts": (("products", "productId"),),
    "productTechRequirements": (("products", "productId"),),
    "vehiclePathTypes": (("vehicles", "vehicleId"),),
    "companyFieldValues": (("companies", "companyId"),),
    "techPrerequisites": (("techNodes", "nodeId"), ("techNodes", "prerequisiteId")),
    "mapEdges": (("mapNodes", "fromNodeId"), ("mapNodes", "toNodeId")),
    "contractInstances": (("contractTypes", "contractTypeId"),),
    "stockFundsAccounts": (("users", "userId"),),
    "overviewCards": (("regions", "regionId"),),
}

# 追加模式下：该资源任一「列表型父引用」命中被保留记录时，整行跳过
_CHILD_OF_LIST: dict[str, tuple[tuple[str, str], ...]] = {
    # users 的公司范围引用 companies（列表）
    "users": (
        ("companies", "companyScopes"),
        ("companies", "viewCompanyScopes"),
        ("companies", "contractViewCompanyScopes"),
        ("companies", "stockCompanyScopes"),
    ),
}


def _filter_rows_for_mode(resource: str, rows: list[dict], ctx: ImportContext) -> list[dict]:
    """追加模式下过滤掉「父记录已被保留」的子行；覆盖模式原样返回。"""
    if ctx.is_overwrite or not rows:
        return rows

    fk_specs = _CHILD_OF.get(resource, ())
    list_specs = _CHILD_OF_LIST.get(resource, ())
    if not fk_specs and not list_specs:
        return rows

    kept = 0
    out: list[dict] = []
    for row in rows:
        skip = False
        for owner_resource, field in fk_specs:
            if ctx.ids.kept(owner_resource, row.get(field)):
                skip = True
                break
        if not skip:
            for owner_resource, field in list_specs:
                parents = row.get(field)
                if isinstance(parents, list) and any(
                    ctx.ids.kept(owner_resource, p) for p in parents
                ):
                    skip = True
                    break
        if skip:
            kept += 1
        else:
            out.append(row)
    if kept:
        ctx.bump(resource, "kept", kept)
        ctx.note(
            f"{RESOURCE_LABELS.get(resource, resource)}：追加模式下有 {kept} 条因所属对象已存在而保留未改动"
        )
    return out


def _simple_lookup_import(
    resource: str,
    rows: list[dict],
    ctx: ImportContext,
    *,
    model_path: str,
    name_key: str = "name",
    extra_fields: dict[str, str] | None = None,
    label: str = "",
) -> None:
    """按「比赛 + 名称」去重的通用导入（节点类型 / 路径类型 / 燃料 / 生产线 / 仓库 / 零件 / 产品 …）。

    策略：
    - 追加（append）：已存在则整条保留不动（记 kept），不覆盖任何字段。
    - 覆盖（overwrite）：已存在则按归档内容更新全部字段。
    """
    from django.apps import apps as django_apps

    model = django_apps.get_model(model_path)
    extra_fields = extra_fields or {}
    label = label or RESOURCE_LABELS.get(resource, resource)
    for row in rows:
        name = (row.get(name_key) or "").strip()
        if not name:
            ctx.bump(resource, "skipped")
            continue
        defaults: dict[str, Any] = {}
        for field, src_key in extra_fields.items():
            val = row.get(src_key)
            if val is not None:
                defaults[field] = val
        existing = model.objects.filter(competition_id=ctx.competition_id, name=name).first()
        if existing is not None:
            ctx.ids.put(resource, row.get("_id"), existing.id)
            if ctx.keep_existing_id(resource, row.get("_id"), existing.id, f"{label}「{name}」"):
                continue
            touched = False
            for field, val in defaults.items():
                if getattr(existing, field) != val:
                    setattr(existing, field, val)
                    touched = True
            if touched:
                existing.save()
                ctx.bump(resource, "updated")
            else:
                ctx.bump(resource, "skipped")
            continue
        obj = model.objects.create(competition_id=ctx.competition_id, name=name, **defaults)
        ctx.bump(resource, "created")
        ctx.ids.put(resource, row.get("_id"), obj.id)


def _imp_map_node_types(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import(
        "mapNodeTypes",
        rows,
        ctx,
        model_path="maps.MapNodeType",
        extra_fields={"description": "description", "color": "color"},
    )


def _imp_path_types(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import(
        "pathTypes",
        rows,
        ctx,
        model_path="maps.PathType",
        extra_fields={"description": "description", "color": "color"},
    )


def _imp_map_nodes(rows: list[dict], ctx: ImportContext) -> None:
    from apps.maps.models import MapNode, MapNodeType

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("mapNodes", "skipped")
            continue
        type_name = row.get("nodeTypeName")
        type_id = ctx.ref.resolve("mapNodeTypes", row.get("nodeTypeId"), name=type_name)
        if type_id is None and type_name:
            type_id = MapNodeType.objects.filter(
                competition_id=ctx.competition_id, name=type_name
            ).values_list("id", flat=True).first()
            if type_id is None:
                type_id = MapNodeType.objects.create(
                    competition_id=ctx.competition_id, name=type_name
                ).id
                ctx.note(f"节点类型「{type_name}」不在导入包内，已自动创建")
        if type_id is None:
            ctx.problem(f"地图节点「{name}」缺少节点类型，已跳过")
            ctx.bump("mapNodes", "skipped")
            continue
        obj, created = MapNode.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={
                "region": row.get("region") or "",
                "node_type_id": type_id,
                "x": row.get("x") or 0,
                "y": row.get("y") or 0,
            },
        )
        if created:
            ctx.bump("mapNodes", "created")
        else:
            ctx.bump("mapNodes", "skipped")
        ctx.ids.put("mapNodes", row.get("_id"), obj.id)


def _imp_map_edges(rows: list[dict], ctx: ImportContext) -> None:
    from apps.maps.models import MapEdge, MapNode, PathType

    for row in rows:
        from_id = ctx.ref.resolve("mapNodes", row.get("fromNodeId"), name=row.get("fromNodeName"))
        to_id = ctx.ref.resolve("mapNodes", row.get("toNodeId"), name=row.get("toNodeName"))
        if from_id is None or to_id is None:
            ctx.problem(
                f"地图连线 #{row.get('_id')} 的端点节点未在本包中导入"
                f"（{row.get('fromNodeId')}→{row.get('toNodeId')}），已跳过"
            )
            ctx.bump("mapEdges", "skipped")
            continue
        type_name = row.get("pathTypeName")
        type_id = ctx.ref.resolve("pathTypes", row.get("pathTypeId"), name=type_name)
        if type_id is None and type_name:
            type_id = PathType.objects.filter(
                competition_id=ctx.competition_id, name=type_name
            ).values_list("id", flat=True).first()
            if type_id is None:
                type_id = PathType.objects.create(
                    competition_id=ctx.competition_id, name=type_name
                ).id
                ctx.note(f"路径类型「{type_name}」不在导入包内，已自动创建")
        if type_id is None:
            ctx.problem(f"地图连线 #{row.get('_id')} 缺少路径类型，已跳过")
            ctx.bump("mapEdges", "skipped")
            continue
        if from_id == to_id:
            ctx.problem(f"地图连线 #{row.get('_id')} 的起终点相同，已跳过")
            ctx.bump("mapEdges", "skipped")
            continue
        if not (MapNode.objects.filter(pk=from_id).exists() and MapNode.objects.filter(pk=to_id).exists()):
            ctx.bump("mapEdges", "skipped")
            continue
        obj, created = MapEdge.objects.get_or_create(
            from_node_id=from_id,
            to_node_id=to_id,
            defaults={
                "competition_id": ctx.competition_id,
                "distance": row.get("distance") or 0,
                "path_type_id": type_id,
            },
        )
        if created:
            ctx.bump("mapEdges", "created")
        else:
            ctx.bump("mapEdges", "skipped")
        ctx.ids.put("mapEdges", row.get("_id"), obj.id)


def _imp_fuels(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import(
        "fuels",
        rows,
        ctx,
        model_path="fuels.Fuel",
        extra_fields={"price_per_liter": "pricePerLiter"},
    )


def _imp_materials(rows: list[dict], ctx: ImportContext) -> None:
    from apps.maps.models import MapNode
    from apps.materials.models import Material

    node_id_by_name = {
        n["name"]: n["id"]
        for n in MapNode.objects.filter(competition_id=ctx.competition_id).values("id", "name")
    }

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("materials", "skipped")
            continue
        # 地点价优先用「节点名 → 价格」重建（可跨分组独立导入）；
        # 退回按旧节点 id 映射（同一份数据同时含 geo 分组时）。
        new_prices: dict[str, Any] = {}
        dropped = 0
        by_name = row.get("nodePricesByName") or {}
        if isinstance(by_name, dict) and by_name:
            for node_name, price in by_name.items():
                node_id = node_id_by_name.get(node_name)
                if node_id is None:
                    node_id = ctx.ref.resolve("mapNodes", None, name=node_name)
                if node_id is None:
                    dropped += 1
                    continue
                new_prices[str(node_id)] = price
        else:
            old_prices = row.get("nodePrices") or {}
            if isinstance(old_prices, dict):
                for old_node_id, price in old_prices.items():
                    key = int(old_node_id) if str(old_node_id).isdigit() else old_node_id
                    new_node_id = ctx.ref.resolve("mapNodes", key)
                    if new_node_id is None:
                        dropped += 1
                        continue
                    new_prices[str(new_node_id)] = price
        if dropped:
            ctx.note(
                f"原料「{name}」有 {dropped} 个地点价对应的地图节点在目标比赛里不存在，这些地点价未导入"
                "（如需保留，请先在「地图管理」建好同名节点，或连同「地理与物流」分组一起导入）"
            )
        obj, created = Material.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={
                "origin": row.get("origin") or "",
                "carbon_emission_coefficient": row.get("carbonEmissionCoefficient") or 0,
                "node_prices": json.dumps(new_prices, ensure_ascii=False),
                "type": row.get("type") or "NORMAL",
            },
        )
        if created:
            ctx.bump("materials", "created")
        elif ctx.keep_existing_id("materials", row.get("_id"), obj.id, f"原料「{name}」"):
            ctx.ids.put("materials", row.get("_id"), obj.id)
            continue
        else:
            obj.origin = row.get("origin") or ""
            obj.carbon_emission_coefficient = row.get("carbonEmissionCoefficient") or 0
            obj.node_prices = json.dumps(new_prices, ensure_ascii=False)
            obj.type = row.get("type") or "NORMAL"
            obj.save()
            ctx.bump("materials", "updated")
        ctx.ids.put("materials", row.get("_id"), obj.id)


def _imp_tech_nodes(rows: list[dict], ctx: ImportContext) -> None:
    from apps.tech_tree.models import TechNode

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("techNodes", "skipped")
            continue
        obj, created = TechNode.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={
                "description": row.get("description"),
                "tier": row.get("tier") or 0,
                "research_cost": row.get("researchCost") or 0,
            },
        )
        if created:
            ctx.bump("techNodes", "created")
        elif ctx.keep_existing_id("techNodes", row.get("_id"), obj.id, f"科技节点「{name}」"):
            ctx.ids.put("techNodes", row.get("_id"), obj.id)
            continue
        else:
            obj.tier = row.get("tier") or 0
            obj.research_cost = row.get("researchCost") or 0
            obj.description = row.get("description")
            obj.save()
            ctx.bump("techNodes", "updated")
        ctx.ids.put("techNodes", row.get("_id"), obj.id)


def _imp_tech_prerequisites(rows: list[dict], ctx: ImportContext) -> None:
    from apps.tech_tree.models import TechPrerequisite

    for row in rows:
        node_id = ctx.ids.get("techNodes", row.get("nodeId"))
        pre_id = ctx.ids.get("techNodes", row.get("prerequisiteId"))
        if node_id is None or pre_id is None:
            ctx.problem(f"科技前置 #{row.get('_id')} 的节点未在本包中导入，已跳过")
            ctx.bump("techPrerequisites", "skipped")
            continue
        if node_id == pre_id:
            ctx.problem(f"科技前置 #{row.get('_id')} 指向自身，已跳过")
            ctx.bump("techPrerequisites", "skipped")
            continue
        _, created = TechPrerequisite.objects.get_or_create(node_id=node_id, prerequisite_id=pre_id)
        ctx.bump("techPrerequisites", "created" if created else "skipped")


def _imp_infrastructures(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import(
        "infrastructures",
        rows,
        ctx,
        model_path="infrastructures.Infrastructure",
        extra_fields={
            "footprint": "footprint",
            "price": "price",
            "activation_price": "activationPrice",
            "employment_rate_bonus": "employmentRateBonus",
            "population_bonus": "populationBonus",
            "high_quality_population_bonus": "highQualityPopulationBonus",
            "happiness_index_bonus": "happinessIndexBonus",
            "per_capita_income_bonus": "perCapitaIncomeBonus",
            "carbon_reduction_bonus": "carbonReductionBonus",
        },
    )


def _imp_production_lines(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import(
        "productionLines",
        rows,
        ctx,
        model_path="production_lines.ProductionLine",
        extra_fields={
            "price": "price",
            "labor_count": "laborCount",
            "max_per_year": "maxPerYear",
        },
    )


def _imp_warehouses(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import(
        "warehouses",
        rows,
        ctx,
        model_path="warehouses.Warehouse",
        extra_fields={"type": "type", "capacity": "capacity", "price": "price"},
    )


def _imp_parts(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import("parts", rows, ctx, model_path="parts.Part")


def _imp_products(rows: list[dict], ctx: ImportContext) -> None:
    _simple_lookup_import("products", rows, ctx, model_path="products.Product")


def _imp_part_materials(rows: list[dict], ctx: ImportContext) -> None:
    from apps.parts.models import PartMaterial

    for row in rows:
        part_id = ctx.ref.resolve("parts", row.get("partId"), name=row.get("partName"))
        material_id = ctx.ref.resolve("materials", row.get("materialId"), name=row.get("materialName"))
        if part_id is None or material_id is None:
            ctx.problem(f"零件配比 #{row.get('_id')} 的零件或原料未在本包中导入，已跳过")
            ctx.bump("partMaterials", "skipped")
            continue
        obj, created = PartMaterial.objects.get_or_create(
            part_id=part_id, material_id=material_id, defaults={"ratio": row.get("ratio") or 0}
        )
        if created:
            ctx.bump("partMaterials", "created")
        else:
            obj.ratio = row.get("ratio") or 0
            obj.save()
            ctx.bump("partMaterials", "updated")


def _imp_part_tech_requirements(rows: list[dict], ctx: ImportContext) -> None:
    from apps.parts.models import PartTechRequirement

    for row in rows:
        part_id = ctx.ref.resolve("parts", row.get("partId"), name=row.get("partName"))
        tech_id = ctx.ref.resolve("techNodes", row.get("techNodeId"), name=row.get("techNodeName"))
        if part_id is None or tech_id is None:
            ctx.problem(f"零件科技需求 #{row.get('_id')} 的零件或科技节点未在本包中导入，已跳过")
            ctx.bump("partTechRequirements", "skipped")
            continue
        _, created = PartTechRequirement.objects.get_or_create(part_id=part_id, tech_node_id=tech_id)
        ctx.bump("partTechRequirements", "created" if created else "skipped")


def _imp_product_parts(rows: list[dict], ctx: ImportContext) -> None:
    from apps.products.models import ProductPart

    for row in rows:
        product_id = ctx.ref.resolve("products", row.get("productId"), name=row.get("productName"))
        part_id = ctx.ref.resolve("parts", row.get("partId"), name=row.get("partName"))
        if product_id is None or part_id is None:
            ctx.problem(f"产品配比 #{row.get('_id')} 的产品或零件未在本包中导入，已跳过")
            ctx.bump("productParts", "skipped")
            continue
        obj, created = ProductPart.objects.get_or_create(
            product_id=product_id, part_id=part_id, defaults={"ratio": row.get("ratio") or 0}
        )
        if created:
            ctx.bump("productParts", "created")
        else:
            obj.ratio = row.get("ratio") or 0
            obj.save()
            ctx.bump("productParts", "updated")


def _imp_product_tech_requirements(rows: list[dict], ctx: ImportContext) -> None:
    from apps.products.models import ProductTechRequirement

    for row in rows:
        product_id = ctx.ref.resolve("products", row.get("productId"), name=row.get("productName"))
        tech_id = ctx.ref.resolve("techNodes", row.get("techNodeId"), name=row.get("techNodeName"))
        if product_id is None or tech_id is None:
            ctx.problem(f"产品科技需求 #{row.get('_id')} 的产品或科技节点未在本包中导入，已跳过")
            ctx.bump("productTechRequirements", "skipped")
            continue
        _, created = ProductTechRequirement.objects.get_or_create(
            product_id=product_id, tech_node_id=tech_id
        )
        ctx.bump("productTechRequirements", "created" if created else "skipped")


def _imp_vehicles(rows: list[dict], ctx: ImportContext) -> None:
    from apps.vehicles.models import Vehicle

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("vehicles", "skipped")
            continue
        fuel_id = ctx.ref.resolve("fuels", row.get("fuelId"), name=row.get("fuelName"))
        if fuel_id is None:
            ctx.problem(
                f"载具「{name}」引用的燃料未在本包中导入，已跳过"
                "（请连同「物资与产能」分组一起导出导入；载具必须绑定燃料）"
            )
            ctx.bump("vehicles", "skipped")
            continue
        obj, created = Vehicle.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={
                "fuel_id": fuel_id,
                "fuel_consumption_per_km": row.get("fuelConsumptionPerKm") or 0,
                "max_cargo": row.get("maxCargo") or 0,
                "price": row.get("price") or 0,
                "carbon_emission": row.get("carbonEmission") or 0,
            },
        )
        if created:
            ctx.bump("vehicles", "created")
        elif ctx.keep_existing_id("vehicles", row.get("_id"), obj.id, f"载具「{name}」"):
            ctx.ids.put("vehicles", row.get("_id"), obj.id)
            continue
        else:
            obj.fuel_id = fuel_id
            obj.fuel_consumption_per_km = row.get("fuelConsumptionPerKm") or 0
            obj.max_cargo = row.get("maxCargo") or 0
            obj.price = row.get("price") or 0
            obj.carbon_emission = row.get("carbonEmission") or 0
            obj.save()
            ctx.bump("vehicles", "updated")
        ctx.ids.put("vehicles", row.get("_id"), obj.id)


def _imp_vehicle_path_types(rows: list[dict], ctx: ImportContext) -> None:
    from apps.vehicles.models import VehiclePathType

    for row in rows:
        vehicle_id = ctx.ref.resolve("vehicles", row.get("vehicleId"), name=row.get("vehicleName"))
        path_id = ctx.ref.resolve("pathTypes", row.get("pathTypeId"), name=row.get("pathTypeName"))
        if vehicle_id is None or path_id is None:
            ctx.problem(f"载具通行路径 #{row.get('_id')} 的载具或路径类型未在本包中导入，已跳过")
            ctx.bump("vehiclePathTypes", "skipped")
            continue
        _, created = VehiclePathType.objects.get_or_create(vehicle_id=vehicle_id, path_type_id=path_id)
        ctx.bump("vehiclePathTypes", "created" if created else "skipped")


def _imp_consumer_demands(rows: list[dict], ctx: ImportContext) -> None:
    from apps.consumer_demands.models import ConsumerDemand

    for row in rows:
        region = (row.get("region") or "").strip()
        product_type = (row.get("productType") or "").strip()
        if not region or not product_type:
            ctx.bump("consumerDemands", "skipped")
            continue
        product_id = ctx.ref.resolve("products", row.get("productId"), name=product_type)
        if product_id is None:
            ctx.note(
                f"消费者需求「{region}·{product_type}」在目标比赛里找不到同名产品，已按名称保留"
                "（未关联产品记录；导入「物资与产能」分组后会自动关联）"
            )
        quantity = row.get("quantity") or 0
        # 自然键（比赛 + 区域 + 产品类型 + 数量）去重：合并导入时不重复追加需求
        obj, created = ConsumerDemand.objects.get_or_create(
            competition_id=ctx.competition_id,
            region=region,
            product_type=product_type,
            quantity=quantity,
            defaults={"product_id": product_id, "note": row.get("note")},
        )
        ctx.ids.put("consumerDemands", row.get("_id"), obj.id)
        if created:
            ctx.bump("consumerDemands", "created")
        else:
            touched = False
            if product_id is not None and obj.product_id != product_id:
                obj.product_id = product_id
                touched = True
            if touched:
                obj.save(update_fields=["product_id", "updated_at"])
                ctx.bump("consumerDemands", "updated")
            else:
                ctx.bump("consumerDemands", "skipped")


def _imp_contract_types(rows: list[dict], ctx: ImportContext) -> None:
    """全局资源：按 key 复用/更新。"""
    from apps.contracts.models import ContractType

    for row in rows:
        key = (row.get("key") or "").strip()
        if not key:
            ctx.bump("contractTypes", "skipped")
            continue
        party_roles = row.get("partyRoles") or []
        payload = {
            "name": row.get("name") or key,
            "description": row.get("description"),
            "party_count": len(party_roles) if isinstance(party_roles, list) else 0,
            "party_roles": json.dumps(party_roles, ensure_ascii=False),
            "input_schema": json.dumps(row.get("inputSchema") or [], ensure_ascii=False),
            "effects": json.dumps(row.get("effects") or [], ensure_ascii=False),
            "conditions": json.dumps(row.get("conditions") or [], ensure_ascii=False),
            "graph": (
                json.dumps(row.get("graph"), ensure_ascii=False) if row.get("graph") is not None else None
            ),
            "schema_version": row.get("schemaVersion") or 1,
            "enabled": True if row.get("enabled") is None else bool(row.get("enabled")),
        }
        obj, created = ContractType.objects.get_or_create(key=key, defaults=payload)
        if created:
            ctx.bump("contractTypes", "created")
        elif ctx.keep_existing_id("contractTypes", row.get("_id"), obj.id, f"合同类型「{obj.name}」"):
            ctx.ids.put("contractTypes", row.get("_id"), obj.id)
            ctx.ids.put("contractTypeByKey", key, obj.id)
            continue
        else:
            for k, v in payload.items():
                setattr(obj, k, v)
            obj.save()
            ctx.bump("contractTypes", "updated")
        ctx.ids.put("contractTypes", row.get("_id"), obj.id)
        ctx.ids.put("contractTypeByKey", key, obj.id)


def _imp_contract_instances(rows: list[dict], ctx: ImportContext) -> None:
    from apps.contracts.models import Contract, ContractType

    for row in rows:
        key = row.get("contractTypeKey")
        ct_id = ctx.ids.get("contractTypeByKey", key) or ContractType.objects.filter(
            key=key
        ).values_list("id", flat=True).first()
        if ct_id is None:
            ctx.problem(f"合同实例 #{row.get('_id')} 的合同类型 key={key} 不存在，已跳过")
            ctx.bump("contractInstances", "skipped")
            continue
        ct = ContractType.objects.filter(pk=ct_id).first()
        # 参与方中的 companyId 需要映射到新公司
        parties = _json_list(row.get("parties"))
        for p in parties:
            if isinstance(p, dict) and (p.get("companyId") is not None or p.get("companyName")):
                mapped = ctx.ref.resolve(
                    "companies", p.get("companyId"), name=p.get("companyName")
                )
                if mapped is None:
                    ctx.problem(
                        f"合同实例 #{row.get('_id')} 的参与方公司 "
                        f"#{p.get('companyId')}（{p.get('companyName') or '未知名'}）未在本包中导入，该方公司置空"
                    )
                    p["companyId"] = None
                else:
                    p["companyId"] = mapped
        obj = Contract.objects.filter(
            competition_id=ctx.competition_id, contract_type_id=ct_id, name=ct.name if ct else (row.get("name") or "合同")
        ).first()
        if obj is None:
            obj = Contract.objects.create(
                competition_id=ctx.competition_id,
                contract_type_id=ct_id,
                name=ct.name if ct else (row.get("name") or "合同"),
                status=row.get("status") or "DRAFT",
                parties=json.dumps(parties, ensure_ascii=False),
                inputs=json.dumps(row.get("inputs") or {}, ensure_ascii=False),
            )
            ctx.bump("contractInstances", "created")
        else:
            # 已存在同类型同名的合同（合并导入）：只补参与方公司引用，不覆盖已有状态
            ctx.bump("contractInstances", "skipped")
        ctx.ids.put("contractInstances", row.get("_id"), obj.id)


def _imp_stocks(rows: list[dict], ctx: ImportContext) -> None:
    from apps.stock.models import Stock

    for row in rows:
        code = (row.get("code") or "").strip()
        name = (row.get("name") or "").strip()
        if not code or not name:
            ctx.bump("stocks", "skipped")
            continue
        company_id = ctx.ref.resolve("companies", row.get("companyId"), name=row.get("companyName"))
        obj, created = Stock.objects.get_or_create(
            competition_id=ctx.competition_id,
            code=code,
            defaults={
                "name": name,
                "company_id": company_id,
                "total_shares": row.get("totalShares") or 0,
                "init_net_profit": row.get("initNetProfit") or 0,
                "init_price": row.get("initPrice") or 0,
                "current_price": row.get("currentPrice") or row.get("initPrice") or 0,
                "industry_pe": row.get("industryPe") or 0,
                "current_carbon": row.get("currentCarbon") or 0,
                "industry_avg_carbon": row.get("industryAvgCarbon") or 0,
                "happiness": row.get("happiness") or 0,
                "round": row.get("round") or 0,
                "carbon_field_ref": row.get("carbonFieldRef"),
                "happiness_field_ref": row.get("happinessFieldRef"),
                "industry_avg_carbon_refs": row.get("industryAvgCarbonRefs"),
                "pb_company_id": ctx.ids.get("companies", row.get("pbCompanyId")),
                "pb_field_id": None,
                "pb_random": row.get("pbRandom"),
            },
        )
        if created:
            ctx.bump("stocks", "created")
        else:
            ctx.bump("stocks", "skipped")
        ctx.ids.put("stocks", row.get("_id"), obj.id)
        if row.get("pbFieldId") is not None:
            ctx.note(
                f"股票「{code}」的行业 PE 联动字段绑定（pbFieldId={row.get('pbFieldId')}）指向具体字段 id，"
                "未跨比赛搬运；如需联动请在股票管理中重新选择。"
            )


def _imp_stock_funds_accounts(rows: list[dict], ctx: ImportContext) -> None:
    from apps.stock.models import StockFundsAccount

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            ctx.bump("stockFundsAccounts", "skipped")
            continue
        owner_type = row.get("ownerType") or "COMPANY"
        company_id = ctx.ref.resolve("companies", row.get("companyId"), name=row.get("companyName"))
        user_id = ctx.ref.resolve("users", row.get("userId"), name=row.get("username"))
        obj, created = StockFundsAccount.objects.get_or_create(
            competition_id=ctx.competition_id,
            name=name,
            defaults={
                "owner_type": owner_type,
                "company_id": company_id if owner_type == "COMPANY" else None,
                "user_id": user_id if owner_type == "USER" else None,
                "cash_balance": row.get("cashBalance") or 0,
                "bind_field_id": None,
            },
        )
        if created:
            ctx.bump("stockFundsAccounts", "created")
        else:
            ctx.bump("stockFundsAccounts", "skipped")
        ctx.ids.put("stockFundsAccounts", row.get("_id"), obj.id)
        if row.get("bindFieldId") is not None:
            ctx.note(
                f"资金账户「{name}」的绑定字段（bindFieldId={row.get('bindFieldId')}）指向具体字段 id，"
                "未跨比赛搬运；如需联动请在股票管理中重新选择。"
            )


def _imp_overview_cards(rows: list[dict], ctx: ImportContext) -> None:
    from apps.regions.models import Region

    for row in rows:
        region_name = (row.get("regionName") or "").strip()
        if not region_name:
            ctx.bump("overviewCards", "skipped")
            continue
        cards = row.get("cards") or []
        # 卡片里的 companyId 换成本次导入的公司 id；换不到的卡片丢弃并提示
        kept = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            cid_old = card.get("companyId")
            cid_name = card.get("companyName")
            mapped = ctx.ref.resolve("companies", cid_old, name=cid_name) if (cid_old is not None or cid_name) else None
            if (cid_old is not None or cid_name) and mapped is None:
                continue
            new_card = dict(card)
            if mapped is not None:
                new_card["companyId"] = mapped
            kept.append(new_card)
        dropped = len(cards) - len(kept)
        if dropped:
            ctx.note(
                f"区域「{region_name}」有 {dropped} 张概览卡片的公司不在导入包内，这些卡片已丢弃"
                "（如需完整卡片，请连同「参赛主体」分组一起导入）"
            )
        region, created = Region.objects.get_or_create(
            competition_id=ctx.competition_id, name=region_name, defaults={"overview_cards": "[]"}
        )
        if created:
            ctx.bump("overviewCards", "created")
        region.overview_cards = json.dumps(kept, ensure_ascii=False)
        region.save(update_fields=["overview_cards", "updated_at"])
        ctx.ids.put("overviewCards", row.get("_id"), region.id)


def _imp_messages(rows: list[dict], ctx: ImportContext) -> None:
    from apps.messages.models import Message
    from apps.users.models import User

    # 发布者必填：优先按用户名映射，其次用导入操作者，最后回退任一超管
    default_sender = ctx.user if getattr(ctx.user, "pk", None) else User.objects.filter(
        role="SUPER_ADMIN"
    ).first()
    if default_sender is None:
        ctx.problem("没有可用的消息发布者（无超管账号），消息已全部跳过")
        ctx.bump("messages", "skipped", len(rows))
        return

    for row in rows:
        title = (row.get("title") or "").strip()
        if not title:
            ctx.bump("messages", "skipped")
            continue
        sender = default_sender
        sender_name = row.get("senderUsername")
        if sender_name:
            found = User.objects.filter(username=sender_name).first()
            if found is not None:
                sender = found
            else:
                ctx.note(
                    f"消息「{title}」的原发布者「{sender_name}」在目标库中不存在，改由当前操作账号发布"
                )
        # 指定收件人按用户名映射（用户 id 跨比赛会变）
        old_ids = _json_list(row.get("targetUserIds"))
        new_ids = []
        for old in old_ids:
            mapped = ctx.ids.get("users", old)
            if mapped is None:
                continue
            new_ids.append(mapped)
        if len(new_ids) != len(old_ids):
            ctx.note(
                f"消息「{title}」的部分指定收件人不在导入包内，已从收件人中移除"
                "（如需完整收件人，请连同「账号与权限」分组一起导入）"
            )
        Message.objects.create(
            competition_id=ctx.competition_id,
            title=title,
            content=row.get("content") or "",
            sender_id=sender.pk,
            targets_all=bool(row.get("targetsAll")),
            target_user_ids=json.dumps(new_ids, ensure_ascii=False),
        )
        ctx.bump("messages", "created")


def _map_company_scope_ids(ids: list, by_name: list, ctx: "ImportContext") -> list:
    """把账号的公司范围（源比赛 id 列表）映射到目标比赛。

    先按 id 映射，再按「同下标的公司名」兜底 —— 这样单独导入「账号与权限」分组时，
    只要目标比赛里已有同名公司，范围依然能正确指向。
    """
    out: list = []
    for idx, old_id in enumerate(ids):
        mapped = ctx.ids.get("companies", old_id)
        if mapped is None:
            name = by_name[idx] if idx < len(by_name) and by_name[idx] else ctx.old_company_names.get(old_id)
            if name:
                mapped = ctx.ref.resolve("companies", old_id, name=name)
        if mapped is not None and mapped not in out:
            out.append(mapped)
    return out


def _imp_users(rows: list[dict], ctx: ImportContext) -> None:
    """账号导入：不含密码，统一设为「首次登录必须改密」并要求超管重置密码。

    用户名全局唯一（跨比赛）：
    - 目标库无该用户名 → 新建账号，归属目标比赛，密码为随机值（需超管重置）。
    - 目标库已有该用户名 → 不覆盖密码、不抢归属，只把公司范围**并入**已有范围，
      使同一个账号可以同时操作多场比赛的公司。
    """
    from apps.users.models import User

    def _merge_scopes(existing: list, added: list) -> list:
        """把新范围并入旧范围（保持顺序、去重）。"""
        out = list(existing)
        for s in added:
            if s not in out:
                out.append(s)
        return out

    for row in rows:
        username = (row.get("username") or "").strip()
        if not username:
            ctx.bump("users", "skipped")
            continue
        role = row.get("role") or "PLAYER"
        scopes = _json_list(row.get("companyScopes"))
        mapped_scopes = _map_company_scope_ids(scopes, _json_list(row.get("companyScopeNames")), ctx)
        if len(mapped_scopes) != len(scopes):
            ctx.note(f"账号「{username}」的部分公司范围公司不在导入包内，已移除这些范围项")
        view_scopes = _map_company_scope_ids(
            _json_list(row.get("viewCompanyScopes")), _json_list(row.get("viewCompanyScopeNames")), ctx
        )
        contract_scopes = _map_company_scope_ids(
            _json_list(row.get("contractViewCompanyScopes")),
            _json_list(row.get("contractViewCompanyScopeNames")),
            ctx,
        )
        stock_scopes = _map_company_scope_ids(
            _json_list(row.get("stockCompanyScopes")), _json_list(row.get("stockCompanyScopeNames")), ctx
        )

        existing = User.objects.filter(username=username).first()
        if existing is not None:
            changed = []
            # 角色只在目标账号仍是默认 PLAYER 时按归档提升，避免降级既有管理员
            if role != "PLAYER" and existing.role == "PLAYER":
                existing.role = role
                changed.append("role")
            if existing.competition_id is None and role != "SUPER_ADMIN":
                existing.competition_id = ctx.competition_id
                changed.append("competition")
            merged = {
                "company_scopes": _merge_scopes(_json_list(existing.company_scopes), mapped_scopes),
                "view_company_scopes": _merge_scopes(
                    _json_list(existing.view_company_scopes), view_scopes
                ),
                "contract_view_company_scopes": _merge_scopes(
                    _json_list(existing.contract_view_company_scopes), contract_scopes
                ),
                "stock_company_scopes": _merge_scopes(
                    _json_list(existing.stock_company_scopes), stock_scopes
                ),
            }
            for k, v in merged.items():
                new_val = json.dumps(v, ensure_ascii=False)
                if getattr(existing, k) != new_val:
                    setattr(existing, k, new_val)
                    changed.append(k)
            if changed:
                existing.save(update_fields=changed + ["updated_at"])
                ctx.bump("users", "updated")
            else:
                ctx.bump("users", "skipped")
            ctx.ids.put("users", row.get("_id"), existing.id)
            ctx.note(
                f"账号「{username}」已存在：密码未被覆盖，公司范围已合并（可同时操作多场比赛的公司）"
            )
            continue

        user = User(
            username=username,
            role=role,
            display_name=row.get("displayName"),
            competition_id=None if role == "SUPER_ADMIN" else ctx.competition_id,
            company_scopes=json.dumps(mapped_scopes, ensure_ascii=False),
            view_company_scopes=json.dumps(view_scopes, ensure_ascii=False),
            contract_view_company_scopes=json.dumps(contract_scopes, ensure_ascii=False),
            stock_company_scopes=json.dumps(stock_scopes, ensure_ascii=False),
            permissions=json.dumps(_json_list(row.get("permissions")), ensure_ascii=False),
            is_active=True if row.get("isActive") is None else bool(row.get("isActive")),
            must_change_password=True,
        )
        # 导出文件不含密码：给一个随机初始密码，必须由超管重置后才能登录
        import secrets

        user.set_password(secrets.token_urlsafe(16))
        user.save()
        ctx.ids.put("users", row.get("_id"), user.id)
        ctx.bump("users", "created")
        ctx.note(f"账号「{username}」已创建但密码为随机值 {_IMPORT_RESET_PASSWORD_NOTE}")


_IMPORTERS: dict[str, _ImportFn] = {
    "competitionMeta": _imp_competition_meta,
    "fiscalYears": _imp_fiscal_years,
    "stockConfig": _imp_stock_config,
    "industryTypes": _imp_industry_types,
    "industryFields": _imp_industry_fields,
    "companies": _imp_companies,
    "companyFieldValues": _imp_company_field_values,
    "regions": _imp_regions,
    "mapNodeTypes": _imp_map_node_types,
    "pathTypes": _imp_path_types,
    "mapNodes": _imp_map_nodes,
    "mapEdges": _imp_map_edges,
    "fuels": _imp_fuels,
    "materials": _imp_materials,
    "techNodes": _imp_tech_nodes,
    "techPrerequisites": _imp_tech_prerequisites,
    "infrastructures": _imp_infrastructures,
    "productionLines": _imp_production_lines,
    "warehouses": _imp_warehouses,
    "parts": _imp_parts,
    "partMaterials": _imp_part_materials,
    "partTechRequirements": _imp_part_tech_requirements,
    "products": _imp_products,
    "productParts": _imp_product_parts,
    "productTechRequirements": _imp_product_tech_requirements,
    "vehicles": _imp_vehicles,
    "vehiclePathTypes": _imp_vehicle_path_types,
    "consumerDemands": _imp_consumer_demands,
    "contractTypes": _imp_contract_types,
    "contractInstances": _imp_contract_instances,
    "stocks": _imp_stocks,
    "stockFundsAccounts": _imp_stock_funds_accounts,
    "overviewCards": _imp_overview_cards,
    "messages": _imp_messages,
    "users": _imp_users,
}


# ==================== 导入入口 ====================

class ArchiveError(Exception):
    """归档文件结构非法。"""


def validate_archive(payload: Any) -> dict:
    """校验归档文件结构，返回归一化后的 payload。"""
    if not isinstance(payload, dict):
        raise ArchiveError("归档文件内容不是 JSON 对象")
    resources = payload.get("resources")
    if not isinstance(resources, dict) or not resources:
        raise ArchiveError("归档文件缺少 resources 字段或内容为空")
    version = payload.get("schemaVersion")
    if version is not None and version != SCHEMA_VERSION:
        raise ArchiveError(f"归档文件版本不支持：{version}（当前支持 {SCHEMA_VERSION}）")
    for name, block in resources.items():
        if name not in _IMPORTERS:
            raise ArchiveError(f"归档文件包含未知资源：{name}")
        if not isinstance(block, dict):
            raise ArchiveError(f"资源 {name} 的结构非法")
        rows = block.get("rows")
        if rows is not None and not isinstance(rows, list):
            raise ArchiveError(f"资源 {name} 的 rows 必须是数组")
    return payload


# 目标比赛「非空」判定用的比赛级模型（按依赖顺序，命中即为已有数据）
_NON_EMPTY_PROBES: list[tuple[str, str]] = [
    ("公司", "companies.Company"),
    ("原料", "materials.Material"),
    ("零件", "parts.Part"),
    ("产品", "products.Product"),
    ("地图节点", "maps.MapNode"),
    ("科技节点", "tech_tree.TechNode"),
    ("区域", "regions.Region"),
    ("燃料", "fuels.Fuel"),
    ("基建", "infrastructures.Infrastructure"),
    ("载具", "vehicles.Vehicle"),
    ("仓库", "warehouses.Warehouse"),
    ("生产线", "production_lines.ProductionLine"),
    ("股票", "stock.Stock"),
    ("预算账户", "stock.StockFundsAccount"),
    ("合同", "contracts.Contract"),
    ("消费者需求", "consumer_demands.ConsumerDemand"),
    ("参赛账号", "users.User"),
]


def competition_occupancy(competition_id: int) -> list[tuple[str, int]]:
    """统计目标比赛已有的业务数据（用于「空比赛才能导入」判定）。"""
    from django.apps import apps as django_apps

    found: list[tuple[str, int]] = []
    for label, model_path in _NON_EMPTY_PROBES:
        model = django_apps.get_model(model_path)
        try:
            n = model.objects.filter(competition_id=competition_id).count()
        except Exception:  # noqa: BLE001 - 模型无 competition 字段时跳过
            continue
        if n:
            found.append((label, n))
    return found


def apply_import(
    payload: dict,
    competition_id: int,
    *,
    dry_run: bool,
    allow_non_empty: bool,
    mode: str = MODE_APPEND,
    only_resources: set[str] | None = None,
    user=None,
) -> dict:
    """把归档数据导入目标比赛。

    导入策略（mode）：
    - append（追加，默认）：只补目标比赛缺的数据；同键已存在的记录**原样保留**，
      其子数据（配比/需求/关联等）也一并保留，不往既有对象里混入新关联。
    - overwrite（覆盖）：同键已存在的记录按归档内容更新（保留主键与关联关系，不删除记录）。

    范围（only_resources）：只导入用户勾选的资源；None 表示归档里有什么就导什么。

    事务策略：
    - dry_run=True：整体执行后强制回滚，返回与真实导入一致的结果预览。
    - dry_run=False：整体成功才提交；出现异常则回滚并抛出。

    安全策略：目标比赛已有数据时，默认拒绝；需显式 allow_non_empty=True 才允许写入。
    """
    resources = payload.get("resources") or {}
    ctx = ImportContext(
        competition_id,
        dry_run=dry_run,
        allow_non_empty=allow_non_empty,
        mode=mode,
        only_resources=only_resources,
        user=user,
    )

    # 目标比赛存在性
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=competition_id).exists():
        raise ArchiveError("目标比赛不存在")

    # 非空保护（dry_run 不抛错，改为在预览里提示，便于前端先把风险展示给用户）
    occupancy = competition_occupancy(competition_id)
    if occupancy and not allow_non_empty:
        detail = "、".join(f"{label} {n} 条" for label, n in occupancy[:6])
        msg = (
            f"目标比赛已有业务数据（{detail}），默认拒绝导入以避免污染既有数据。"
            "如确认要在已有数据上导入，请勾选「允许导入到已有数据的比赛」。"
        )
        if dry_run:
            ctx.problem(msg)
            result = ctx.result()
            result.update(
                {
                    "dryRun": True,
                    "blocked": True,
                    "targetCompetitionId": competition_id,
                    "sourceCompetition": payload.get("sourceCompetition"),
                    "scope": payload.get("scope") or SCOPE_ALL,
                    "occupancy": [{"label": label, "count": n} for label, n in occupancy],
                }
            )
            result["problemCount"] = len(result["problems"])
            return result
        raise ArchiveError(msg)

    # 预扫归档里的公司：供账号范围按公司名兜底映射（users 在 IMPORT_ORDER 末尾，届时映射表已就绪）
    for r in (resources.get("companies") or {}).get("rows") or []:
        if isinstance(r, dict) and r.get("_id") is not None and r.get("name"):
            ctx.old_company_names[r["_id"]] = r["name"]

    # 只导入用户勾选（且归档里存在）的资源，且按依赖顺序执行
    ordered = [r for r in IMPORT_ORDER if r in resources and ctx.wants(r)]
    skipped_resources = [
        r for r in IMPORT_ORDER if r in resources and not ctx.wants(r)
    ]

    with transaction.atomic():
        for res in ordered:
            rows = (resources.get(res) or {}).get("rows") or []
            if not rows:
                continue
            fn = _IMPORTERS.get(res)
            if fn is None:
                ctx.problem(f"资源 {res} 暂不支持导入，已跳过")
                continue
            # 追加模式：父记录被保留时，其子行一并跳过（集中处理，保证各资源语义一致）
            rows = _filter_rows_for_mode(res, rows, ctx)
            if not rows:
                continue
            try:
                fn(rows, ctx)
            except Exception as e:  # noqa: BLE001 - 单资源失败不中断整批
                ctx.problem(f"资源 {RESOURCE_LABELS.get(res, res)} 导入失败：{type(e).__name__}: {e}")
                ctx.bump(res, "skipped", len(rows))
        if dry_run:
            transaction.set_rollback(True)

    result = ctx.result()
    result["dryRun"] = dry_run
    result["blocked"] = False
    result["targetCompetitionId"] = competition_id
    result["sourceCompetition"] = payload.get("sourceCompetition")
    result["scope"] = payload.get("scope") or SCOPE_ALL
    result["occupancy"] = [{"label": label, "count": n} for label, n in occupancy]
    result["skippedResources"] = [
        {"resource": r, "label": RESOURCE_LABELS.get(r, r)} for r in skipped_resources
    ]
    result["problemCount"] = len(result["problems"])
    result["noteCount"] = len(result.get("notes") or [])
    return result


