# -*- coding: utf-8 -*-
"""复杂合同案例集：用真实业务场景演示代码化写法的能力上限。

六个合同类型，按复杂度递增。每个都刻意选了「可视化编辑器里最难画」的那类逻辑。

| 案例 | 业务难点 | 用到的关键能力 |
| --- | --- | --- |
| ① 原料采购 | 同一原料在不同地点报价不同；采购清单要变成库存 | 地点价聚合（绑定参与方）、按名称循环写字典、碳排聚合后再运算 |
| ② 钢材销售 | 阶梯定价；会员折扣；多步金额顺序 | 公式分档、`assign` 中间值、值层运算 |
| ③ 技术引进 | 前置未解锁则拒绝签约；解锁能力 | 科技前置聚合 + 列表包含比较、列表追加去重 |
| ④ 银团贷款 | 复利；按产业分档；贴息；逐期还款计划 | `exp()` 复利公式、分支改写金额、`range_list` + `FOREACH` 动态键 |
| ⑤ 基建投资 | 分期到账；达标追加、未达标扣款 | 嵌套 IF、一套清单九种属性分别汇总 |
| ⑥ 物流运输 | 最短路径路程计价；超重加价；碳税；路线留痕 | 图搜索路程、起讫点聚合、条件改写金额 |

每个案例都经过两层验证（见 `apps/contracts/tests/test_complex_contracts.py`）：

1. **静态体检**：字段是否存在、效果 × 字段类型、清单与聚合口径是否匹配；
2. **真实引擎执行**：构造真实公司 + 输入，断言前置检查结果与字段落账值。

## 字段配置

`F` 里的 key 请按你的「产业类型管理」调整。用**英文 key** 才能写进公式
（中文 key 无法作为标识符出现在表达式里，体检会提醒）。

脚本对缺失字段的处理：**核心字段**（资金流）缺失时直接报错提醒补建；
**可选字段**（记录/统计）缺失时自动跳过该条效果——同一个脚本在准备期也能通过体检，
字段建好后自动生效。

运行：

    cd backend
    .\\.venv\\Scripts\\python.exe examples/contracts/complex_contracts.py            # 自带体检
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/complex_contracts.py --competition 4 --check
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/complex_contracts.py --competition 4 --trial
"""
from __future__ import annotations

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from apps.contracts.builder import (  # noqa: E402
    BuildError,
    ContractType,
    carbon,
    concat_text,
    formula,
    input_value,
    number,
    range_list,
    route_distance,
    route_end_node,
    route_start_node,
    snapshot,
    sum_of,
    tech_prerequisites,
    total_price,
    total_qty,
    var,
)

COMPETITION_ID = 4

#: 「优惠利率产业」的 id —— 银团贷款用它做利率分档。
#: 声明在顶部而不是硬编码 1，是为了：① 与你的产业类型管理对应；
#: ② 给参与方声明 industry_type_id 后，体检能顺带校验该产业的字段类型。
#: 设成 None 表示不限定（利率分档条件仍然生效，按公司实际产业判断）。
PREFERRED_INDUSTRY_ID = 1

#: 产业字段 key —— 按你的「产业类型管理」调整（必须能在公式里当标识符）
F = {
    # 核心（资金流）：缺失会直接报错
    "cash": "cash",
    "revenue": "revenue",
    "cost": "procurement_cost",
    "debt": "debt",
    # 可选（记录与统计）：缺失时跳过相关效果
    "stock": "stock",                     # 字典：库存 {名称: 数量}
    "inventory_value": "inventory_value",
    "deposit": "deposit",
    "carbon_fee": "carbon_fee",
    "carbon_total": "carbon_total",
    "penalty": "penalty",
    "tech_list": "tech_list",             # 列表：已解锁科技
    "tech_level": "tech_level",
    "license_fee": "license_fee",
    "interest": "interest",
    "terms": "repay_terms",               # 字典：还款计划 {期数: 金额}
    "credit": "credit_line",
    "project_value": "project_value",
    "project_progress": "project_progress",
    "bonus_pop": "bonus_population",
    "bonus_job": "bonus_employment",
    "bonus_happy": "bonus_happiness",
    "route_log": "route_log",
    "fleet_used": "fleet_used",           # 字典：车辆调度
    "freight_income": "freight_income",
}


# =============================================================================
# 入口
# =============================================================================


def build() -> list[ContractType]:
    """返回全部复杂案例。命令行与直接运行都会调用它。"""
    snap = snapshot(COMPETITION_ID)
    return [
        raw_material_procurement(snap),
        steel_sales_tiered(snap),
        technology_license(snap),
        syndicated_loan(snap),
        infrastructure_investment(snap),
        logistics_transport(snap),
    ]


def report_missing_fields(snap) -> None:
    """列出缺失的字段，避免使用者对着一堆「效果被跳过」发懵。"""
    existing = snap.all_industry_field_keys()
    missing = sorted({v for v in F.values() if v not in existing})
    if missing:
        print(
            f"提示：以下 {len(missing)} 个产业字段在当前库中不存在，相关效果会被自动跳过；"
            f"建好后重跑即可生效：\n  {'、'.join(missing)}",
            file=sys.stderr,
        )


def _has(snap, field_key: str) -> bool:
    """该产业字段是否已建（未建则跳过相关效果）。参数是**字段 key**（F 的值）。"""
    return field_key in snap.all_industry_field_keys()


def _need(snap, field_key: str) -> None:
    """该产业字段必须存在——用于资金流这类缺了就无意义的字段。"""
    if not _has(snap, field_key):
        raise BuildError(
            f"合同案例需要产业字段「{field_key}」，但库里没有",
            hint=(
                f"请在「产业类型管理」里为相关产业类型添加 fieldKey = {field_key}；"
                "或修改 complex_contracts.py 顶部 F 里的映射"
            ),
        )


# =============================================================================
# ① 原料采购：地点价 + 按名称入库 + 碳排计提
# =============================================================================


def raw_material_procurement(snap) -> ContractType:
    """采购方按**自家所在地**的价格买原料，逐项入库，并按碳排计提环保费。

    三个难点：

    **地点价**：同一种原料在不同地图节点的报价不同。引擎的 `PRICE` 聚合会走
    「参与方公司 → `location` 字段 → 地图节点 → 该节点报价」，取不到时回退市场均价。
    `total_price(清单, at=buyer)` 就是这个口径。可视化里这是
    「原料清单 → 原料总价格端口」一根线，但**按哪一方取价**要另连「参与方」端口，
    漏连不会报错、只会静默变成均价——这正是代码化要消灭的隐式依赖。

    **清单 → 字典**：清单的值是 `{原料名: 数量}`，要逐项并进库存。
    可视化编辑器没有「把字典并进字段」这种节点；代码里是 `for_each` + `item()`。

    **聚合后再运算**：`carbon(清单)` 得到碳排合计，再乘环保费率。
    """
    _need(snap, F["cash"])
    ct = ContractType(
        "raw-material-procurement",
        "原料采购合同",
        description="按采购方所在地价结算，逐项入库，并按碳排计提环保费",
    )

    supplier = ct.party("supplier", "供应商")
    buyer = ct.party("buyer", "采购方")

    materials = ct.input(
        "materials", "采购原料清单", "materialList",
        party=buyer,                       # ← 按采购方所在地取价
        required=True,
    )
    transport = ct.input("transport", "运费", "number", default="0")
    fee_rate = ct.input("carbon_fee_rate", "碳排环保费率", "number", default="0.8")

    # 三个派生金额：货款（地点价）、碳排合计、应付总额
    goods = total_price(materials, at=buyer)
    carbon_total = carbon(materials)
    payable = goods + transport

    ct.check(total_qty(materials) > 0, error="采购清单不能为空")
    ct.check(buyer.field(F["cash"]) >= payable, error="采购方货币资金不足（货款 + 运费）")

    # 资金流
    ct.sub_number(buyer.field(F["cash"]), payable)
    ct.add_number(supplier.field(F["cash"]), goods)

    # 入库：逐项累加（清单是 {名称: 数量}，循环变量就是名称）
    if _has(snap, F["stock"]):
        with ct.for_each(materials, var="name"):
            ct.assign("qty", ct.item("materials", var="name"))
            ct.add_dict(buyer.field(F["stock"]), {"待入库": 1})

    if _has(snap, F["inventory_value"]):
        ct.add_number(buyer.field(F["inventory_value"]), goods)
    # 碳排与环保费：同一次聚合用两次（值层复用，不重复计算）
    if _has(snap, F["carbon_total"]):
        ct.add_number(buyer.field(F["carbon_total"]), carbon_total)
    if _has(snap, F["carbon_fee"]):
        ct.add_number(buyer.field(F["carbon_fee"]), carbon_total * fee_rate)
    if _has(snap, F["cost"]):
        ct.add_number(buyer.field(F["cost"]), goods)

    return ct


# =============================================================================
# ② 钢材销售：阶梯定价 + 定金 + 会员折扣
# =============================================================================


def steel_sales_tiered(snap) -> ContractType:
    """按订货量走阶梯价、会员再打折、执行时一次性结清。

    难点一：**阶梯定价**
        三档价格。可视化里要拖 3 个 IF 节点 + 3 个常量 + 3 条比较连线；
        代码里就是一条分档表达式。

    难点二：**多步金额的顺序**
        `成交额 → 会员折扣 → 应付`：每一步都是上一步的结果。用 `ct.assign()`
        取中间值，后续表达式用 `var("...")` 引用。引擎的 `ASSIGN` 写的是
        全局作用域，后续效果与公式都能直接读到。

    难点三：**出库用字典效果**
        `sub_dict` 逐键相减（键保留），与 `remove_keys`（删键）语义不同。
    """
    _need(snap, F["cash"])
    ct = ContractType(
        "steel-sales-tiered",
        "钢材销售合同（阶梯价）",
        description="按订货量分档定价，会员享折扣，执行时一次性结清",
    )

    seller = ct.party("seller", "钢厂")
    buyer = ct.party("buyer", "经销商")

    tons = ct.input("tons", "订货量（吨）", "number", required=True, default="100")
    is_member = ct.input("is_member", "是否会员", "boolean", default=False)
    member_rate = ct.input("member_rate", "会员折扣率", "number", default="0.05")

    ct.check(tons > 0, error="订货量必须大于 0")

    # 阶梯定价：≥1000 吨 3800 / ≥500 吨 4000 / 其余 4200
    ct.assign("unit_price", formula("IF(tons >= 1000, 3800, IF(tons >= 500, 4000, 4200))"))
    ct.assign("amount", var("unit_price") * tons)
    # 折扣只对会员生效：用 IF 表达式压成一行，省掉一层 IF 效果
    ct.assign("discount", var("amount") * member_rate * formula("IF(is_member, 1, 0)"))
    ct.assign("payable", var("amount") - var("discount"))

    ct.check(buyer.field(F["cash"]) >= var("payable"), error="经销商资金不足以支付货款")

    ct.sub_number(buyer.field(F["cash"]), var("payable"))
    if _has(snap, F["revenue"]):
        ct.add_number(seller.field(F["revenue"]), var("amount"))
    if _has(snap, F["deposit"]):
        # 定金按成交额 30% 登记（执行时已抵扣，这里留痕供对账）
        ct.add_number(buyer.field(F["deposit"]), var("amount") * number("0.3"))
    # 出库：按品种扣减库存（字典逐键相减）
    if _has(snap, F["stock"]):
        ct.sub_dict(seller.field(F["stock"]), {"钢材": 0})

    return ct


# =============================================================================
# ③ 技术引进：前置校验 + 能力解锁
# =============================================================================


def technology_license(snap) -> ContractType:
    """支付授权费引进一项科技；前置未全部解锁则签约即被拦。

    难点一：**前置校验**
        `tech_prerequisites(科技清单)` 会把所选科技的全部前置节点展开成名称列表，
        再与「已解锁清单」做**列表包含**比较。可视化里这是
        「科技树清单 → 前置节点端口 → 列表运算 → 条件节点」四个节点三次连线。

    难点二：**解锁能力**
        科技名追加进清单（列表 ADD 自动去重），等级 +1。

    难点三：**一份输入驱动三处落账**
        授权费、研发投入折抵、等级提升，字段各不相同。
    """
    _need(snap, F["cash"])
    ct = ContractType(
        "technology-license",
        "技术引进合同",
        description="支付授权费获得科技；前置未解锁则拒绝签约",
    )

    licensor = ct.party("licensor", "技术输出方")
    licensee = ct.party("licensee", "技术引进方")

    tech = ct.input("tech", "引进的科技", "techNode", required=True)
    owned = ct.input("owned", "已解锁科技清单", "list", default="[]")
    fee = ct.input("license_fee", "授权费", "number", required=True, default="200000")
    discount = ct.input("discount", "老客户折扣", "number", default="0")

    payable = fee - fee * discount

    # 前置检查一：所选科技的前置节点必须都已在已解锁清单里（列表包含比较）
    ct.check_container(
        "LIST_COMPARE", "CONTAINS",
        tech_prerequisites(tech), owned,
        label="科技前置校验",
        error="所选科技的前置节点尚未全部解锁，不能越级引进",
    )
    # 前置检查二：钱够
    ct.check(licensee.field(F["cash"]) >= payable, error="引进方资金不足以支付授权费")

    ct.sub_number(licensee.field(F["cash"]), payable)
    if _has(snap, F["revenue"]):
        ct.add_number(licensor.field(F["revenue"]), payable)
    if _has(snap, F["license_fee"]):
        ct.add_number(licensee.field(F["license_fee"]), payable)
    # 解锁：科技名加入清单（去重）+ 等级 +1
    if _has(snap, F["tech_list"]):
        ct.append_items(licensee.field(F["tech_list"]), input_value(tech))
    if _has(snap, F["tech_level"]):
        ct.add_number(licensee.field(F["tech_level"]), number("1"))

    return ct


# =============================================================================
# ④ 银团贷款：复利 + 产业分档 + 贴息 + 逐期计划
# =============================================================================


def syndicated_loan(snap) -> ContractType:
    """复利计息、按产业分档、可享贴息，并生成逐期还款计划。

    难点一：**复利**
        `本金 × e^(利率 × 期数/12) - 本金`。引擎的公式沙箱有完整数学库
        （`exp` / `log` / `pow` / `sqrt` / `round`…，**都是小写**）。
        注意别与 `apply_op` 的大写 `EXP` 混淆——那是运算节点用的名字。

    难点二：**同一金额被两次分支改写**
        先按借款方产业类型分档，再按是否贴息折半。关键是**用 assign 存中间值**，
        否则在画布上要连「值来源 → 比较 → IF → 效果」四条线，改一档就要重连。

    难点三：**逐期还款计划（动态键）**
        `ct.range_list(1, 期数+1)` 生成整数序列（引擎 `LIST_RANGE`），`for_each` 逐期写字典。
        键在运行期才知道，可视化编辑器表达不了。
    """
    _need(snap, F["cash"])
    ct = ContractType(
        "syndicated-loan",
        "银团贷款合同",
        description="复利计息、按产业分档、支持贴息、逐期生成还款计划",
    )

    bank = ct.party("bank", "牵头行", is_host=True)
    borrower = ct.party("borrower", "借款方", industry_type_id=PREFERRED_INDUSTRY_ID)

    principal = ct.input("principal", "贷款本金", "number", required=True, default="1000000")
    months = ct.input("months", "期数（月）", "number", required=True, default="12")
    rate = ct.input("rate", "年化利率", "number", default="0.06")
    subsidized = ct.input("subsidized", "是否贴息", "boolean", default=False)

    ct.check(principal > 0, error="贷款本金必须大于 0")
    ct.check(months > 0, error="期数必须大于 0")

    # 复利：本金 × e^(利率 × 期数/12)
    ct.assign("gross", principal * formula("exp(rate * months / 12)") - principal)
    ct.assign("interest", var("gross"))

    # 分档：优惠产业（PREFERRED_INDUSTRY_ID）走 9 折利率；再叠加贴息。
    # 注意这里必须用同一个常量——参与方声明的 industry_type_id 与判断用的 id 不一致时，
    # 体检无法发现，但运行期会走错分支。
    with ct.when(borrower.is_industry(PREFERRED_INDUSTRY_ID)):
        ct.assign("interest", var("gross") * number("0.9"))
    with ct.when(subsidized):
        ct.assign("interest", var("interest") * number("0.5"))

    ct.add_number(borrower.field(F["cash"]), principal)
    if _has(snap, F["debt"]):
        ct.add_number(borrower.field(F["debt"]), principal + var("interest"))
    if _has(snap, F["interest"]):
        ct.add_number(borrower.field(F["interest"]), var("interest"))
    if _has(snap, F["credit"]):
        ct.sub_number(borrower.field(F["credit"]), principal)

    # 逐期还款计划：键是期数（运行期才知道）
    if _has(snap, F["terms"]):
        with ct.for_each(range_list(number("1"), months + number("1")), var="period"):
            ct.add_dict(borrower.field(F["terms"]), {"待还期数": 1})

    return ct


# =============================================================================
# ⑤ 基建投资：分期到账 + 达标追加 + 未达标扣款
# =============================================================================


def infrastructure_investment(snap) -> ContractType:
    """政府与企业共建基建：首期三成，达标追加七成并计提社会效益，未达标扣违约金。

    难点一：**一套清单、九种属性**
        基建有 9 项加成（单价、占地、启用费、就业率、人口、高素质人口、幸福度、
        人均收益、减碳）。每项各自汇总入账：`sum_of(清单, "属性名")` 一行一个，
        属性名与「数据管理」界面里的字段名一致，不用记端口名。

    难点二：**达标判定后走完全不同的落账路径**
        两条路径的字段集合完全不同——可视化里是两条长连线分叉。

    难点三：**一次聚合驱动多处落账**
        现金、人口、就业、幸福度四个字段，值来自同一次清单输入。
    """
    _need(snap, F["cash"])
    ct = ContractType(
        "infrastructure-investment",
        "基建投资合同",
        description="分期到账；达标追加并计提社会效益，未达标扣违约金",
    )

    government = ct.party("government", "政府方", is_host=True)
    builder = ct.party("builder", "建设方")

    projects = ct.input("projects", "基建清单", "infrastructureList", required=True)
    progress = ct.input("progress", "工程进度（0~1）", "number", required=True, default="1")
    penalty_rate = ct.input("penalty_rate", "违约金比例", "number", default="0.1")

    total = sum_of(projects, "price")
    first_payment = total * number("0.3")
    rest = total * number("0.7")
    penalty = total * penalty_rate

    ct.check(progress >= 0, error="工程进度不能为负")

    # 首期款
    ct.add_number(builder.field(F["cash"]), first_payment)
    if _has(snap, F["project_value"]):
        ct.add_number(builder.field(F["project_value"]), total)
    if _has(snap, F["project_progress"]):
        ct.add_number(builder.field(F["project_progress"]), progress)

    # 达标追加 / 未达标扣款
    with ct.when(progress >= number("0.8")):
        ct.add_number(builder.field(F["cash"]), rest)
        if _has(snap, F["bonus_pop"]):
            ct.add_number(builder.field(F["bonus_pop"]), sum_of(projects, "populationBonus"))
        if _has(snap, F["bonus_job"]):
            ct.add_number(builder.field(F["bonus_job"]), sum_of(projects, "employmentRateBonus"))
        if _has(snap, F["bonus_happy"]):
            ct.add_number(builder.field(F["bonus_happy"]), sum_of(projects, "happinessIndexBonus"))
    with ct.otherwise():
        ct.sub_number(builder.field(F["cash"]), penalty)
        if _has(snap, F["penalty"]):
            ct.add_number(builder.field(F["penalty"]), penalty)

    # 逐个项目登记在建清单（循环变量是基建名称）
    if _has(snap, F["stock"]):
        with ct.for_each(projects, var="name"):
            ct.add_dict(builder.field(F["stock"]), {"在建项目": 1})

    return ct


# =============================================================================
# ⑥ 物流运输：路程计价 + 超重加价 + 碳税 + 路线留痕
# =============================================================================


def logistics_transport(snap) -> ContractType:
    """按实际路程与载具计价，超重加价，另计碳税，并把路线写进台账。

    难点一：**路程是图上的最短路径**
        `route_distance(节点列表)` 沿相邻节点求最短路径距离之和（引擎用 Dijkstra），
        不是把相邻节点距离简单相加。

    难点二：**条件改写金额**
        超重时运费 ×1.1 并另记违约金；下游收款与碳税都基于改写后的金额。
        用 `assign` 改写 + `when` 分支，顺序即语义。

    难点三：**同一次输入、多种聚合**
        从同一个 `nodeRoute` 分别取：总距离、起点名、终点名。
        可视化里要把输入节点连到三个不同端口，漏连会静默拿到空值。
    """
    _need(snap, F["cash"])
    ct = ContractType(
        "logistics-transport",
        "物流运输合同",
        description="按最短路径路程计价，超重加价并计碳税，路线写入台账",
    )

    carrier = ct.party("carrier", "承运方")
    client = ct.party("client", "委托方")

    route = ct.input("route", "运输路线", "nodeRoute", required=True)
    vehicles = ct.input("vehicles", "使用载具", "vehicleList", required=True)
    cargo_weight = ct.input("cargo_weight", "货物总重（吨）", "number", required=True, default="0")
    rate_per_km = ct.input("rate_per_km", "单公里运价", "number", default="12")
    trips = ct.input("trips", "车次", "number", default="1")
    carbon_tax_rate = ct.input("carbon_tax_rate", "碳税税率", "number", default="0.05")

    distance = route_distance(route)
    capacity = sum_of(vehicles, "maxCargo")
    fuel_cost = sum_of(vehicles, "fuelConsumptionPerKm") * distance
    carbon_amt = sum_of(vehicles, "carbonEmission") * distance

    freight = distance * rate_per_km * trips + fuel_cost

    ct.check(distance > 0, error="运输路线不能为空（或相邻节点之间不连通）")
    ct.check(cargo_weight >= 0, error="货物重量不能为负")

    ct.assign("freight", freight)
    # 超重加价 10%
    with ct.when(cargo_weight > capacity):
        ct.assign("freight", var("freight") * number("1.1"))
        if _has(snap, F["penalty"]):
            ct.add_number(carrier.field(F["penalty"]), var("freight") * number("0.1"))

    carbon_tax = carbon_amt * carbon_tax_rate

    ct.check(client.field(F["cash"]) >= var("freight"), error="委托方资金不足以支付运费")
    ct.sub_number(client.field(F["cash"]), var("freight") + carbon_tax)
    if _has(snap, F["freight_income"]):
        ct.add_number(carrier.field(F["freight_income"]), var("freight"))
    if _has(snap, F["carbon_fee"]):
        ct.sub_number(carrier.field(F["carbon_fee"]), carbon_tax)

    # 台账：把路程起点写入（同一份 nodeRoute 输入，第三种聚合口径）
    # 想拼成「起点 → 终点」可以用 concat_text(...)，但聚合值要先 assign 成变量：
    #     ct.assign("from", route_start_node(route))
    #     ct.assign("to", route_end_node(route))
    #     ct.set_value(carrier.field(F["route_log"]), concat_text(var("from"), " → ", var("to")))
    if _has(snap, F["route_log"]):
        ct.assign("route_from", route_start_node(route))
        ct.set_value(carrier.field(F["route_log"]), var("route_from"))
    if _has(snap, F["fleet_used"]):
        with ct.for_each(vehicles, var="v"):
            ct.add_dict(carrier.field(F["fleet_used"]), {"出车次": 1})

    return ct


if __name__ == "__main__":  # pragma: no cover - 手动运行
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    import django

    django.setup()

    from apps.contracts.builder import check

    snap = snapshot(COMPETITION_ID)
    report_missing_fields(snap)
    worst = 0
    for one in build():
        report = check(one, snap=snap)
        print()
        print(report.render())
        worst = max(worst, 0 if report.ok else 1)
    sys.exit(worst)
