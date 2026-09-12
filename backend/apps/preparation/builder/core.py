"""比赛建包库：用简单 Python 代码描述一场比赛的全部内容，产出现有导入引擎的归档 JSON。

定位
----
本库**只负责把「你想建什么」写成结构化数据**，不直接写数据库：

    CompetitionBuilder
        .build()            -> dict     与 `apps.preparation.archive.build_export` 完全同构
        .to_json()          -> str
        .save(path)         -> Path

产出的 JSON 可直接：
1. 用 `manage.py build_competition <脚本> --competition <id>` 导入（库自带，零新增写库逻辑）；
2. 从前端「比赛准备 → 导入归档」上传导入；
3. `POST /api/preparations/archive/import` 接口导入。

为什么这样做：导入侧的外键映射、跨分组按名兜底、追加/覆盖策略、空比赛保护、
dry-run 回滚等全部复用 `apps.preparation.archive` 里**已经存在并已验证**的实现，
本库不新增任何写库路径，因此不可能影响现有功能。

字段口径
--------
每类资源产出的列名与 `apps.preparation.archive._exp_*` 一一对应（camelCase）。
本库只写「用户显式设置」的列，未设置的列不出现，从而沿用导入侧的默认值
（例如公司 status 默认 ACTIVE、原料 type 默认 NORMAL），语义与手工导出后导入一致。

已知的导入侧固有语义（不是本库的缺陷，文档与体检都会提示）
--------------------------------------------------------
- 比赛名不会被导入改写（避免全局重名），只同步状态与缺失的地图背景图；
- 产业类型 / 产业字段 / 合同类型是**全局资源**，按 code / (code, fieldKey) / key 复用或更新；
- 账号不含密码，新账号密码为随机值且强制首次登录改密；
- 消息的「指定收件人」依赖账号 id 映射，而账号在导入顺序里排在消息之后，
  因此单次导入中指定收件人无法落地（导入侧会给出提示），需分两次导入；
- 股票/资金账户的字段 id 绑定（pbFieldId / bindFieldId）与总览卡片的 industryFieldId
  指向具体主键，跨比赛不搬运，需要重新选择或用 resolve_field_ids() 回填。

最小示例
--------
    from apps.preparation.builder import CompetitionBuilder

    b = CompetitionBuilder("2026 春季赛")
    east = b.region("东区")
    steel = b.industry_type(1, "钢铁")
    b.add_field(steel, "所在地", "location", field_type="STRING")
    b.add_field(steel, "现金", "cash", field_type="NUMBER", default_value="1000")
    b.company("甲钢铁", industry_type=steel, region=east, field_values={"cash": "5000"})
    b.fiscal_year(2026)
    b.save("spring-2026.json")
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from .types import (
    BuilderError,
    FIELD_TYPES,
    Ref,
    TIMER_TRIGGERS,
    positive_int,
    refs_of,
    require_text,
    resolve_ref,
)

__all__ = [
    "CompetitionBuilder",
    "BuilderError",
    "Ref",
    "RESOURCE_ORDER",
    "RESOURCE_LABELS",
    "SCOPES",
]

# 归档结构版本与生成器标识：与 apps.preparation.archive 保持一致
SCHEMA_VERSION = 1
GENERATOR = "gipfel-preparation-builder"

SCOPE_ALL = "all"

# 资源名 → 中文名（与 archive.RESOURCE_LABELS 一致，用于导出块与报错信息）
RESOURCE_LABELS: dict[str, str] = {
    "competitionMeta": "比赛名称与状态",
    "fiscalYears": "财年",
    "stockConfig": "股票系统参数",
    "industryTypes": "产业类型（全局）",
    "industryFields": "产业字段（全局）",
    "contractTypes": "合同类型（全局）",
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

# 产出顺序：必须与 archive.IMPORT_ORDER 的依赖顺序一致，否则引用会解析不到
RESOURCE_ORDER: tuple[str, ...] = (
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
)

# 分组（scope）→ 资源名：与 archive.SCOPES 一致，供 build(scope=...) 使用
SCOPES: dict[str, tuple[str, ...]] = {
    "competition": ("competitionMeta", "fiscalYears", "stockConfig"),
    "industry": ("industryTypes", "industryFields"),
    "company": ("companies", "companyFieldValues"),
    "supply": (
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
    ),
    "geo": ("regions", "mapNodeTypes", "pathTypes", "mapNodes", "mapEdges"),
    "tech": ("techNodes", "techPrerequisites", "consumerDemands"),
    "market": (
        "contractTypes",
        "contractInstances",
        "stocks",
        "stockFundsAccounts",
        "overviewCards",
        "messages",
    ),
    "access": ("users",),
}


def _assert_archive_parity() -> None:
    """启动期自检：本库的资源顺序与导入引擎保持一致。

    这是一道「防漂移」保险：archive.py 是导入引擎的唯一权威，一旦它的
    IMPORT_ORDER 增删资源，本库必须同步，否则会出现「产出了但导不进去」
    或「顺序不对导致引用解析不到」的静默问题。发现不一致立即抛错（fail-fast），
    而不是等到导入时才发现丢数据。
    """
    from apps.preparation import archive as _archive

    ours = list(RESOURCE_ORDER)
    theirs = list(_archive.IMPORT_ORDER)
    if len(set(ours)) != len(ours):
        dup = sorted({r for r in ours if ours.count(r) > 1})
        raise RuntimeError(f"builder.RESOURCE_ORDER 存在重复资源名：{dup}")
    if ours != theirs:
        only_ours = [r for r in ours if r not in theirs]
        only_theirs = [r for r in theirs if r not in ours]
        detail = []
        if only_ours:
            detail.append(f"本库多出：{only_ours}")
        if only_theirs:
            detail.append(f"本库缺少：{only_theirs}")
        if not detail:
            detail.append("资源顺序不一致")
        raise RuntimeError(
            "builder.RESOURCE_ORDER 与 apps.preparation.archive.IMPORT_ORDER 不一致（"
            + "；".join(detail)
            + "）；请同步 apps/preparation/builder/core.py 的顺序声明"
        )


def assert_archive_parity() -> None:
    """对外暴露的一致性自检（测试与命令启动时可调用）。"""
    _assert_archive_parity()


# 导入期 fail-fast：资源顺序与导入引擎不一致时立刻报错，避免静默丢数据。
# 注意：本库真正的「纯 Python」部分在 types.py / schema.py，core 因为要对着 archive 做一致性
# 自检而依赖 Django app 环境（manage.py / django.setup() 之后即可用，不需要数据库）。
_assert_archive_parity()

# 枚举取值（与各模型 choices 一致，写错立即报错而不是导入时才失败）
CONTRACT_STATUSES = ("DRAFT", "PENDING_EXEC", "EXECUTED", "TERMINATED")
WAREHOUSE_TYPES = ("MATERIAL", "PART", "PRODUCT", "FUEL")
MATERIAL_TYPES = ("NORMAL", "SPECIAL")
COMPANY_STATUSES = ("ACTIVE", "INACTIVE")
COMPETITION_STATUSES = ("ACTIVE", "CLOSED")
USER_ROLES = ("SUPER_ADMIN", "COMPETITION_ADMIN", "PLAYER")

# 四套公司范围字段：参数名 → (归档列名, 名称列名)
_SCOPE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("company_scopes", "companyScopes", "companyScopeNames"),
    ("view_company_scopes", "viewCompanyScopes", "viewCompanyScopeNames"),
    ("contract_view_company_scopes", "contractViewCompanyScopes", "contractViewCompanyScopeNames"),
    ("stock_company_scopes", "stockCompanyScopes", "stockCompanyScopeNames"),
)

# 导入顺序决定的固有语义：账号在消息之后，所以单次导入中消息的指定收件人无法落地
_USERS_IMPORTED_AFTER_MESSAGES = True


class CompetitionBuilder:
    """一场比赛的内容构建器（链式调用）。

    说明：
    - `_primary` 保存「每类资源的主记录」，附带其 `_id`（旧 id，导入时由引擎映射为新主键）；
    - `_extra` 保存「子记录」（配比 / 需求 / 范围 / 卡片 / 连线等），它们也各有自己的 `_id` 序列；
    - 所有名称在同一类资源内必须唯一（与数据库唯一约束一致），重复登记立即报错。
    """

    # ---------------- 初始化 ----------------

    def __init__(
        self,
        name: str,
        *,
        status: str = "ACTIVE",
        map_background: dict | None = None,
        stock_config: dict | None = None,
    ) -> None:
        self.name = require_text(name, "比赛名称")
        self.status = self._choice(status, COMPETITION_STATUSES, "比赛状态")
        self.map_background = map_background
        self.stock_config = stock_config

        self._primary: dict[str, list[dict]] = {r: [] for r in RESOURCE_ORDER}
        self._extra: dict[str, list[dict]] = {r: [] for r in RESOURCE_ORDER}
        self._by_name: dict[str, dict[str, dict]] = {r: {} for r in RESOURCE_ORDER}
        self._seq: dict[str, int] = {r: 0 for r in RESOURCE_ORDER}
        self._industry_by_code: dict[int, Ref] = {}
        self._contract_type_keys: set[str] = set()
        # (产业类型名, fieldKey) → 真实 industryField id（由 resolve_field_ids 回填）
        self._field_ids: dict[tuple[str, str], int] = {}
        # 概览卡片的登记信息：[(区域名, 卡片 dict, 产业类型名, fieldKey)]
        self._cards: list[tuple[str, dict, str, str]] = []

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _choice(value: Any, allowed: Sequence[str], field: str) -> str:
        text = require_text(value, field)
        if text not in allowed:
            raise BuilderError(f"{field} 取值必须是 {list(allowed)} 之一，收到 {text!r}")
        return text

    @staticmethod
    def _num(value: Any, field: str) -> Any:
        """数值列：原样透传（int / float / str 均可，字符串可保 Decimal 精度）。"""
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise BuilderError(
                f"{field} 必须是数字或数字字符串，收到 {type(value).__name__}: {value!r}"
            )
        return value

    @staticmethod
    def _opt(**kwargs: Any) -> dict:
        """剔除 None 的可选列字典。"""
        return {k: v for k, v in kwargs.items() if v is not None}

    def _next_id(self, resource: str) -> int:
        self._seq[resource] += 1
        return self._seq[resource]

    def _register(self, resource: str, name: str, row: dict, *, register_name: bool = True) -> Ref:
        """登记一条主记录：规范化名称、查重、分配 _id，返回引用。

        `register_name=False` 用于「归档里没有 name 列」的资源（如财年，其自然键是年份），
        此时 name 只作为构建器内部的登记键，不会出现在产出行里。
        """
        label = RESOURCE_LABELS.get(resource, resource)
        text = require_text(name, f"{label}名称")
        if text in self._by_name[resource]:
            raise BuilderError(
                f"{label}「{text}」重复登记；同一场比赛内名称必须唯一（与数据库唯一约束一致）"
            )
        stored = dict(row)
        stored["_id"] = self._next_id(resource)
        if register_name:
            stored["name"] = text
        self._primary[resource].append(stored)
        self._by_name[resource][text] = stored
        return Ref(resource, text)

    def _require(self, resource: str, name: str, field: str) -> dict:
        """要求某名称已在本构建器中登记，返回其行；否则报错（拦住导入期才暴露的引用缺失）。"""
        label = RESOURCE_LABELS.get(resource, resource)
        text = require_text(name, field)
        row = self._by_name[resource].get(text)
        if row is None:
            raise BuilderError(
                f"{field} 引用的 {label}「{text}」尚未在本构建器中登记"
                "（请先调用对应的登记方法，或检查名称拼写）"
            )
        return row

    def _has(self, resource: str, name: str) -> bool:
        return str(name).strip() in self._by_name[resource]

    def _add_extra(self, resource: str, row: dict) -> dict:
        stored = dict(row)
        stored["_id"] = self._next_id(resource)
        self._extra[resource].append(stored)
        return stored

    def _industry_row(self, ref: Any, field: str) -> dict:
        return self._require("industryTypes", resolve_ref(ref, "industryTypes", field), field)

    def _company_row(self, ref: Any, field: str) -> dict:
        return self._require("companies", resolve_ref(ref, "companies", field), field)

    def _industry_name_by_code(self, code: Any) -> str:
        ref = self._industry_by_code.get(code)
        if ref is None:
            raise BuilderError(
                f"公司引用的产业类型 code={code} 未在本构建器中登记；"
                "请用 company(industry_type=<industry_type() 的返回值>) 明确指定"
            )
        return ref.name

    def _field_owner_name(self, company_row: dict, industry_type: Any) -> str:
        """确定某公司字段值/卡片所用的产业类型名：显式指定优先，否则取公司自身产业类型。"""
        if industry_type is not None:
            return resolve_ref(industry_type, "industryTypes", "字段所属产业类型")
        return self._industry_name_by_code(company_row.get("industryTypeCode"))

    # ---------------- ① 比赛基础 ----------------

    def fiscal_year(self, year: int, *, status: str = "ACTIVE") -> Ref:
        """登记一个财年（比赛的时间轴）。

        导入侧语义：按 (比赛, 年份) 幂等；新建财年或把财年从非 ACTIVE 改为 ACTIVE 会触发
        FY_START 定时器，改写启用了该时机的产业字段，因此请先配好字段再开始财年。
        """
        y = positive_int(year, "财年 year")
        if y <= 0:
            raise BuilderError("财年 year 必须为正整数")
        return self._register(
            "fiscalYears",
            str(y),
            {"year": y, "status": self._choice(status, COMPETITION_STATUSES, "财年状态")},
            register_name=False,
        )

    def stock_config_set(self, config: dict) -> "CompetitionBuilder":
        """设置股票系统参数（整份替换；不调用则沿用系统默认）。

        键名与 `apps.stock.engine.DEFAULT_STOCK_CONFIG` 一致（limitPct / maxMovePct /
        mmMinQty / mmMaxQty 等）。建议保持 limitPct ≥ maxMovePct、mmMinQty ≤ mmMaxQty。
        """
        if not isinstance(config, dict) or not config:
            raise BuilderError("stock_config 需要非空字典（不设置即沿用系统默认）")
        self.stock_config = dict(config)
        return self

    # ---------------- ② 行业口径（全局资源） ----------------

    def industry_type(
        self,
        code: int,
        name: str,
        *,
        description: str | None = None,
        icon: str | None = None,
    ) -> Ref:
        """登记一个产业类型。

        `code` 是**全局唯一整数**，也是跨比赛复用的自然键：目标库已有同 code 的产业类型时
        导入会复用它（覆盖模式下按本包内容更新名称/描述/图标），不会重复新建。
        """
        c = positive_int(code, "产业类型 code")
        if c <= 0:
            raise BuilderError("产业类型 code 必须为正整数")
        if c in self._industry_by_code:
            raise BuilderError(f"产业类型 code={c} 重复登记")
        ref = self._register(
            "industryTypes",
            name,
            self._opt(code=c, description=description, icon=icon),
        )
        self._industry_by_code[c] = ref
        return ref

    def add_field(
        self,
        industry_type: Any,
        name: str,
        field_key: str,
        *,
        field_type: str = "NUMBER",
        config: dict | None = None,
        default_value: Any = None,
        is_calculated: bool = False,
        graph: dict | None = None,
        sort_order: int = 0,
        visible: bool = True,
        timer_enabled: bool = False,
        timer_trigger: str | None = None,
        timer_value: Any = None,
    ) -> Ref:
        """登记一个产业字段（全局资源，按 (产业类型, fieldKey) 复用/更新）。

        必读约束：
        - 每个产业类型建议保留一个 `field_key="location"` 的「所在地」字段：地图与运费逻辑
          依赖它，区域总览也按它的值（地图节点名）把公司落到具体区域；
        - `is_calculated=True` 必须提供 `graph`（计算图，可用 calc_graph(...) 构造），
          且与 `timer_enabled` **互斥**；
        - `timer_enabled=True` 时 `timer_trigger` 必须是 FY_START / FY_END；
        - `field_key` 是合同、图表、股票绑定的依据，开赛后改名会让既有引用失效。
        """
        it = self._industry_row(industry_type, "产业字段所属产业类型")
        key = require_text(field_key, "字段 fieldKey")
        ftype = self._choice(field_type, FIELD_TYPES, "字段类型 fieldType")
        if is_calculated and timer_enabled:
            raise BuilderError(
                f"字段「{name}」（{key}）不能同时是计算字段与财年定时器字段（二者互斥）"
            )
        if is_calculated and graph is None:
            raise BuilderError(
                f"字段「{name}」（{key}）标记为计算字段，必须提供 graph"
                "（可用 calc_graph(calc_node('add'), calc_node('field', fieldKey='...')) 构造）"
            )
        trigger = None
        if timer_trigger is not None:
            trigger = self._choice(timer_trigger, TIMER_TRIGGERS, "定时器触发时机 timerTrigger")
        if timer_enabled and trigger is None:
            raise BuilderError(f"字段「{name}」（{key}）启用定时器时必须指定 timer_trigger")
        if timer_enabled and timer_value is None:
            raise BuilderError(f"字段「{name}」（{key}）启用定时器时必须指定 timer_value")

        row: dict[str, Any] = {
            "industryTypeCode": it["code"],
            "fieldKey": key,
            "fieldType": ftype,
        }
        if config is not None:
            row["config"] = dict(config)
        if default_value is not None:
            row["defaultValue"] = default_value
        if is_calculated:
            row["isCalculated"] = True
        if graph is not None:
            row["calcGraph"] = graph
        if sort_order:
            row["sortOrder"] = positive_int(sort_order, "字段 sortOrder")
        if not visible:
            row["visible"] = False
        if timer_enabled:
            row["timerEnabled"] = True
            row["timerTrigger"] = trigger
            row["timerValue"] = timer_value

        dedup = f"{it['name']}\u0000{key}"
        if dedup in self._by_name["industryFields"]:
            raise BuilderError(f"产业类型「{it['name']}」下的字段 {key} 重复登记")
        row["_id"] = self._next_id("industryFields")
        row["name"] = require_text(name, "字段名称")
        self._primary["industryFields"].append(row)
        self._by_name["industryFields"][dedup] = row
        return Ref("industryFields", key)

    # ---------------- ③ 参赛主体 ----------------

    def region(self, name: str, *, description: str | None = None) -> Ref:
        """登记一个区域（公司归属、区域总览卡片、消费者需求的维度）。"""
        return self._register("regions", name, self._opt(description=description))

    def company(
        self,
        name: str,
        *,
        industry_type: Any,
        region: Any = None,
        status: str = "ACTIVE",
        field_values: dict | None = None,
    ) -> Ref:
        """登记一家公司（参赛主体）。

        - `industry_type` 必填：决定该公司有哪些字段（缺省会导致字段填报全部无效）；
        - `region` 可填区域引用/名称；本包内没有该区域时，导入侧会按名称自动建一个；
        - `field_values` 形如 {"cash": "5000", "location": "东区港"}，键是产业字段 fieldKey，
          只能填该公司产业类型下**已在本包登记过**的字段（否则导入时会因找不到字段而跳过）；
        - 字段值一律以文本写入（NUMBER 字段也建议传字符串以保留精度）。
        """
        it = self._industry_row(industry_type, "公司所属产业类型")
        row = {
            "industryTypeCode": it["code"],
            "status": self._choice(status, COMPANY_STATUSES, "公司状态"),
        }
        if region is not None:
            row["regionName"] = resolve_ref(region, "regions", "公司所属区域")
        ref = self._register("companies", name, row)
        if field_values:
            if not isinstance(field_values, dict):
                raise BuilderError("company(field_values=...) 必须是 {fieldKey: 值} 字典")
            for field_key, value in field_values.items():
                self.add_field_value(ref, field_key, value)
        return ref

    def add_field_value(self, company: Any, field_key: str, value: Any) -> "CompetitionBuilder":
        """给公司登记一个字段初始值（也可用 company(field_values={...}) 一次写完）。

        导入侧按 (公司, 产业字段) 幂等：目标库已有该字段值时，值不同则更新并把乐观锁
        version +1，值相同则跳过。
        """
        c = self._company_row(company, "公司字段值所属公司")
        it_name = self._industry_name_by_code(c.get("industryTypeCode"))
        key = require_text(field_key, "字段 fieldKey")
        dedup = f"{it_name}\u0000{key}"
        if dedup not in self._by_name["industryFields"]:
            raise BuilderError(
                f"公司「{c['name']}」的字段 {key} 未在本构建器中登记"
                f"（产业类型「{it_name}」下没有该 fieldKey）；"
                "请先用 add_field(...) 登记该字段，否则导入时会因找不到字段而跳过这条值"
            )
        it_row = self._require("industryTypes", it_name, "字段所属产业类型")
        self._add_extra(
            "companyFieldValues",
            {
                "companyId": c["_id"],
                "companyName": c["name"],
                "industryTypeCode": it_row["code"],
                "fieldKey": key,
                "value": "" if value is None else str(value),
            },
        )
        return self

    # ---------------- ⑤ 地理与物流 ----------------

    def node_type(
        self, name: str, *, description: str | None = None, color: str | None = None
    ) -> Ref:
        """登记地图节点类型（城市 / 港口 …）。"""
        return self._register("mapNodeTypes", name, self._opt(description=description, color=color))

    def path_type(
        self, name: str, *, description: str | None = None, color: str | None = None
    ) -> Ref:
        """登记路径类型（公路 / 铁路 / 航线 …）。载具按它决定可通行性。"""
        return self._register("pathTypes", name, self._opt(description=description, color=color))

    def node(
        self,
        name: str,
        node_type: Any,
        *,
        region: str = "",
        x: float = 0,
        y: float = 0,
    ) -> Ref:
        """登记地图节点（原料产地、公司所在地、运输起讫点的落点）。

        - `region` 是节点上的**文本**区域名（MapNode.region），不是外键；区域总览按它聚合；
        - 孤立节点（没有任何连线）在比赛体检里会被提醒，运费/路程计算也会失败，
          记得用 edge() 把节点连起来。
        """
        type_name = resolve_ref(node_type, "mapNodeTypes", "地图节点类型")
        if not self._has("mapNodeTypes", type_name):
            raise BuilderError(
                f"节点「{name}」引用的节点类型「{type_name}」未在本构建器中登记；"
                "请先调用 node_type(...)"
            )
        return self._register(
            "mapNodes",
            name,
            {
                "nodeTypeName": type_name,
                "region": str(region or ""),
                "x": float(x or 0),
                "y": float(y or 0),
            },
        )

    def edge(
        self,
        from_node: Any,
        to_node: Any,
        distance: float,
        path_type: Any,
    ) -> "CompetitionBuilder":
        """登记一条地图连线。

        唯一约束为 (起点节点, 终点节点)：同一对节点只允许一条连线，方向不同视为两条。
        起终点相同的连线会被导入侧跳过并记为 problem，本库直接拦下。
        """
        a = resolve_ref(from_node, "mapNodes", "连线起点节点")
        b = resolve_ref(to_node, "mapNodes", "连线终点节点")
        self._require("mapNodes", a, "连线起点节点")
        self._require("mapNodes", b, "连线终点节点")
        if a == b:
            raise BuilderError(f"地图连线的起终点不能相同：「{a}」")
        p = resolve_ref(path_type, "pathTypes", "连线路径类型")
        self._require("pathTypes", p, "连线路径类型")
        if distance is None:
            raise BuilderError(f"连线「{a} → {b}」必须给出 distance")
        for row in self._extra["mapEdges"]:
            if row["fromNodeName"] == a and row["toNodeName"] == b:
                raise BuilderError(f"地图连线「{a} → {b}」重复登记（同一对节点只允许一条连线）")
        self._add_extra(
            "mapEdges",
            {
                "fromNodeName": a,
                "toNodeName": b,
                "distance": float(distance),
                "pathTypeName": p,
            },
        )
        return self

    # ---------------- ④ 物资与产能 ----------------

    def fuel(self, name: str, price_per_liter: Any = 0) -> Ref:
        """登记一种燃料。载具必须绑定燃料，且燃料被载具 PROTECT 引用（有载具时不能删）。"""
        return self._register(
            "fuels", name, {"pricePerLiter": self._num(price_per_liter, "燃料单价")}
        )

    def material(
        self,
        name: str,
        *,
        origin: str = "",
        carbon_emission_coefficient: float = 0,
        type: str = "NORMAL",
        node_prices: dict | None = None,
    ) -> Ref:
        """登记一种原料（生产链起点）。

        - `origin` 是产地文本（通常填地图节点名）；
        - `node_prices` 形如 {"东区港": 120.5}，键是**已在本包登记的地图节点名或引用**；
          导入侧按节点名重建为 {地图节点id: 价格}，节点不存在的地点价会被丢弃并提示。
        """
        ref = self._register(
            "materials",
            name,
            {
                "origin": str(origin or ""),
                "carbonEmissionCoefficient": float(carbon_emission_coefficient or 0),
                "type": self._choice(type, MATERIAL_TYPES, "原料种类 type"),
            },
        )
        if node_prices:
            self.set_node_prices(ref, node_prices)
        return ref

    def set_node_prices(self, material: Any, prices: dict) -> Ref:
        """设置原料的地点价（键可为地图节点引用或节点名），返回该原料的引用。"""
        m = self._require("materials", resolve_ref(material, "materials", "原料"), "原料")
        if not isinstance(prices, dict):
            raise BuilderError("node_prices 必须是 {地图节点: 价格} 字典")
        by_name: dict[str, Any] = {}
        for node, price in prices.items():
            node_name = resolve_ref(node, "mapNodes", "地点价对应的地图节点")
            self._require("mapNodes", node_name, "地点价对应的地图节点")
            by_name[node_name] = self._num(price, f"原料「{m['name']}」在「{node_name}」的地点价")
        m["nodePricesByName"] = by_name
        return Ref("materials", m["name"])

    def tech(
        self,
        name: str,
        *,
        tier: int = 0,
        research_cost: Any = 0,
        description: str | None = None,
        prerequisites: Iterable[Any] | None = None,
    ) -> Ref:
        """登记一个科技节点（研发对象）。

        `prerequisites` 传前置科技节点（引用/名称）列表，导入侧建为 (节点, 前置) 关系。
        注意不要让前置成环（A 依赖 B、B 又依赖 A），否则研发永远解锁不了（validate 会提醒）。
        """
        row: dict[str, Any] = {
            "tier": positive_int(tier, "科技节点 tier"),
            "researchCost": self._num(research_cost, "研发费用 researchCost"),
        }
        if description is not None:
            row["description"] = description
        ref = self._register("techNodes", name, row)
        for pre in prerequisites or []:
            self.add_prerequisite(ref, pre)
        return ref

    def add_prerequisite(self, node: Any, prerequisite: Any) -> "CompetitionBuilder":
        """追加一条科技前置依赖：node 依赖 prerequisite。

        注意：导入侧的科技前置只按「旧 id」解析（没有按名兜底），因此本库在产出时会
        把节点名换成登记时分配的旧 id，保证跨比赛导入时正确映射到新主键。
        """
        n = resolve_ref(node, "techNodes", "科技节点")
        p = resolve_ref(prerequisite, "techNodes", "前置科技节点")
        n_row = self._require("techNodes", n, "科技节点")
        p_row = self._require("techNodes", p, "前置科技节点")
        if n == p:
            raise BuilderError(f"科技节点「{n}」不能以自身为前置")
        for row in self._extra["techPrerequisites"]:
            if row.get("nodeId") == n_row["_id"] and row.get("prerequisiteId") == p_row["_id"]:
                raise BuilderError(f"科技前置「{n} ← {p}」重复登记")
        self._add_extra(
            "techPrerequisites",
            {"nodeId": n_row["_id"], "prerequisiteId": p_row["_id"]},
        )
        return self

    def line(
        self,
        name: str,
        *,
        price: Any = 0,
        labor_count: int = 0,
        max_per_year: Any = 0,
    ) -> Ref:
        """登记一条生产线（产能档位）。"""
        return self._register(
            "productionLines",
            name,
            {
                "price": self._num(price, "生产线单价"),
                "laborCount": positive_int(labor_count, "生产线上工人数 laborCount"),
                "maxPerYear": self._num(max_per_year, "生产线年产能 maxPerYear"),
            },
        )

    def infrastructure(
        self,
        name: str,
        *,
        footprint: float = 0,
        price: Any = 0,
        activation_price: Any = 0,
        employment_rate_bonus: float = 0,
        population_bonus: float = 0,
        high_quality_population_bonus: float = 0,
        happiness_index_bonus: float = 0,
        per_capita_income_bonus: float = 0,
        carbon_reduction_bonus: float = 0,
    ) -> Ref:
        """登记一项基建（价格 / 占地 / 各项加成，合同各聚合端点的数据来源）。"""
        return self._register(
            "infrastructures",
            name,
            {
                "footprint": float(footprint or 0),
                "price": self._num(price, "基建单价"),
                "activationPrice": self._num(activation_price, "基建启用费用"),
                "employmentRateBonus": float(employment_rate_bonus or 0),
                "populationBonus": float(population_bonus or 0),
                "highQualityPopulationBonus": float(high_quality_population_bonus or 0),
                "happinessIndexBonus": float(happiness_index_bonus or 0),
                "perCapitaIncomeBonus": float(per_capita_income_bonus or 0),
                "carbonReductionBonus": float(carbon_reduction_bonus or 0),
            },
        )

    def warehouse(self, name: str, type: str, *, capacity: Any = 0, price: Any = 0) -> Ref:
        """登记一种仓库。type 取 MATERIAL / PART / PRODUCT / FUEL（四种都建议覆盖）。"""
        return self._register(
            "warehouses",
            name,
            {
                "type": self._choice(type, WAREHOUSE_TYPES, "仓库种类 type"),
                "capacity": self._num(capacity, "仓库容量"),
                "price": self._num(price, "仓库单价"),
            },
        )

    def part(
        self,
        name: str,
        *,
        materials: dict | None = None,
        tech: Iterable[Any] | None = None,
    ) -> Ref:
        """登记一个零件。

        `materials` 形如 {原料: 数量系数}；`tech` 是所需科技节点列表。
        配比缺失会让生产计算得到空字典，因此零件建议都配齐配比。
        """
        ref = self._register("parts", name, {})
        for material, ratio in (materials or {}).items():
            self.add_material_ratio(ref, material, ratio)
        for node in tech or []:
            self.add_tech_requirement(ref, node)
        return ref

    def add_material_ratio(self, part: Any, material: Any, ratio: Any) -> "CompetitionBuilder":
        """追加零件-原料配比。"""
        p = self._require("parts", resolve_ref(part, "parts", "零件"), "零件")
        m = self._require("materials", resolve_ref(material, "materials", "原料"), "原料")
        for row in self._extra["partMaterials"]:
            if row["partName"] == p["name"] and row["materialName"] == m["name"]:
                raise BuilderError(f"零件配比「{p['name']} ← {m['name']}」重复登记")
        self._add_extra(
            "partMaterials",
            {
                "partName": p["name"],
                "materialName": m["name"],
                "ratio": self._num(ratio, "配比系数"),
            },
        )
        return self

    def product(
        self,
        name: str,
        *,
        parts: dict | None = None,
        tech: Iterable[Any] | None = None,
    ) -> Ref:
        """登记一个产品（消费者需求与销售的对象）。

        `parts` 形如 {零件: 数量系数}；`tech` 是所需科技节点列表。
        """
        ref = self._register("products", name, {})
        for part, ratio in (parts or {}).items():
            self.add_part_ratio(ref, part, ratio)
        for node in tech or []:
            self.add_tech_requirement(ref, node)
        return ref

    def add_part_ratio(self, product: Any, part: Any, ratio: Any) -> "CompetitionBuilder":
        """追加产品-零件配比。"""
        pr = self._require("products", resolve_ref(product, "products", "产品"), "产品")
        pa = self._require("parts", resolve_ref(part, "parts", "零件"), "零件")
        for row in self._extra["productParts"]:
            if row["productName"] == pr["name"] and row["partName"] == pa["name"]:
                raise BuilderError(f"产品配比「{pr['name']} ← {pa['name']}」重复登记")
        self._add_extra(
            "productParts",
            {
                "productName": pr["name"],
                "partName": pa["name"],
                "ratio": self._num(ratio, "配比系数"),
            },
        )
        return self

    def add_tech_requirement(self, item: Any, tech_node: Any) -> "CompetitionBuilder":
        """给零件或产品追加一条科技需求（item 传零件或产品的引用/名称）。"""
        node = resolve_ref(tech_node, "techNodes", "科技需求节点")
        self._require("techNodes", node, "科技需求节点")
        resource: str | None = None
        name = ""
        for candidate in ("parts", "products"):
            try:
                candidate_name = resolve_ref(item, candidate, "零件或产品")
            except BuilderError:
                continue
            if candidate_name in self._by_name[candidate]:
                resource, name = candidate, candidate_name
                break
        if resource is None:
            raise BuilderError(
                "add_tech_requirement 的第一个参数必须是本构建器登记过的零件或产品引用/名称"
            )
        extra_res = "partTechRequirements" if resource == "parts" else "productTechRequirements"
        field = "partName" if resource == "parts" else "productName"
        for row in self._extra[extra_res]:
            if row[field] == name and row["techNodeName"] == node:
                return self  # 幂等：同一条科技需求不重复登记
        self._add_extra(extra_res, {field: name, "techNodeName": node})
        return self

    def vehicle(
        self,
        name: str,
        *,
        fuel: Any,
        path_types: Iterable[Any] | None = None,
        fuel_consumption_per_km: float = 0,
        max_cargo: float = 0,
        price: Any = 0,
        carbon_emission: float = 0,
    ) -> Ref:
        """登记一种载具。

        `fuel` 必填（模型是 PROTECT 外键）；`path_types` 是可通行的路径类型，
        不勾选任何路径类型时该载具的运输路径校验会失败，建议传全。
        """
        f = self._require("fuels", resolve_ref(fuel, "fuels", "载具燃料"), "载具燃料")
        ref = self._register(
            "vehicles",
            name,
            {
                "fuelName": f["name"],
                "fuelConsumptionPerKm": float(fuel_consumption_per_km or 0),
                "maxCargo": float(max_cargo or 0),
                "price": self._num(price, "载具单价"),
                "carbonEmission": float(carbon_emission or 0),
            },
        )
        for path in path_types or []:
            self.add_path_type(ref, path)
        return ref

    def add_path_type(self, vehicle: Any, path_type: Any) -> "CompetitionBuilder":
        """给载具追加一种可通行路径类型。"""
        v = self._require("vehicles", resolve_ref(vehicle, "vehicles", "载具"), "载具")
        p = self._require("pathTypes", resolve_ref(path_type, "pathTypes", "路径类型"), "路径类型")
        for row in self._extra["vehiclePathTypes"]:
            if row["vehicleName"] == v["name"] and row["pathTypeName"] == p["name"]:
                return self
        self._add_extra("vehiclePathTypes", {"vehicleName": v["name"], "pathTypeName": p["name"]})
        return self

    # ---------------- ⑥ 科技与需求 ----------------

    def demand(
        self,
        region: str,
        product: Any,
        quantity: int,
        *,
        note: str | None = None,
    ) -> "CompetitionBuilder":
        """登记一条消费者需求（区域 × 产品 × 数量）。

        - `region` 是文本区域名（模型列是字符串），建议与区域名保持一致；
        - 导入侧按 (比赛, 区域, 产品类型, 数量) 幂等去重，因此「改需求量」会被视为新增一条；
        - 产品必须在本包登记过，否则玩家无法交付（本库直接拦下）。
        """
        r = require_text(region, "需求区域 region")
        p = self._require("products", resolve_ref(product, "products", "需求产品"), "需求产品")
        row = {
            "region": r,
            "productType": p["name"],
            "productName": p["name"],
            "quantity": positive_int(quantity, "需求量 quantity"),
        }
        if note is not None:
            row["note"] = note
        self._add_extra("consumerDemands", row)
        return self

    # ---------------- ⑦ 市场与规则 ----------------

    def contract_type(
        self,
        key: str,
        name: str,
        *,
        description: str | None = None,
        party_roles: Sequence[dict] | None = None,
        input_schema: Sequence[dict] | None = None,
        effects: Sequence[dict] | None = None,
        conditions: Sequence[dict] | None = None,
        graph: dict | None = None,
        enabled: bool = True,
    ) -> Ref:
        """登记一个合同类型（全局资源，按 key 复用/更新）。

        四个 JSON 结构沿用合同引擎的既有口径（`apps/contracts/engine.py`，字段名不变）：
        - `party_roles`  [{role, label, selectable?, isHost?}]               参与方角色
        - `input_schema` [{key, label, type, required?, default?}]           需要填写的输入项
        - `effects`      [{kind:"FIELD", party, fieldKey, op:"ADD|SUB|SET", value}]  落账效果
        - `conditions`   [{kind:"FIELD", party, fieldKey, op:"GTE", value}]          前置检查
        `graph` 是可视化图结构（前端「可视化新建」产出），纯代码场景通常留空。
        """
        k = require_text(key, "合同类型 key")
        if k in self._contract_type_keys:
            raise BuilderError(f"合同类型 key={k} 重复登记")
        cname = require_text(name, "合同类型名称")
        row: dict[str, Any] = {"key": k, "name": cname}
        if description is not None:
            row["description"] = description
        if party_roles:
            row["partyRoles"] = list(party_roles)
        if input_schema:
            row["inputSchema"] = list(input_schema)
        if effects:
            row["effects"] = list(effects)
        if conditions:
            row["conditions"] = list(conditions)
        if graph is not None:
            row["graph"] = graph
        if not enabled:
            row["enabled"] = False
        ref = self._register(
            "contractTypes",
            k,
            row,
        )
        self._contract_type_keys.add(k)
        # _register 会把 name 设成自然键（合同类型是 key），登记后补回真实类型名
        self._by_name["contractTypes"][k]["name"] = cname
        return ref

    def contract(
        self,
        name: str | None = None,
        *,
        contract_type: Any,
        parties: Sequence[dict] | None = None,
        inputs: dict | None = None,
        status: str = "DRAFT",
    ) -> Ref:
        """登记一个合同实例（比赛级预设合同）。

        - `contract_type` 传 contract_type() 的返回值或 key 字符串；
        - `parties`：[{"role": "买方", "company": <公司引用/名>, "contractNumber": "..."}]，
          导入侧按公司名兜底解析公司，公司不在本包时该方公司会被置空并提示；
        - `status` 默认 DRAFT（只预置、不落账）；EXECUTED 会立刻改写公司字段，
          开赛前请保持草稿；
        - `name` 缺省取**合同类型名**（与导入侧的判重口径一致）；同一合同类型下名称必须唯一。
        """
        ct_key = self._contract_type_key(contract_type)
        ct_row = self._by_name["contractTypes"][ct_key]
        cname = require_text(ct_row.get("name") or ct_key, "合同名称") if name is None else require_text(name, "合同名称")
        dedup = f"{ct_key}\u0000{cname}"
        if dedup in self._by_name["contractInstances"]:
            raise BuilderError(
                f"合同「{cname}」（类型 {ct_key}）重复登记；同一合同类型下名称必须唯一"
            )
        party_rows: list[dict] = []
        for item in parties or []:
            if not isinstance(item, dict):
                raise BuilderError("contract(parties=...) 的每项必须是字典")
            role = require_text(item.get("role"), "参与方 role")
            if item.get("company") is None:
                raise BuilderError(f"合同「{cname}」的参与方「{role}」必须指定 company")
            c = self._require(
                "companies",
                resolve_ref(item["company"], "companies", "参与方公司"),
                "参与方公司",
            )
            entry: dict[str, Any] = {"role": role, "companyName": c["name"]}
            if item.get("isHost"):
                entry["isHost"] = True
            if item.get("contractNumber"):
                entry["contractNumber"] = str(item["contractNumber"])
            party_rows.append(entry)
        row: dict[str, Any] = {
            "contractTypeKey": ct_key,
            "status": self._choice(status, CONTRACT_STATUSES, "合同状态"),
            "parties": party_rows,
            "inputs": dict(inputs or {}),
            "_id": self._next_id("contractInstances"),
            "name": cname,
        }
        self._primary["contractInstances"].append(row)
        self._by_name["contractInstances"][dedup] = row
        return Ref("contractInstances", cname)

    def _contract_type_key(self, ref: Any) -> str:
        key = resolve_ref(ref, "contractTypes", "合同类型")
        if key not in self._contract_type_keys:
            raise BuilderError(
                f"合同引用的合同类型「{key}」未在本构建器中登记（请先调用 contract_type(...)）"
            )
        return key

    def stock(
        self,
        code: str,
        name: str,
        *,
        company: Any = None,
        total_shares: Any = 0,
        init_net_profit: Any = 0,
        init_price: Any = 0,
        current_price: Any = None,
        industry_pe: float = 0,
        current_carbon: float = 0,
        industry_avg_carbon: float = 0,
        happiness: float = 0,
        round: int = 0,
        carbon_field_ref: str | None = None,
        happiness_field_ref: str | None = None,
        industry_avg_carbon_refs: str | None = None,
        pb_company: Any = None,
        pb_random: float | None = None,
    ) -> Ref:
        """登记一只股票（按 code 幂等，同比赛内 code 唯一）。

        说明：
        - `current_price` 不填时导入侧取 `init_price`；
        - `carbon_field_ref` / `happiness_field_ref` / `industry_avg_carbon_refs` 是
          「区域总览卡片」引用字符串（形如 '{"region":"东区","cardId":"..."}'），
          需先用 card() 建好卡片；本库原样透传，不做解析；
        - `pb_company` 是行业 PE 联动公司；字段 id 绑定（pbFieldId）跨比赛不搬运。
        """
        c = require_text(code, "股票代码 code")
        n = require_text(name, "股票名称")
        row: dict[str, Any] = {
            "code": c,
            "totalShares": self._num(total_shares, "总股本 totalShares"),
            "initNetProfit": self._num(init_net_profit, "初始净利润 initNetProfit"),
            "initPrice": self._num(init_price, "初始价格 initPrice"),
            "currentPrice": self._num(
                init_price if current_price is None else current_price, "当前价格 currentPrice"
            ),
            "industryPe": float(industry_pe or 0),
            "currentCarbon": float(current_carbon or 0),
            "industryAvgCarbon": float(industry_avg_carbon or 0),
            "happiness": float(happiness or 0),
            "round": positive_int(round, "股票轮次 round"),
        }
        if company is not None:
            cm = self._require(
                "companies", resolve_ref(company, "companies", "股票关联公司"), "股票关联公司"
            )
            row["companyName"] = cm["name"]
        if carbon_field_ref is not None:
            row["carbonFieldRef"] = carbon_field_ref
        if happiness_field_ref is not None:
            row["happinessFieldRef"] = happiness_field_ref
        if industry_avg_carbon_refs is not None:
            row["industryAvgCarbonRefs"] = industry_avg_carbon_refs
        if pb_company is not None:
            pbc = self._require(
                "companies", resolve_ref(pb_company, "companies", "PE 联动公司"), "PE 联动公司"
            )
            # 导入侧只认 pbCompanyId，且要用「归档里的旧 id」查映射表，故此处换成公司旧 id
            row["pbCompanyId"] = pbc["_id"]
        if pb_random is not None:
            row["pbRandom"] = float(pb_random)
        # _register 会把行的 name 设成自然键（股票是 code），登记后补回真实股票名
        ref = self._register("stocks", c, row)
        self._by_name["stocks"][ref.name]["name"] = n
        return ref

    def account(
        self,
        name: str,
        *,
        owner: Any = None,
        username: str | None = None,
        cash_balance: Any = 1_000_000,
    ) -> Ref:
        """登记一个资金账户（玩家下单的资金来源）。

        - 公司账户传 `owner=<公司引用>`；用户账户传 `username="<用户名>"`（需先 user() 建账号）；
        - `bindFieldId`（现金跟随产业字段）依赖具体字段 id，跨比赛不搬运，本库不设该列。
        """
        aname = require_text(name, "资金账户名称")
        if owner is not None and username is not None:
            raise BuilderError(f"资金账户「{aname}」只能二选一：owner=<公司> 或 username=<用户名>")
        if owner is None and not username:
            raise BuilderError(f"资金账户「{aname}」必须指定 owner=<公司> 或 username=<用户名>")
        row: dict[str, Any] = {"cashBalance": self._num(cash_balance, "账户现金 cashBalance")}
        if owner is not None:
            c = self._require(
                "companies", resolve_ref(owner, "companies", "账户归属公司"), "账户归属公司"
            )
            row["ownerType"] = "COMPANY"
            row["companyName"] = c["name"]
        else:
            uname = require_text(username, "账户归属用户名")
            self._require("users", uname, "账户归属用户")
            row["ownerType"] = "USER"
            row["username"] = uname
        return self._register("stockFundsAccounts", aname, row)

    def card(
        self,
        region: Any,
        company: Any,
        field_key: str,
        *,
        display_name: str | None = None,
        zone: str | None = None,
        card_id: str | None = None,
    ) -> "CompetitionBuilder":
        """给区域登记一张总览卡片 {id, displayName, companyId, industryFieldId, zone?}。

        重要：卡片里的 `industryFieldId` 是**数据库主键**，而产业字段是全局资源、跨比赛复用
        （导入侧按 (产业类型 code, fieldKey) 找已有字段、不新建）。纯代码建包时无法凭空得知该 id：
        - 若该字段已在目标库存在，用 `resolve_field_ids(导出的归档)` 从真实归档里回填；
        - 若尚未存在，先导入一次（字段会被建出来），导出后再回填、再导一次。
        未回填时本库写入占位值 0，`validate()` 会给出提醒。

        卡片 id 缺省时按「区域-公司-字段」生成稳定字符串，保证重复建包结果一致。
        """
        r = self._require("regions", resolve_ref(region, "regions", "卡片所属区域"), "区域")
        c = self._require("companies", resolve_ref(company, "companies", "卡片所属公司"), "公司")
        key = require_text(field_key, "卡片字段 fieldKey")
        it_name = self._industry_name_by_code(c.get("industryTypeCode"))
        dedup = f"{it_name}\u0000{key}"
        if dedup not in self._by_name["industryFields"]:
            raise BuilderError(
                f"区域「{r['name']}」的卡片引用了未登记的产业字段 {key}（产业类型「{it_name}」）"
            )
        card_row: dict[str, Any] = {
            "id": card_id or f"{r['name']}-{c['name']}-{key}",
            "displayName": display_name or key,
            "companyName": c["name"],
            "industryFieldId": int(self._field_ids.get((it_name, key), 0)),
        }
        if zone is not None:
            card_row["zone"] = zone
        owner = self._extra_row_by("overviewCards", "regionName", r["name"])
        if owner is None:
            owner = self._add_extra("overviewCards", {"regionName": r["name"], "cards": []})
        owner["cards"].append(card_row)
        self._cards.append((r["name"], card_row, it_name, key))
        return self

    def _extra_row_by(self, resource: str, field: str, value: str) -> dict | None:
        for row in self._extra[resource]:
            if row.get(field) == value:
                return row
        return None

    def message(
        self,
        title: str,
        content: str = "",
        *,
        to_all: bool = True,
        to_users: Iterable[str] | None = None,
        sender: str | None = None,
    ) -> "CompetitionBuilder":
        """登记一条比赛内消息。

        - `to_all=True` 面向全体；也可 `to_users=["player01"]` 指定收件人（需先 user() 建账号）；
        - `sender` 是发布者用户名；不填时导入侧用「当前操作账号」，找不到则回退任一超管；
        - 注意：账号在导入顺序里排在消息之后，因此**单次导入**中指定收件人无法落地
          （导入侧会给出提示）；要保留指定收件人请分两次导入（先账号，后消息）。
        """
        t = require_text(title, "消息标题")
        unames: list[str] = []
        for uname in to_users or []:
            u = require_text(uname, "消息收件人用户名")
            self._require("users", u, "消息收件人用户名")
            if u not in unames:
                unames.append(u)
        row: dict[str, Any] = {
            "title": t,
            "content": str(content or ""),
            "targetsAll": bool(to_all),
        }
        if unames:
            row["targetUsernames"] = unames
        if sender:
            row["senderUsername"] = require_text(sender, "消息发布者用户名")
        self._add_extra("messages", row)
        return self

    # ---------------- ⑧ 账号与权限 ----------------

    def user(
        self,
        username: str,
        *,
        role: str = "PLAYER",
        display_name: str | None = None,
        company_scopes: Iterable[Any] | None = None,
        view_company_scopes: Iterable[Any] | None = None,
        contract_view_company_scopes: Iterable[Any] | None = None,
        stock_company_scopes: Iterable[Any] | None = None,
        permissions: Iterable[str] | None = None,
        is_active: bool = True,
    ) -> Ref:
        """登记一个参赛账号。

        重点：四套公司范围（companyScopes / viewCompanyScopes / contractViewCompanyScopes /
        stockCompanyScopes）为空会导致该账号「登录后什么都看不到」，玩家账号至少要给公司范围。

        导入侧语义（与手工导入一致）：
        - 用户名全局唯一：目标库已有同名账号时不覆盖密码、不抢比赛归属，只把公司范围并入；
        - 新建账号密码为随机值且强制首次登录改密，需超管重置后才能交付选手。
        """
        uname = require_text(username, "用户名")
        row: dict[str, Any] = {"role": self._choice(role, USER_ROLES, "账号角色")}
        if display_name is not None:
            row["displayName"] = display_name
        if permissions:
            row["permissions"] = list(permissions)
        if not is_active:
            row["isActive"] = False
        user_ref = self._register("users", uname, row)
        for param, field, names_field in _SCOPE_FIELDS:
            self._set_scope(user_ref, field, names_field, locals()[param])
        return user_ref

    def _set_scope(self, user_ref: Ref, field: str, names_field: str, scopes: Any) -> None:
        names = refs_of(scopes, "companies", f"账号「{user_ref.name}」的 {field}")
        for name in names:
            self._require("companies", name, f"账号「{user_ref.name}」的 {field}")
        if not names:
            return
        row = self._require("users", user_ref.name, "账号")
        row[field] = names
        row[names_field] = names

    # ---------------- 产出 ----------------

    def build(self, *, scope: str | None = None, resources: Iterable[str] | None = None) -> dict:
        """产出比赛准备归档 JSON（结构与 archive.build_export 一致）。

        - `scope`：只产出某个分组（如 "company"）；
        - `resources`：更细粒度地只产出若干资源名（如 ["companies", "companyFieldValues"]）；
        - 名称重复、引用缺失、必填缺失等问题都会在此阶段抛 BuilderError（不会污染数据库）。
        """
        if scope is not None and scope != SCOPE_ALL and scope not in SCOPES:
            raise BuilderError(f"未知分组 scope={scope!r}；可选 {list(SCOPES)} 或 '{SCOPE_ALL}'")
        if resources is not None:
            wanted = set(resources)
            unknown = sorted(r for r in wanted if r not in RESOURCE_ORDER)
            if unknown:
                raise BuilderError(f"未知资源名：{', '.join(unknown)}")
        elif scope is not None and scope != SCOPE_ALL:
            wanted = set(SCOPES[scope])
        else:
            wanted = set(RESOURCE_ORDER)

        self.validate()

        out: dict[str, Any] = {}
        for res in RESOURCE_ORDER:
            if res not in wanted:
                continue
            rows = self._rows_of(res)
            if not rows:
                continue
            # 列名自检：拼错的字段名会让导入侧 .get 取不到而静默用默认值，这里直接拦下
            from .schema import verify_rows

            verify_rows(res, rows)
            out[res] = {
                "label": RESOURCE_LABELS.get(res, res),
                "count": len(rows),
                "rows": rows,
            }

        return {
            "schemaVersion": SCHEMA_VERSION,
            "generator": GENERATOR,
            "exportedAt": _now_text(),
            "scope": scope if (scope and scope != SCOPE_ALL) else SCOPE_ALL,
            "scopeLabel": _scope_label(scope),
            "sourceCompetition": {"id": None, "name": self.name},
            "resources": out,
        }

    def _rows_of(self, resource: str) -> list[dict]:
        """取某资源的全部行（主记录 + 子记录）。"""
        if resource == "competitionMeta":
            row: dict[str, Any] = {"name": self.name, "status": self.status}
            if self.map_background is not None:
                row["mapBackground"] = self.map_background
            return [row]
        if resource == "stockConfig":
            if self.stock_config is None:
                return []
            return [{"isDefault": False, "custom": self.stock_config}]
        if resource == "messages":
            # 指定收件人换成「归档里的旧账号 id」：导入侧只认 targetUserIds
            rows = []
            for row in self._extra["messages"]:
                copied = dict(row)
                names = copied.pop("targetUsernames", None)
                if names:
                    copied["targetUserIds"] = [
                        self._by_name["users"][n]["_id"]
                        for n in names
                        if n in self._by_name["users"]
                    ]
                rows.append(copied)
            return rows
        if resource == "users":
            rows = []
            for row in self._primary["users"]:
                copied = dict(row)
                copied.pop("name", None)  # users 的自然键是 username，不需要 name 列
                copied["username"] = row["name"]
                rows.append(copied)
            return rows
        return list(self._primary[resource]) + list(self._extra[resource])

    def to_json(self, *, indent: int = 2, scope: str | None = None) -> str:
        """产出归档 JSON 文本（可直接导入）。"""
        return json.dumps(self.build(scope=scope), ensure_ascii=False, indent=indent, default=str)

    def save(self, path: str | Path, *, indent: int = 2, scope: str | None = None) -> Path:
        """把归档 JSON 写到文件。"""
        target = Path(path)
        if target.parent and str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(indent=indent, scope=scope), encoding="utf-8")
        return target

    # ---------------- 校验与回填 ----------------

    def validate(self) -> list[str]:
        """自检并返回提醒列表（有硬错误则抛 BuilderError）。

        覆盖：公司产业类型、location 字段、地图孤立节点、科技前置成环、载具通行路径、
        概览卡片字段 id 占位、消息指定收件人的导入顺序限制。硬性引用缺失在各登记方法中即时拦截。
        """
        warnings: list[str] = []

        # 1) 公司必须有产业类型（_register 已保证，这里兜底防手改内部结构）
        for row in self._primary["companies"]:
            if row.get("industryTypeCode") is None:
                raise BuilderError(f"公司「{row['name']}」未绑定产业类型")

        # 2) 每个产业类型的 location 字段
        for it in self._primary["industryTypes"]:
            if not any(
                f.get("industryTypeCode") == it["code"] and f.get("fieldKey") == "location"
                for f in self._primary["industryFields"]
            ):
                warnings.append(
                    f"产业类型「{it['name']}」没有 fieldKey='location' 的「所在地」字段："
                    "地图与运费逻辑依赖它，区域总览也无法把公司落到区域"
                )

        # 3) 地图孤立节点
        if self._primary["mapNodes"]:
            connected: set[str] = set()
            for e in self._extra["mapEdges"]:
                connected.add(e["fromNodeName"])
                connected.add(e["toNodeName"])
            for n in self._primary["mapNodes"]:
                if n["name"] not in connected:
                    warnings.append(
                        f"地图节点「{n['name']}」没有任何连线，不可达（运费/路程计算会失败）"
                    )

        # 4) 科技前置成环
        node_name_by_id = {n["_id"]: n["name"] for n in self._primary["techNodes"]}
        cycle = _find_cycle(
            [n["name"] for n in self._primary["techNodes"]],
            [
                (
                    node_name_by_id.get(p.get("prerequisiteId"), "?"),
                    node_name_by_id.get(p.get("nodeId"), "?"),
                )
                for p in self._extra["techPrerequisites"]
            ],
        )
        if cycle:
            warnings.append("科技前置存在环路：" + " → ".join(cycle) + "，这些节点永远无法解锁")

        # 5) 载具可通行路径
        path_types_of: dict[str, int] = {}
        for r in self._extra["vehiclePathTypes"]:
            path_types_of[r["vehicleName"]] = path_types_of.get(r["vehicleName"], 0) + 1
        for v in self._primary["vehicles"]:
            if not path_types_of.get(v["name"]):
                warnings.append(f"载具「{v['name']}」没有可通行路径类型，运输路径校验会失败")

        # 6) 概览卡片字段 id 占位
        placeholders = [f"{region}/{card['displayName']}" for region, card, _t, _k in self._cards
                        if not card.get("industryFieldId")]
        if placeholders:
            warnings.append(
                f"区域总览卡片的 industryFieldId 仍是占位值 0（共 {len(placeholders)} 张："
                f"{'、'.join(placeholders[:5])}）；请用 resolve_field_ids(已有归档) 回填真实字段 id，"
                "否则卡片取不到值"
            )

        # 7) 消息指定收件人的导入顺序限制
        if _USERS_IMPORTED_AFTER_MESSAGES:
            targeted = [r["title"] for r in self._extra["messages"] if r.get("targetUserIds")]
            if targeted:
                warnings.append(
                    f"有 {len(targeted)} 条消息使用了指定收件人，但账号在导入顺序中排在消息之后，"
                    "单次导入无法落地收件人（导入侧会提示）；如需保留，请先导入账号再单独导入消息"
                )
        return warnings

    def resolve_field_ids(self, reference_archive: dict) -> "CompetitionBuilder":
        """用一份**已导出的**归档回填总览卡片所需的 industryFieldId。

        用法：先对目标库导出一次（GET /api/preparations/archive/export?scope=industry），
        把 JSON 解析成 dict 传给本方法；本库按 (产业类型 code, fieldKey) 在参照归档里
        查到真实字段 id 并写回所有卡片。这样纯代码建包也能正确引用全局产业字段。

        找不到对应字段时抛 BuilderError（而不是留下占位 0 让卡片静默失效）。
        本方法可以反复调用（例如改了产业字段后再回填一次），也可在 card() 之前调用。
        """
        if not isinstance(reference_archive, dict):
            raise BuilderError("resolve_field_ids 需要一份归档 dict（导出 JSON 的解析结果）")
        resources = reference_archive.get("resources") or {}
        type_rows = (resources.get("industryTypes") or {}).get("rows") or []
        field_rows = (resources.get("industryFields") or {}).get("rows") or []
        # 参照归档可能是老格式（字段行里只有 industryTypeId），做一层兼容
        code_of_type_id = {t.get("_id"): t.get("code") for t in type_rows}

        resolved: dict[tuple[str, str], int] = {}
        for row in field_rows:
            code = row.get("industryTypeCode")
            if code is None and row.get("industryTypeId") is not None:
                code = code_of_type_id.get(row["industryTypeId"])
            ref = self._industry_by_code.get(code)
            key = row.get("fieldKey")
            fid = row.get("_id")
            if ref is None or not key or fid is None:
                continue
            resolved[(ref.name, str(key))] = int(fid)
        if not resolved:
            raise BuilderError(
                "参照归档里没有可用的产业字段（resources.industryFields.rows 为空）；"
                "请确认导出的是包含「行业口径」分组的归档，且这些字段已在目标库存在"
            )

        # 只要求「本构建器实际用到的字段」都能解析到，其它全局字段缺失不算问题
        used = {(type_name, key) for _region, _card, type_name, key in self._cards}
        missing = sorted(f"{t}/{k}" for t, k in used if (t, k) not in resolved)
        if missing:
            raise BuilderError(
                "参照归档里找不到这些产业字段的 id：" + "、".join(missing[:8])
                + "；请确认这些字段已在目标库存在（即已导入过「行业口径」分组）"
            )

        self._field_ids.update(resolved)
        self._backfill_card_field_ids()
        return self

    def _backfill_card_field_ids(self) -> None:
        """把已登记卡片里的 industryFieldId 刷成当前已知的真实 id。"""
        for _region, card, type_name, key in self._cards:
            fid = self._field_ids.get((type_name, key))
            if fid:
                card["industryFieldId"] = int(fid)

    # ---------------- 只读视图（便于脚本与测试断言） ----------------

    def rows(self, resource: str) -> list[dict]:
        """取某资源的全部行（副本），便于脚本自行检查产出。"""
        if resource not in RESOURCE_ORDER:
            raise BuilderError(f"未知资源名：{resource}")
        return [dict(r) for r in self._rows_of(resource)]

    def names(self, resource: str) -> list[str]:
        """取某资源已登记的名称列表（industryFields 为 (产业类型, fieldKey) 元组串）。"""
        return list(self._by_name.get(resource, {}).keys())

    def __repr__(self) -> str:  # pragma: no cover - 仅调试可读性
        counts = {r: len(self._rows_of(r)) for r in RESOURCE_ORDER}
        shown = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
        return f"CompetitionBuilder({self.name!r}, {shown})"


# ==================== 模块级小工具 ====================


def _now_text() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _scope_label(scope: str | None) -> str:
    if not scope or scope == SCOPE_ALL:
        return "全部准备数据"
    return {
        "competition": "① 比赛基础",
        "industry": "② 行业口径",
        "company": "③ 参赛主体",
        "supply": "④ 物资与产能",
        "geo": "⑤ 地理与物流",
        "tech": "⑥ 科技与需求",
        "market": "⑦ 市场与规则",
        "access": "⑧ 账号与权限",
    }.get(scope, scope)


def _find_cycle(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> list[str] | None:
    """在「prerequisite → node」有向图上找环，返回环上的节点路径（无环返回 None）。"""
    graph: dict[str, list[str]] = {n: [] for n in nodes}
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
        graph.setdefault(dst, [])
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in graph.get(node, []):
            if color.get(nxt, WHITE) == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color.get(nxt, WHITE) == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in list(graph):
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None
