"""归档资源列定义（自描述表）。

本表是「仓库里现成 JSON / 手写建包脚本」的字段字典，列名与
`apps.preparation.archive` 的 `_exp_*` 导出函数一一对应。

用途有三个：
1. 写脚本时查字段（也可 `python manage.py build_competition --schema <资源>` 打印）；
2. 自动检测拼错列名：`verify_rows()` 会比对实际产出行，出现表里没有的列立即报错，
   避免「字段名打错 → 导入侧 .get 取不到 → 静默用默认值」这类最难查的问题；
3. 生成文档（`schema_markdown()`）。

列属性说明：
- `required=True`   —— 导入侧缺了会跳过该行或产生错误数据；
- `key=True`        —— 自然键（导入侧按它去重复用已有记录）；
- `ref="资源名"`     —— 该列是「对被引用资源旧 id 的引用」，由建包库按名称自动填；
- `aux=True`        —— 辅助列（导入侧用于跨分组按名兜底解析，不是模型字段）；
- `note`            —— 取值口径或注意事项。
"""
from __future__ import annotations

import dataclasses
from typing import Any

from .types import BuilderError


@dataclasses.dataclass(frozen=True)
class Column:
    """归档里的一列。"""

    name: str
    note: str = ""
    required: bool = False
    key: bool = False
    ref: str | None = None
    aux: bool = False


@dataclasses.dataclass(frozen=True)
class ResourceSchema:
    """一类资源的列定义。"""

    resource: str
    label: str
    builder_methods: tuple[str, ...]
    columns: tuple[Column, ...]
    notes: tuple[str, ...] = ()

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "label": self.label,
            "builderMethods": list(self.builder_methods),
            "columns": [dataclasses.asdict(c) for c in self.columns],
            "notes": list(self.notes),
        }


_RESOURCE_SCHEMAS: tuple[ResourceSchema, ...] = (
    ResourceSchema(
        resource="competitionMeta",
        label="比赛名称与状态",
        builder_methods=("CompetitionBuilder(name, status=..., map_background=...)",),
        columns=(
            Column("name", "比赛名称（导入**不会**改写目标比赛名，仅提示差异）"),
            Column("status", "ACTIVE / CLOSED；导入会同步目标比赛状态"),
            Column("mapBackground", "地图背景图 {url, filename, width, height}；只在目标为空时写入"),
        ),
        notes=("一场比赛只产出一行；比赛名不会被导入覆盖（避免全局重名冲突）。",),
    ),
    ResourceSchema(
        resource="fiscalYears",
        label="财年",
        builder_methods=("fiscal_year(year, status=...)",),
        columns=(
            Column("year", "财年年份（正整数）", required=True, key=True),
            Column("status", "ACTIVE / CLOSED"),
        ),
        notes=(
            "导入按 (比赛, 年份) 幂等；新建或将状态改为 ACTIVE 会触发 FY_START 定时器，"
            "改写启用了该时机的产业字段。",
        ),
    ),
    ResourceSchema(
        resource="stockConfig",
        label="股票系统参数",
        builder_methods=("stock_config_set(config)",),
        columns=(
            Column("isDefault", "true 表示回到系统默认（不设置即为默认）"),
            Column("custom", "自定义参数对象，键同 apps.stock.engine.DEFAULT_STOCK_CONFIG"),
        ),
        notes=("不调用 stock_config_set 时本资源完全不产出，目标比赛沿用原配置。",),
    ),
    ResourceSchema(
        resource="industryTypes",
        label="产业类型（全局）",
        builder_methods=("industry_type(code, name, description=..., icon=...)",),
        columns=(
            Column("code", "全局唯一整数，跨比赛复用的自然键", required=True, key=True),
            Column("name", "产业类型名称"),
            Column("description", "描述"),
            Column("icon", "图标"),
        ),
        notes=("全局资源：目标库已有同 code 时复用并（覆盖模式下）更新，不会重复新建。",),
    ),
    ResourceSchema(
        resource="industryFields",
        label="产业字段（全局）",
        builder_methods=("add_field(industry_type, name, field_key, ...)",),
        columns=(
            Column("industryTypeCode", "所属产业类型 code", required=True),
            Column("fieldKey", "字段键（合同/图表/股票绑定依据）", required=True, key=True),
            Column("name", "字段显示名"),
            Column("fieldType", "STRING / NUMBER / BOOLEAN / DICTIONARY / LIST"),
            Column("config", "类型配置：DICTIONARY -> {entries, valueType}；LIST -> {itemType}"),
            Column("defaultValue", "默认值（文本）"),
            Column("isCalculated", "是否由计算图自动推导"),
            Column("calcGraph", "计算图（GGraph JSON），isCalculated=true 时必填"),
            Column("sortOrder", "排序"),
            Column("visible", "是否在界面展示（默认 true）"),
            Column("timerEnabled", "是否启用财年定时器（与 isCalculated 互斥）"),
            Column("timerTrigger", "FY_START / FY_END"),
            Column("timerValue", "定时器写入的值"),
        ),
        notes=(
            "全局资源：按 (产业类型 code, fieldKey) 复用/更新。",
            "每个产业类型建议保留 fieldKey='location' 的「所在地」字段（地图/运费/区域总览依赖）。",
        ),
    ),
    ResourceSchema(
        resource="companies",
        label="公司",
        builder_methods=("company(name, industry_type=..., region=..., status=..., field_values=...)",),
        columns=(
            Column("name", "公司名（同比赛内唯一）", required=True, key=True),
            Column("industryTypeCode", "所属产业类型 code（决定字段集合）", required=True),
            Column("regionName", "所属区域名（导入按名解析；不存在会按名自动建）"),
            Column("status", "ACTIVE / INACTIVE"),
        ),
    ),
    ResourceSchema(
        resource="companyFieldValues",
        label="公司字段初始值",
        builder_methods=("add_field_value(company, field_key, value)", "company(..., field_values={...})"),
        columns=(
            Column("companyId", "公司旧 id", ref="companies"),
            Column("companyName", "公司名（跨分组按名兜底解析）", aux=True),
            Column("industryTypeCode", "字段所属产业类型 code", required=True),
            Column("fieldKey", "产业字段 fieldKey", required=True),
            Column("value", "字段值（文本；NUMBER 建议用字符串保精度）"),
            Column("version", "乐观锁版本号（导入时由引擎维护，通常不填）"),
        ),
        notes=("导入按 (公司, 产业字段) 幂等：值变化则更新并把 version +1。",),
    ),
    ResourceSchema(
        resource="regions",
        label="区域",
        builder_methods=("region(name, description=...)",),
        columns=(
            Column("name", "区域名（同比赛内唯一）", required=True, key=True),
            Column("description", "描述"),
            Column("overviewCards", "总览卡片数组（一般由 card() 产出，走 overviewCards 资源）"),
        ),
    ),
    ResourceSchema(
        resource="mapNodeTypes",
        label="地图节点类型",
        builder_methods=("node_type(name, description=..., color=...)",),
        columns=(
            Column("name", "类型名（同比赛内唯一）", required=True, key=True),
            Column("description", "描述"),
            Column("color", "颜色"),
        ),
    ),
    ResourceSchema(
        resource="pathTypes",
        label="路径类型",
        builder_methods=("path_type(name, description=..., color=...)",),
        columns=(
            Column("name", "类型名（同比赛内唯一）", required=True, key=True),
            Column("description", "描述"),
            Column("color", "颜色"),
        ),
        notes=("载具按路径类型决定可通行性，合同「存在的路径类型」也输出该列表。",),
    ),
    ResourceSchema(
        resource="mapNodes",
        label="地图节点",
        builder_methods=("node(name, node_type, region=..., x=..., y=...)",),
        columns=(
            Column("name", "节点名（同比赛内唯一，也是合同/运费展示依据）", required=True, key=True),
            Column("nodeTypeName", "节点类型名", required=True),
            Column("region", "区域名（**文本列**，不是外键；区域总览按它聚合）", required=True),
            Column("x", "画布横坐标"),
            Column("y", "画布纵坐标"),
        ),
        notes=("缺节点类型会在导入时跳过该行；孤立节点（无连线）不可达，运费计算会失败。",),
    ),
    ResourceSchema(
        resource="mapEdges",
        label="地图连线",
        builder_methods=("edge(from_node, to_node, distance, path_type)",),
        columns=(
            Column("fromNodeName", "起点节点名", required=True, ref="mapNodes"),
            Column("toNodeName", "终点节点名", required=True, ref="mapNodes"),
            Column("distance", "距离", required=True),
            Column("pathTypeName", "路径类型名", required=True, ref="pathTypes"),
        ),
        notes=("唯一约束 (起点, 终点)：同一对节点只允许一条连线；起终点不能相同。",),
    ),
    ResourceSchema(
        resource="fuels",
        label="燃料",
        builder_methods=("fuel(name, price_per_liter=...)",),
        columns=(
            Column("name", "燃料名（同比赛内唯一）", required=True, key=True),
            Column("pricePerLiter", "每升单价（参与运费计算）"),
        ),
        notes=("被载具 PROTECT 引用：有载具引用时不能删除。",),
    ),
    ResourceSchema(
        resource="materials",
        label="原料",
        builder_methods=("material(name, origin=..., carbon_emission_coefficient=..., type=..., node_prices=...)",),
        columns=(
            Column("name", "原料名（同比赛内唯一，是配比/库存字典的键）", required=True, key=True),
            Column("origin", "产地（通常填地图节点名）"),
            Column("carbonEmissionCoefficient", "碳排放系数"),
            Column("type", "NORMAL / SPECIAL"),
            Column("nodePricesByName", "地点价 {地图节点名: 价格}（推荐：可跨分组独立导入）", aux=True),
            Column("nodePrices", "地点价 {地图节点旧 id: 价格}（导出侧口径；导入时优先用上面那个）"),
        ),
        notes=("导入优先用 nodePricesByName 按节点名重建；节点不存在的地点价会被丢弃并提示。",),
    ),
    ResourceSchema(
        resource="techNodes",
        label="科技节点",
        builder_methods=("tech(name, tier=..., research_cost=..., description=..., prerequisites=[...])",),
        columns=(
            Column("name", "节点名（同比赛内唯一）", required=True, key=True),
            Column("description", "说明"),
            Column("tier", "层级"),
            Column("researchCost", "研发费用"),
        ),
    ),
    ResourceSchema(
        resource="techPrerequisites",
        label="科技前置依赖",
        builder_methods=("add_prerequisite(node, prerequisite)", "tech(..., prerequisites=[...])"),
        columns=(
            Column("nodeId", "节点旧 id（导入侧只认 id，无按名兜底）", required=True, ref="techNodes"),
            Column("prerequisiteId", "前置节点旧 id", required=True, ref="techNodes"),
        ),
        notes=(
            "导入侧只按旧 id 解析（不像其它资源有按名兜底），因此必须写 id；"
            "用 add_prerequisite(node, prerequisite) 登记即可自动填。",
            "前置成环会让研发永远无法解锁；builder.validate() 会检测并提醒。",
        ),
    ),
    ResourceSchema(
        resource="infrastructures",
        label="基建",
        builder_methods=("infrastructure(name, footprint=..., price=..., activation_price=..., ...)",),
        columns=(
            Column("name", "名称（同比赛内唯一）", required=True, key=True),
            Column("footprint", "占地面积"),
            Column("price", "单价"),
            Column("activationPrice", "启用费用"),
            Column("employmentRateBonus", "就业率加成"),
            Column("populationBonus", "人口加成"),
            Column("highQualityPopulationBonus", "高素质人口加成"),
            Column("happinessIndexBonus", "幸福度加成"),
            Column("perCapitaIncomeBonus", "人均收益加成"),
            Column("carbonReductionBonus", "减碳加成"),
        ),
    ),
    ResourceSchema(
        resource="productionLines",
        label="生产线",
        builder_methods=("line(name, price=..., labor_count=..., max_per_year=...)",),
        columns=(
            Column("name", "名称（同比赛内唯一）", required=True, key=True),
            Column("price", "单价"),
            Column("laborCount", "用工人数"),
            Column("maxPerYear", "年产能"),
        ),
    ),
    ResourceSchema(
        resource="warehouses",
        label="仓库",
        builder_methods=("warehouse(name, type, capacity=..., price=...)",),
        columns=(
            Column("name", "名称（同比赛内唯一）", required=True, key=True),
            Column("type", "MATERIAL / PART / PRODUCT / FUEL", required=True),
            Column("capacity", "容量"),
            Column("price", "单价"),
        ),
        notes=("四种种类建议都有覆盖，否则对应物资无处存放。",),
    ),
    ResourceSchema(
        resource="parts",
        label="零件",
        builder_methods=("part(name, materials={...}, tech=[...])",),
        columns=(Column("name", "零件名（同比赛内唯一）", required=True, key=True),),
    ),
    ResourceSchema(
        resource="partMaterials",
        label="零件-原料配比",
        builder_methods=("add_material_ratio(part, material, ratio)", "part(..., materials={...})"),
        columns=(
            Column("partId", "零件旧 id（导出侧产出；建包库用 partName）", ref="parts"),
            Column("partName", "零件名", required=True, ref="parts"),
            Column("materialId", "原料旧 id（导出侧产出；建包库用 materialName）", ref="materials"),
            Column("materialName", "原料名", required=True, ref="materials"),
            Column("ratio", "数量系数", required=True),
        ),
        notes=("配比缺失会让生产计算得到空字典。",),
    ),
    ResourceSchema(
        resource="partTechRequirements",
        label="零件-科技需求",
        builder_methods=("add_tech_requirement(part, tech_node)",),
        columns=(
            Column("partId", "零件旧 id（导出侧产出）", ref="parts"),
            Column("partName", "零件名", required=True, ref="parts"),
            Column("techNodeId", "科技节点旧 id（导出侧产出）", ref="techNodes"),
            Column("techNodeName", "科技节点名", required=True, ref="techNodes"),
        ),
    ),
    ResourceSchema(
        resource="products",
        label="产品",
        builder_methods=("product(name, parts={...}, tech=[...])",),
        columns=(Column("name", "产品名（同比赛内唯一）", required=True, key=True),),
    ),
    ResourceSchema(
        resource="productParts",
        label="产品-零件配比",
        builder_methods=("add_part_ratio(product, part, ratio)", "product(..., parts={...})"),
        columns=(
            Column("productId", "产品旧 id（导出侧产出）", ref="products"),
            Column("productName", "产品名", required=True, ref="products"),
            Column("partId", "零件旧 id（导出侧产出）", ref="parts"),
            Column("partName", "零件名", required=True, ref="parts"),
            Column("ratio", "数量系数", required=True),
        ),
    ),
    ResourceSchema(
        resource="productTechRequirements",
        label="产品-科技需求",
        builder_methods=("add_tech_requirement(product, tech_node)",),
        columns=(
            Column("productId", "产品旧 id（导出侧产出）", ref="products"),
            Column("productName", "产品名", required=True, ref="products"),
            Column("techNodeId", "科技节点旧 id（导出侧产出）", ref="techNodes"),
            Column("techNodeName", "科技节点名", required=True, ref="techNodes"),
        ),
    ),
    ResourceSchema(
        resource="vehicles",
        label="载具",
        builder_methods=("vehicle(name, fuel=..., path_types=[...], ...)",),
        columns=(
            Column("name", "载具名（同比赛内唯一）", required=True, key=True),
            Column("fuelName", "绑定燃料名（必填，PROTECT 外键）", required=True, ref="fuels"),
            Column("fuelConsumptionPerKm", "每公里油耗"),
            Column("maxCargo", "载货量"),
            Column("price", "单价"),
            Column("carbonEmission", "碳排放系数"),
        ),
    ),
    ResourceSchema(
        resource="vehiclePathTypes",
        label="载具-可通行路径类型",
        builder_methods=("add_path_type(vehicle, path_type)", "vehicle(..., path_types=[...])"),
        columns=(
            Column("vehicleId", "载具旧 id（导出侧产出）", ref="vehicles"),
            Column("vehicleName", "载具名", required=True, ref="vehicles"),
            Column("pathTypeId", "路径类型旧 id（导出侧产出）", ref="pathTypes"),
            Column("pathTypeName", "路径类型名", required=True, ref="pathTypes"),
        ),
        notes=("一条都没有时该载具的运输路径校验会失败。",),
    ),
    ResourceSchema(
        resource="consumerDemands",
        label="消费者需求",
        builder_methods=("demand(region, product, quantity, note=...)",),
        columns=(
            Column("region", "区域名（文本列）", required=True),
            Column("productType", "产品名（冗余列，与 productName 一致）", required=True),
            Column("productName", "产品名（跨分组按名兜底解析）", aux=True),
            Column("quantity", "需求量", required=True),
            Column("note", "备注"),
        ),
        notes=("导入按 (比赛, 区域, 产品类型, 数量) 幂等；改需求量等于新增一条。",),
    ),
    ResourceSchema(
        resource="contractTypes",
        label="合同类型（全局）",
        builder_methods=("contract_type(key, name, party_roles=[...], input_schema=[...], effects=[...], conditions=[...])",),
        columns=(
            Column("key", "全局唯一 key，跨比赛复用自然键", required=True, key=True),
            Column("name", "类型名称"),
            Column("description", "说明"),
            Column("partyRoles", "[{role, label, selectable?, isHost?}]"),
            Column("inputSchema", "[{key, label, type, required?, default?}]"),
            Column("effects", "[{kind:'FIELD', party, fieldKey, op:'ADD|SUB|SET', value}]"),
            Column("conditions", "[{kind:'FIELD', party, fieldKey, op:'GTE', value}]"),
            Column("graph", "可视化图结构（可空）"),
            Column("schemaVersion", "DSL 版本，默认 1"),
            Column("enabled", "是否启用"),
        ),
        notes=("全局资源：按 key 复用/更新；数据结构口径见 apps/contracts/engine.py。",),
    ),
    ResourceSchema(
        resource="contractInstances",
        label="合同实例",
        builder_methods=("contract(name, contract_type=..., parties=[...], inputs={...}, status=...)",),
        columns=(
            Column("name", "合同名（同类型内唯一）", required=True, key=True),
            Column("contractTypeId", "合同类型旧 id（导出侧产出；建包库用 contractTypeKey）", ref="contractTypes"),
            Column("contractTypeKey", "合同类型 key", required=True, ref="contractTypes"),
            Column("status", "DRAFT / PENDING_EXEC / EXECUTED / TERMINATED"),
            Column("parties", "[{role, companyId|companyName, isHost?, contractNumber?}]"),
            Column("inputs", "已填写的输入参数对象"),
        ),
        notes=(
            "导入按 (比赛, 合同类型, 名称) 幂等；已存在时只补参与方公司引用，不覆盖状态。",
            "导入侧的名称实际取「合同类型名」（建包库 contract() 的默认值也是它），"
            "因此同一合同类型在一场比赛里通常只能预置一份；确需多份时请给 contract(name=...) 传不同名字，"
            "但请注意导入侧仍按合同类型名判重（既有引擎语义）。",
            "status=EXECUTED 会立刻改写公司字段并落账，开赛前请保持 DRAFT。",
        ),
    ),
    ResourceSchema(
        resource="stocks",
        label="股票",
        builder_methods=("stock(code, name, company=..., total_shares=..., init_price=..., ...)",),
        columns=(
            Column("code", "股票代码（同比赛内唯一）", required=True, key=True),
            Column("name", "股票名称", required=True),
            Column("companyId", "关联公司旧 id（导出侧产出；建包库用 companyName）", ref="companies"),
            Column("companyName", "关联公司名", ref="companies"),
            Column("totalShares", "总股本"),
            Column("initNetProfit", "初始净利润"),
            Column("initPrice", "初始价格"),
            Column("currentPrice", "当前价格（不填取 initPrice）"),
            Column("industryPe", "行业 PE"),
            Column("currentCarbon", "当前碳排"),
            Column("industryAvgCarbon", "行业平均碳排"),
            Column("happiness", "幸福度"),
            Column("round", "当前轮次"),
            Column("carbonFieldRef", "碳排绑定的总览卡片引用字符串"),
            Column("happinessFieldRef", "幸福度绑定的总览卡片引用字符串"),
            Column("industryAvgCarbonRefs", "行业碳排均值绑定的卡片引用数组字符串"),
            Column("pbCompanyId", "行业 PE 联动公司旧 id", ref="companies"),
            Column("pbRandom", "PE 随机模式参数"),
        ),
        notes=("导入按 (比赛, code) 幂等；字段 id 绑定（pbFieldId）跨比赛不搬运。",),
    ),
    ResourceSchema(
        resource="stockFundsAccounts",
        label="资金账户",
        builder_methods=("account(name, owner=<公司> 或 username=..., cash_balance=...)",),
        columns=(
            Column("name", "账户名（同比赛内唯一）", required=True, key=True),
            Column("ownerType", "COMPANY / USER", required=True),
            Column("companyId", "归属公司旧 id（导出侧产出；建包库用 companyName）", ref="companies"),
            Column("companyName", "归属公司名（ownerType=COMPANY 时）", ref="companies"),
            Column("userId", "归属用户旧 id（导出侧产出；建包库用 username）", ref="users"),
            Column("username", "归属用户名（ownerType=USER 时）"),
            Column("cashBalance", "现金余额"),
        ),
        notes=("bindFieldId（现金跟随产业字段）依赖字段 id，跨比赛不搬运。",),
    ),
    ResourceSchema(
        resource="overviewCards",
        label="区域总览卡片",
        builder_methods=("card(region, company, field_key, display_name=..., zone=..., card_id=...)",),
        columns=(
            Column("regionName", "区域名", required=True, ref="regions"),
            Column("cards", "[{id, displayName, companyId, industryFieldId, zone?}]"),
        ),
        notes=(
            "卡片内 industryFieldId 是数据库主键：纯代码建包用 resolve_field_ids(导出的归档) 回填，"
            "未回填时写入 0 并由 validate() 提醒。",
        ),
    ),
    ResourceSchema(
        resource="messages",
        label="比赛内消息",
        builder_methods=("message(title, content=..., to_all=..., to_users=[...], sender=...)",),
        columns=(
            Column("title", "标题", required=True),
            Column("content", "正文"),
            Column("senderUsername", "发布者用户名（缺省用导入操作账号）"),
            Column("targetsAll", "是否面向全体"),
            Column("targetUserIds", "指定收件人旧账号 id 数组", ref="users"),
        ),
        notes=(
            "账号在导入顺序里排在消息之后，因此单次导入中指定收件人无法落地（会提示），"
            "如需保留请先导入账号再单独导入消息。",
        ),
    ),
    ResourceSchema(
        resource="users",
        label="参赛账号与范围",
        builder_methods=("user(username, role=..., company_scopes=[...], ...)",),
        columns=(
            Column("username", "用户名（**全局**唯一）", required=True, key=True),
            Column("displayName", "显示名"),
            Column("role", "SUPER_ADMIN / COMPETITION_ADMIN / PLAYER"),
            Column("isActive", "是否启用"),
            Column("permissions", "细粒度权限数组（null/空表示按 role 继承）"),
            Column("companyScopes", "公司管理范围（公司旧 id 数组）", ref="companies"),
            Column("companyScopeNames", "对应的公司名（按名兜底）", aux=True),
            Column("viewCompanyScopes", "查看范围", ref="companies"),
            Column("viewCompanyScopeNames", "对应的公司名", aux=True),
            Column("contractViewCompanyScopes", "合同查看范围", ref="companies"),
            Column("contractViewCompanyScopeNames", "对应的公司名", aux=True),
            Column("stockCompanyScopes", "股票范围", ref="companies"),
            Column("stockCompanyScopeNames", "对应的公司名", aux=True),
        ),
        notes=(
            "导出不含密码：新建账号密码为随机值且强制首次登录改密，需超管重置。",
            "已存在的用户名不会被覆盖密码、不会被抢比赛归属，只并入公司范围。",
        ),
    ),
)

RESOURCE_SCHEMA: dict[str, ResourceSchema] = {s.resource: s for s in _RESOURCE_SCHEMAS}


def describe_resource(resource: str) -> ResourceSchema:
    """按资源名取列定义；未知资源名报错。"""
    schema = RESOURCE_SCHEMA.get(resource)
    if schema is None:
        raise BuilderError(
            f"未知资源名：{resource}；可选 {', '.join(RESOURCE_SCHEMA)}"
        )
    return schema


def verify_rows(resource: str, rows: list[dict]) -> None:
    """校验产出行里的列名都在列定义中（拦住拼错的字段名）。

    未登记的资源名直接跳过：本表只覆盖 archive 支持导入的资源，
    额外资源由脚本自行保证（不会因为本表而误报）。
    """
    schema = RESOURCE_SCHEMA.get(resource)
    if schema is None:
        return
    allowed = set(schema.column_names) | {"_id"}
    for row in rows:
        unknown = sorted(set(row) - allowed)
        if unknown:
            raise BuilderError(
                f"{schema.label}（{resource}）出现了列定义里没有的字段：{', '.join(unknown)}；"
                f"可用字段：{', '.join(schema.column_names)}"
            )


def schema_markdown(resource: str | None = None) -> str:
    """把列定义渲染成 Markdown 表格（供文档生成）。"""
    schemas = [_schema_of(resource)] if resource else list(_RESOURCE_SCHEMAS)
    blocks: list[str] = []
    for s in schemas:
        lines = [f"### {s.label}（`{s.resource}`）", ""]
        if s.builder_methods:
            lines.append("建包方法：" + "；".join(f"`{m}`" for m in s.builder_methods))
            lines.append("")
        lines.append("| 列 | 必填 | 自然键 | 引用 | 说明 |")
        lines.append("| --- | :---: | :---: | --- | --- |")
        for c in s.columns:
            flags = []
            if c.aux:
                flags.append("辅助")
            lines.append(
                "| `{name}` | {req} | {key} | {ref} | {note} |".format(
                    name=c.name,
                    req="是" if c.required else "",
                    key="是" if c.key else "",
                    ref=(c.ref or "") + ("（" + "、".join(flags) + "）" if flags else ""),
                    note=c.note,
                )
            )
        for note in s.notes:
            lines.append("")
            lines.append(f"> {note}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _schema_of(resource: str) -> ResourceSchema:
    return describe_resource(resource)
