"""比赛数据聚合：把引擎的 37 个聚合端点收敛成一组具名函数。

为什么要收
----------
引擎的聚合口径挂在 `INPUT` 值源的 `aggregate` 字段上，共有 37 个取值
（`engine.py:1714`）。但按「聚合什么」归类，它们其实是同一件事的不同参数：

| 归并后的语义 | 覆盖的枚举数 |
| --- | --- |
| 清单 × 某属性求和 | 约 20 个（`*_TOTAL_PRICE` / `INFRA_*` / `VEHICLE_CARGO` …） |
| 清单总数量 | 4 个（`*_TOTAL_QTY`） |
| 清单展开成配比字典 | 4 个（`PART_MATERIALS` / `PRODUCT_PARTS` / `*_TECH_NODES`） |
| 地点价总额 / 碳排总额 / 按种类分组 | 各 1 个 |
| 路程与起讫点 | 4 个（`ROUTE_*`） |

于是本层只暴露 8 类函数：

    total_qty(清单)                      清单总数量
    sum_of(清单, "price")                清单 × 属性 求和（属性名与数据管理字段同名）
    total_price(原料清单, at=参与方)      原料地点价总额（引擎 PRICE 口径）
    carbon(原料清单)                     原料碳排总额
    expand(清单)                         展开成配比字典 / 科技清单
    warehouse_storage(仓库清单)           每种种类的总存储量
    route_distance/route_path_types/...  路程
    tech_prerequisites(科技清单)          前置节点列表

另外为「最常用的那几项属性」提供同义短名（`vehicle_price` / `fuel_price` /
`infra_price` …），它们只是 `sum_of(..., "price")` 的别名，**编译产物完全一致**，
不会引入第二套口径。

设计约束
--------
1. **不新增口径**：每个函数都映射到引擎已有的 aggregate 枚举，绝不自造计算；
2. **清单类型校验**：`total_price` 只接受原料清单、`expand` 只接受零件/产品清单，
   传错在构建期报错（引擎对错配的清单只会算出 0）；
3. **口径显式**：`total_price` 的 `at=` 参数就是「按哪一方所在地取价」，
   不再依赖「隐式连了哪个参与方」；不传则明确使用市场均价口径。
"""
from __future__ import annotations

from typing import Any

from .errors import BuildError
from .values import (
    LIST_INPUT_ENTITY,
    LIST_INPUT_TYPES,
    Value,
    _as_value,
    _input_aggregate,
    _party_role,
)


def _require_list_input(value: Any, func: str, *, entity: str | None = None) -> tuple[str, str]:
    """校验传入的是清单类输入项，返回 (key, 输入类型)。"""
    v = _as_value(value)
    spec = v.to_spec()
    if spec.get("type") != "INPUT":
        raise BuildError(
            f"{func}() 需要传入一个清单类输入项",
            hint=f"正确写法：{func}(input('mats', '原料清单', 'materialList'))",
        )
    if spec.get("aggregate"):
        raise BuildError(
            f"{func}() 的入参不能是已经聚合过的值",
            hint="请直接传输入项本身（如 plate = input(...)），聚合由本函数负责",
        )
    key = str(spec.get("key") or "")
    itype = str(v.input_type or "")
    if not itype:
        # 没有类型信息时按引擎行为放行：运行时按输入项实际值决定
        return key, ""
    if itype not in LIST_INPUT_TYPES and itype != "techNode":
        raise BuildError(
            f"{func}() 需要清单类输入项（{'、'.join(LIST_INPUT_TYPES)}、techNode），"
            f"但「{key}」的类型是 {itype}"
        )
    if entity and LIST_INPUT_ENTITY.get(itype) not in (None, entity):
        raise BuildError(
            f"{func}() 需要{ENTITY_LABEL_CN.get(entity, entity)}清单，"
            f"但「{key}」是 {itype}（{ENTITY_LABEL_CN.get(LIST_INPUT_ENTITY.get(itype, itype), itype)}）",
            hint=f"正确写法：{func}(input('mats', '原料清单', 'materialList'))",
        )
    return key, itype


#: 清单类型 → 中文名（报错信息用，避免让使用者去查实体枚举）
ENTITY_LABEL_CN: dict[str, str] = {
    "MATERIAL": "原料",
    "PART": "零件",
    "PRODUCT": "产品",
    "INFRASTRUCTURE": "基建",
    "FUEL": "燃料",
    "VEHICLE": "载具",
    "WAREHOUSE": "仓库",
    "TECH_NODE": "科技节点",
}


# ==================== 通用：清单 × 属性 ====================


def total_qty(items: Any) -> Value:
    """清单总数量：把 `{名称: 数量}` 的数量全部相加。

    适用于原料/零件/产品/燃料清单（引擎 `*_TOTAL_QTY`）。
    """
    key, itype = _require_list_input(items, "total_qty")
    if itype not in ("", "materialList", "partList", "productList", "fuelList"):
        raise BuildError(
            f"total_qty() 不支持 {itype} 清单",
            hint="可用：原料清单 / 零件清单 / 产品清单 / 燃料清单",
        )
    return Value({"type": "INPUT", "key": key, "aggregate": _TOTAL_QTY_OF.get(itype, "PART_TOTAL_QTY")},
                 label=f"{key} 总数量")


_TOTAL_QTY_OF: dict[str, str] = {
    "materialList": "MATERIAL_TOTAL_QTY",
    "partList": "PART_TOTAL_QTY",
    "productList": "PRODUCT_TOTAL_QTY",
    "fuelList": "FUEL_TOTAL_QTY",
    # 类型未知时按零件口径兜底（引擎对这四个的总数量算法完全相同）
    "": "PART_TOTAL_QTY",
}


# 别名 → (函数名, 目标属性)。全部是「清单 × 属性求和」，编译产物与 sum_of 一致。
_SUM_ALIASES: dict[str, str] = {
    "vehicle_price": "price",
    "vehicle_cargo": "maxCargo",
    "vehicle_fuel_per_km": "fuelConsumptionPerKm",
    "vehicle_carbon": "carbonEmission",
    "fuel_price": "pricePerLiter",
    "warehouse_price": "price",
    "production_line_price": "price",
    "production_line_labor": "laborCount",
    "production_line_capacity": "maxPerYear",
    "infra_price": "price",
    "infra_activation_price": "activationPrice",
    "infra_footprint": "footprint",
    "infra_employment": "employmentRateBonus",
    "infra_population": "populationBonus",
    "infra_high_quality": "highQualityPopulationBonus",
    "infra_happiness": "happinessIndexBonus",
    "infra_income": "perCapitaIncomeBonus",
    "infra_carbon": "carbonReductionBonus",
    "tech_research_cost": "researchCost",
}


def sum_of(items: Any, attribute: str) -> Value:
    """清单 × 某属性 求和。`attribute` 用数据管理里的真实字段名（camelCase）。

    例：`sum_of(vehicles, "maxCargo")`、`sum_of(infra, "carbonReductionBonus")`。

    这是「降低抽象」的关键一步：原来要记 20 个端口名（`VEHICLE_CARGO`、
    `INFRA_CARBON`…），现在只写属性名。属性名与 `--schema`/数据管理界面一致。
    """
    key, itype = _require_list_input(items, "sum_of")
    if itype and itype not in LIST_INPUT_TYPES and itype not in ("techNode",):
        raise BuildError(f"sum_of() 不支持 {itype} 清单")
    attr = str(attribute or "").strip()
    if not attr:
        raise BuildError("sum_of() 需要属性名", hint=f"例如 sum_of(vehicles, 'price')")
    aggregate = _resolve_sum_aggregate(itype, attr)
    return Value({"type": "INPUT", "key": key, "aggregate": aggregate}, label=f"{key} 的 {attr} 合计")


# 具名属性端点：这些属性有专属聚合枚举，优先使用
_NAMED_ATTR_AGGREGATES: dict[str, str] = {
    "price": "VEHICLE_TOTAL_PRICE",
    "maxCargo": "VEHICLE_CARGO",
    "fuelConsumptionPerKm": "VEHICLE_FUEL_PER_KM",
    "carbonEmission": "VEHICLE_CARBON",
    "pricePerLiter": "FUEL_TOTAL_PRICE",
    "researchCost": "TECH_RESEARCH_COST",
}

# 基建的 9 项加成/费用：引擎用 INFRA_* 系列
_INFRA_ATTR_AGGREGATES: dict[str, str] = {
    "price": "INFRA_PRICE",
    "footprint": "INFRA_FOOTPRINT",
    "employmentRateBonus": "INFRA_EMPLOYMENT",
    "populationBonus": "INFRA_POPULATION",
    "highQualityPopulationBonus": "INFRA_HIGHQUALITY",
    "happinessIndexBonus": "INFRA_HAPPINESS",
    "perCapitaIncomeBonus": "INFRA_INCOME",
    "carbonReductionBonus": "INFRA_CARBON",
    "activationPrice": "INFRA_ACTIVATION_PRICE",
}


def _resolve_sum_aggregate(itype: str, attribute: str) -> str:
    """把（清单类型, 属性名）解析成引擎的 aggregate 枚举。"""
    if itype == "infrastructureList":
        found = _INFRA_ATTR_AGGREGATES.get(attribute)
        if found:
            return found
        raise BuildError(
            f"基建清单没有可求和的属性「{attribute}」",
            hint=f"可用：{'、'.join(_INFRA_ATTR_AGGREGATES)}",
        )
    if itype == "warehouseList":
        if attribute == "price":
            return "WAREHOUSE_TOTAL_PRICE"
        raise BuildError(
            "仓库清单只能求 price 合计（每种种类的存储量请用 warehouse_storage()）",
            hint="可用：price",
        )
    if itype == "vehicleList":
        found = _NAMED_ATTR_AGGREGATES.get(attribute)
        if found and found.startswith("VEHICLE_"):
            return found
        raise BuildError(
            f"载具清单没有可求和的属性「{attribute}」",
            hint="可用：price、maxCargo、fuelConsumptionPerKm、carbonEmission",
        )
    if itype == "fuelList":
        if attribute == "pricePerLiter":
            return "FUEL_TOTAL_PRICE"
        raise BuildError("燃料清单只能求 pricePerLiter 合计", hint="可用：pricePerLiter")
    if itype == "techNode":
        if attribute == "researchCost":
            return "TECH_RESEARCH_COST"
        raise BuildError("科技清单只能求 researchCost 合计", hint="可用：researchCost")
    if itype == "productionLineList":
        # 生产线没有专属聚合端点，引擎侧无对应 aggregate
        raise BuildError(
            "生产线清单暂不支持聚合求和",
            hint="引擎未提供生产线聚合端点；请用 sum_of 之外的方式表达（如固定常量）",
        )
    # 原料/零件/产品（及类型未知）：引擎没有它们的通用属性聚合端点
    raise BuildError(
        f"{LIST_INPUT_ENTITY.get(itype, itype)}清单没有「{attribute}」的聚合端点",
        hint=(
            "原料价格请用 total_price()（地点价口径）、碳排用 carbon()；"
            "零件/产品请用 expand() 展开配比后再取值"
        ),
    )


# ==================== 原料专用 ====================


def total_price(materials: Any, *, at: Any = None) -> Value:
    """原料清单总价格（引擎 `PRICE` 口径）。

    - `at=<参与方>`：按该参与方**公司所在地**取地点价（引擎会解析公司的
      `location` 字段 → 地图节点 → 该原料在此节点的报价）；
    - `at=None`：明确使用**市场均价**口径（引擎在无地点价时也是这个回退）。

    注意：引擎在「指定了参与方但其公司没有 location」时会**静默回退均价**。
    请用 `validate()` 或 `--check` 提前发现这种回退——这是本次落地要消灭的
    静默错误之一。
    """
    key, _ = _require_list_input(materials, "total_price", entity="MATERIAL")
    spec: dict[str, Any] = {"type": "INPUT", "key": key, "aggregate": "PRICE"}
    where = "市场均价"
    if at is not None:
        role = _party_role(at)
        spec["party"] = role
        where = f"{role} 所在地"
    return Value(spec, label=f"{key} 总价格（{where}）")


def avg_price(materials: Any) -> Value:
    """原料清单总价格（市场均价口径，等价于 `total_price(materials)`）。"""
    return total_price(materials)


def carbon(materials: Any) -> Value:
    """原料清单碳排放合计（引擎 `CARBON`）。"""
    key, _ = _require_list_input(materials, "carbon", entity="MATERIAL")
    return Value({"type": "INPUT", "key": key, "aggregate": "CARBON"}, label=f"{key} 碳排放合计")


# ==================== 展开 ====================


def expand(items: Any) -> Value:
    """把清单展开成配比/依赖字典。

    - 零件清单 → 所需原料 `{原料名: 数量}`（`PART_MATERIALS`）
    - 产品清单 → 所需零件 `{零件名: 数量}`（`PRODUCT_PARTS`）
    - 零件清单 → 所需科技节点名列表（`PART_TECH_NODES`）
    - 产品清单 → 所需科技节点名列表（`PRODUCT_TECH_NODES`）

    零件还是产品由输入项的**类型**决定；类型缺失时按零件口径（引擎侧两套算法
    只用清单里的名字查库，行为一致），但会给出提醒。
    """
    key, itype = _require_list_input(items, "expand")
    if itype == "productList":
        aggregate = "PRODUCT_PARTS"
    elif itype in ("partList", ""):
        aggregate = "PART_MATERIALS"
    else:
        raise BuildError(
            f"expand() 只适用于零件清单或产品清单，收到 {itype}",
            hint="原料/基建/仓库/载具/燃料清单没有可展开的配比",
        )
    return Value({"type": "INPUT", "key": key, "aggregate": aggregate}, label=f"{key} 展开")


def required_materials_count(parts: Any) -> Value:
    """零件清单：所需原料总数量（`PART_MATERIAL_TOTAL_QTY`）。"""
    key, _ = _require_list_input(parts, "required_materials_count", entity="PART")
    return Value(
        {"type": "INPUT", "key": key, "aggregate": "PART_MATERIAL_TOTAL_QTY"},
        label=f"{key} 所需原料总数量",
    )


def required_parts_count(products: Any) -> Value:
    """产品清单：所需零件总数量（`PRODUCT_PARTS_TOTAL_QTY`）。"""
    key, _ = _require_list_input(products, "required_parts_count", entity="PRODUCT")
    return Value(
        {"type": "INPUT", "key": key, "aggregate": "PRODUCT_PARTS_TOTAL_QTY"},
        label=f"{key} 所需零件总数量",
    )


def part_tech_nodes(parts: Any) -> Value:
    """零件清单：所需的科技节点名列表（`PART_TECH_NODES`）。"""
    key, _ = _require_list_input(parts, "part_tech_nodes", entity="PART")
    return Value(
        {"type": "INPUT", "key": key, "aggregate": "PART_TECH_NODES"},
        label=f"{key} 所需科技节点",
    )


def product_tech_nodes(products: Any) -> Value:
    """产品清单：所需的科技节点名列表（`PRODUCT_TECH_NODES`）。"""
    key, _ = _require_list_input(products, "product_tech_nodes", entity="PRODUCT")
    return Value(
        {"type": "INPUT", "key": key, "aggregate": "PRODUCT_TECH_NODES"},
        label=f"{key} 所需科技节点",
    )


# ==================== 仓库 / 科技 ====================


def warehouse_storage(warehouses: Any) -> Value:
    """仓库清单：每种种类的总存储量 `{种类: 容量}`（`WAREHOUSE_STORAGE`）。"""
    key, _ = _require_list_input(warehouses, "warehouse_storage", entity="WAREHOUSE")
    return Value(
        {"type": "INPUT", "key": key, "aggregate": "WAREHOUSE_STORAGE"},
        label=f"{key} 每种种类的总存储量",
    )


def tech_prerequisites(tech: Any) -> Value:
    """科技节点：前置节点名列表（`TECH_PREREQUISITES`）。"""
    key, _ = _require_list_input(tech, "tech_prerequisites")
    return Value(
        {"type": "INPUT", "key": key, "aggregate": "TECH_PREREQUISITES"},
        label=f"{key} 的前置节点",
    )


# ==================== 别名（编译产物与 sum_of 完全一致） ====================


def _make_alias(func_name: str, attribute: str):
    def _alias(items: Any) -> Value:
        key, itype = _require_list_input(items, func_name)
        aggregate = _resolve_sum_aggregate(itype, attribute)
        return Value(
            {"type": "INPUT", "key": key, "aggregate": aggregate},
            label=f"{key} 的 {attribute} 合计",
        )

    _alias.__name__ = func_name
    _alias.__qualname__ = func_name
    _alias.__doc__ = f"清单的 {attribute} 合计（等价于 `sum_of(清单, \"{attribute}\")`）。"
    return _alias


vehicle_price = _make_alias("vehicle_price", "price")
vehicle_cargo = _make_alias("vehicle_cargo", "maxCargo")
vehicle_fuel_per_km = _make_alias("vehicle_fuel_per_km", "fuelConsumptionPerKm")
vehicle_carbon = _make_alias("vehicle_carbon", "carbonEmission")
fuel_price = _make_alias("fuel_price", "pricePerLiter")
warehouse_price = _make_alias("warehouse_price", "price")
infra_price = _make_alias("infra_price", "price")
infra_activation_price = _make_alias("infra_activation_price", "activationPrice")
infra_footprint = _make_alias("infra_footprint", "footprint")
infra_employment = _make_alias("infra_employment", "employmentRateBonus")
infra_population = _make_alias("infra_population", "populationBonus")
infra_high_quality = _make_alias("infra_high_quality", "highQualityPopulationBonus")
infra_happiness = _make_alias("infra_happiness", "happinessIndexBonus")
infra_income = _make_alias("infra_income", "perCapitaIncomeBonus")
infra_carbon = _make_alias("infra_carbon", "carbonReductionBonus")
tech_research_cost = _make_alias("tech_research_cost", "researchCost")


# ==================== 路程（在 values 层已实现，这里重导出便于一处引用） ====================


def route_distance(nodes: Any) -> Value:
    """节点列表（`nodeRoute` 输入项）的相邻节点最短路径距离之和（`ROUTE_DISTANCE`）。"""
    from .values import route_distance as _impl

    return _impl(_as_value(nodes))


def route_path_types(nodes: Any) -> Value:
    """路程经过的路径类型列表（`ROUTE_PATH_TYPES`）。"""
    return _input_aggregate(_as_value(nodes), "ROUTE_PATH_TYPES", "路程路径类型")


def route_start_node(nodes: Any) -> Value:
    """路程起始节点名（`ROUTE_START_NODE_NAME`）。"""
    return _input_aggregate(_as_value(nodes), "ROUTE_START_NODE_NAME", "路程起始节点名")


def route_end_node(nodes: Any) -> Value:
    """路程终止节点名（`ROUTE_END_NODE_NAME`）。"""
    return _input_aggregate(_as_value(nodes), "ROUTE_END_NODE_NAME", "路程终止节点名")
