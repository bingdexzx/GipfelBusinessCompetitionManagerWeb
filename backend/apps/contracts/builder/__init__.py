"""合同类型代码化建库：用简单 Python 代码代替可视化拖拽，产出后端契约 JSON。

定位
----
本库**不引入任何新的引擎语义**。产物就是引擎今天已经在跑的四份 JSON：

    {"partyRoles": [...], "inputSchema": [...], "effects": [...], "conditions": [...]}

因此可逆性（`revert_contract` 的事件溯源重放）、审计粒度
（`ContractFieldEffect` 每字段一行）、试算接口（`POST /api/contracts/trial`）
全部原样不受影响。`graph` 字段传 `None`（后端 `allow_null=True`，引擎从不读它）。

降低抽象的两处重点
------------------
**① 效果（effect）**

引擎只有一种效果形状 `{kind:"FIELD", op, value}`，而 `op` 的真实含义取决于
目标字段的**运行时类型**（数值相加 / 列表追加去重 / 字典逐键累加 / 文本覆盖），
字典的 `SUB` 更是靠「值是数组还是字典」来区分「删键」与「减数」。

本库改为 11 个**具名效果**，效果名自带字段类型契约，不匹配在构建期直接报错：

    add_number / sub_number / set_number          数值
    append_items / remove_items / set_items       列表
    add_dict / sub_dict / remove_keys / set_dict  字典
    set_value                                     任意类型

**② 实体（ENTITY）**

引擎引用一条比赛数据要 `{type:"ENTITY", entityRef:<输入项key>, attribute:<属性名>}`：
引用固定实体也得先造隐藏输入项，属性名走 `getattr(..., 0)` 反射——
写错静默为 0（旧字段表里 `MATERIAL.price` 就是这样一条错声明）。

本库改为一层具名访问器，属性名对**模型真实字段**做白名单校验：

    snap = snapshot(7)
    iron = snap.material("铁矿石")
    iron.carbon              # 属性拼错 → 立即报错
    total_price(plate, at=buyer)   # 清单取价只有这一条口径

快速开始
--------
    from apps.contracts.builder import (
        ContractType, snapshot, number, total_price,
    )

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
        ct.add_number(buyer.field("inventory"), total_price(plate, at=buyer))
        return ct

    ct.payload()                  # 可直接 POST /api/contract-types
    check(ct, snap=snap)          # 静态体检（不碰引擎、不写库）

命令行
------
    python manage.py build_contract_types contracts_src/ --competition 7 --check
    python manage.py build_contract_types contracts_src/ --competition 7 --dry-run
    python manage.py build_contract_types contracts_src/ --competition 7 --import
"""
from .aggregates import (
    avg_price,
    carbon,
    expand,
    fuel_price,
    infra_activation_price,
    infra_carbon,
    infra_employment,
    infra_footprint,
    infra_happiness,
    infra_high_quality,
    infra_income,
    infra_population,
    infra_price,
    part_tech_nodes,
    product_tech_nodes,
    required_materials_count,
    required_parts_count,
    route_distance,
    route_end_node,
    route_path_types,
    route_start_node,
    sum_of,
    tech_prerequisites,
    tech_research_cost,
    total_price,
    total_qty,
    vehicle_carbon,
    vehicle_cargo,
    vehicle_fuel_per_km,
    vehicle_price,
    warehouse_price,
    warehouse_storage,
)
from .builder import Check, ContractType, FieldRef, PartyRef
from .effects import (
    EFFECT_KINDS,
    KINDS_BY_FIELD_TYPE,
    Effect,
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
from .errors import BuildError, ContractBuilderError, DataError, SchemaError
from .refs import CompetitionSnapshot, EntityRef, snapshot
from .validate import (
    AGGREGATE_INPUT_TYPES,
    ERROR,
    INFO,
    WARNING,
    Finding,
    Report,
    validate_payload,
)
from .values import (
    COMPARE_OPS,
    ENTITY_ATTRIBUTES,
    ENTITY_TYPE_LABEL,
    INPUT_TYPES,
    LIST_INPUT_TYPES,
    Value,
    company_name,
    concat_text,
    const,
    flag,
    formula,
    industry_is,
    input_value,
    join_text,
    number,
    range_list,
    text,
    var,
)

__all__ = [
    # 主体
    "ContractType",
    "PartyRef",
    "FieldRef",
    "Check",
    "Effect",
    "Value",
    # 快照与实体
    "snapshot",
    "CompetitionSnapshot",
    "EntityRef",
    "ENTITY_ATTRIBUTES",
    "ENTITY_TYPE_LABEL",
    # 值
    "number",
    "text",
    "flag",
    "const",
    "var",
    "formula",
    "input_value",
    "range_list",
    "concat_text",
    "join_text",
    "company_name",
    "industry_is",
    "INPUT_TYPES",
    "LIST_INPUT_TYPES",
    "COMPARE_OPS",
    # 具名效果
    "add_number",
    "sub_number",
    "set_number",
    "append_items",
    "remove_items",
    "set_items",
    "add_dict",
    "sub_dict",
    "remove_keys",
    "set_dict",
    "set_value",
    "EFFECT_KINDS",
    "KINDS_BY_FIELD_TYPE",
    # 聚合
    "total_qty",
    "sum_of",
    "total_price",
    "avg_price",
    "carbon",
    "expand",
    "required_materials_count",
    "required_parts_count",
    "part_tech_nodes",
    "product_tech_nodes",
    "warehouse_storage",
    "tech_prerequisites",
    "route_distance",
    "route_path_types",
    "route_start_node",
    "route_end_node",
    "vehicle_price",
    "vehicle_cargo",
    "vehicle_fuel_per_km",
    "vehicle_carbon",
    "fuel_price",
    "warehouse_price",
    "infra_price",
    "infra_activation_price",
    "infra_footprint",
    "infra_employment",
    "infra_population",
    "infra_high_quality",
    "infra_happiness",
    "infra_income",
    "infra_carbon",
    "tech_research_cost",
    # 校验
    "check",
    "validate_payload",
    "Report",
    "Finding",
    "AGGREGATE_INPUT_TYPES",
    "ERROR",
    "WARNING",
    "INFO",
    # 异常
    "ContractBuilderError",
    "BuildError",
    "SchemaError",
    "DataError",
]


def check(
    ct: "ContractType",
    *,
    snap: CompetitionSnapshot | None = None,
    declared_field_types: dict | None = None,
    strict_effect_types: bool = False,
) -> Report:
    """对合同类型做静态体检（纯只读，不碰引擎、不写库）。

    传 `snap=`（`snapshot(competition_id)` 的返回值）会自动带上：

    - 各产业类型的字段清单 → 校验「效果引用的字段是否存在」与「效果 × 字段类型」；
    - 全库字段 key 并集 → 发现「这个字段任何产业都没有」（通常是拼写错误）。
    """
    payload = ct.build()
    if declared_field_types is None and snap is not None:
        declared_field_types = snap.industry_field_types()
    all_field_keys = snap.all_industry_field_keys() if snap is not None else None
    industry_names = snap.industry_names() if snap is not None else None
    return validate_payload(
        payload,
        key=ct.key,
        name=ct.name,
        declared_field_types=declared_field_types,
        all_field_keys=all_field_keys,
        industry_names=industry_names,
        strict_effect_types=strict_effect_types,
    )
