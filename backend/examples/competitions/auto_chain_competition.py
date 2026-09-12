# -*- coding: utf-8 -*-
"""汽车产业链测试赛：用一段代码建出「原料开采 → 零部件加工 → 整车进销」全链条比赛。

产业链
------

    上游资源区            中部智造区              东部车都
    ┌─────────┐  运输   ┌──────────┐   运输   ┌───────────┐
    │ 原料开采 │ ─────▶ │ 零部件加工│ ──────▶ │  整车进销  │
    │  (2001) │        │  (2002)  │         │   (2003)  │
    └─────────┘        └──────────┘         └───────────┘
     开采合同             购销合同             购销合同
     原矿入库           原料→零件(配比)        零件→整车(配比)

三大合同类型（开采 / 购销 / 运输）定义在同目录的姊妹脚本里，本脚本直接复用：
[`examples/contracts/auto_chain_contracts.py`](../contracts/auto_chain_contracts.py)。

**股票系统完全不动**：本脚本不调用 `stock()` / `account()` / `stock_config_set()`，
目标比赛的股票相关数据保持为空（沿用系统默认配置）。

用法
----

    cd backend

    # 0) 先建比赛（拿到 id；已存在则直接复用）
    .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_setup.py

    # 1) 只看会建出什么（不写库）
    .\\.venv\\Scripts\\python.exe manage.py build_competition examples/competitions/auto_chain_competition.py --inspect

    # 2) 预演导入（事务回滚，一行都不落库）
    .\\.venv\\Scripts\\python.exe manage.py build_competition examples/competitions/auto_chain_competition.py --competition <比赛id> --dry-run

    # 3) 真正导入
    .\\.venv\\Scripts\\python.exe manage.py build_competition examples/competitions/auto_chain_competition.py --competition <比赛id>

    # 4) 再导一次（覆盖模式）把「区域总览卡片」的产业字段 id 回填成真实主键
    #    —— 产业字段是全局资源，首次导入时还不存在，所以卡片需要第二遍才取到值
    $env:AUTO_CHAIN_COMPETITION_ID='<比赛id>'
    .\\.venv\\Scripts\\python.exe manage.py build_competition examples/competitions/auto_chain_competition.py --competition <比赛id> --mode overwrite

环境变量
--------

`AUTO_CHAIN_COMPETITION_ID`：设置后，建包时会把该比赛已存在的产业字段 id 回填到
区域总览卡片上（未设置则卡片字段 id 保持占位 0，只影响卡片取值，不影响导入）。
"""
from __future__ import annotations

import os
import sys

# 既支持 `manage.py build_competition` 加载，也支持直接 `python examples/competitions/auto_chain_competition.py`
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from apps.preparation.builder import (  # noqa: E402
    BuilderError,
    CompetitionBuilder,
)

try:  # 合同类型复用「合同类型代码化」脚本，保证两处永远同源
    from examples.contracts.auto_chain_contracts import build as build_contract_types
except ImportError:  # pragma: no cover - 直接按文件路径运行时的兜底
    import importlib.util
    from pathlib import Path

    _spec = importlib.util.spec_from_file_location(
        "auto_chain_contracts",
        Path(_BACKEND_DIR) / "examples" / "contracts" / "auto_chain_contracts.py",
    )
    assert _spec and _spec.loader
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _mod
    _spec.loader.exec_module(_mod)
    build_contract_types = _mod.build

#: 目标比赛 id（用于回填总览卡片的产业字段 id；不设置也能建包）
COMPETITION_ID = int(os.environ.get("AUTO_CHAIN_COMPETITION_ID") or 0)

#: 三大产业共用的字段 key 与合同脚本 `auto_chain_contracts.py` 的 `F` 一一对应
COMMON_FIELDS = (
    # (显示名, field_key, 类型, 说明)
    ("所在地", "location", "STRING", "地图节点名；运费与区域总览按它归属"),
    ("现金", "cash", "NUMBER", "合同结算的主账户"),
    ("银行存款", "bank_deposit", "NUMBER", "备用资金"),
    ("许可配额", "quota", "NUMBER", "开采量 / 产能 / 销量配额，开采合同按它扣减"),
    ("库存台账", "inventory", "DICTIONARY", "{物资: 数量}，购销合同的出入库对象"),
    ("业务台账", "ledger", "DICTIONARY", "{业务: 次数}，合同留痕"),
    ("碳排放", "carbon", "NUMBER", "合同按碳排系数计提"),
    ("累计合同额", "contract_amount", "NUMBER", "购销 / 运输合同的累计金额"),
    ("累计运输里程", "transport_km", "NUMBER", "运输合同累计公里数"),
    ("最近业务摘要", "last_deal", "STRING", "最近一次合同的对手方 / 摘要"),
)


def build() -> CompetitionBuilder:
    """返回构建好的一场汽车产业链比赛。"""

    # ==================== ① 比赛基础 ====================
    b = CompetitionBuilder("2026 汽车产业链测试赛", status="ACTIVE")
    b.fiscal_year(2026)
    # 股票系统：不调用 stock_config_set()（保持系统默认，不产出 stockConfig / stocks / 资金账户）

    # ==================== ② 行业口径：原料开采 / 零部件加工 / 整车进销 ====================
    mining = b.industry_type(2001, "原料开采", description="汽车产业链上游：锂 / 铝 / 铁矿石与橡胶硅砂开采")
    parts = b.industry_type(2002, "零部件加工", description="汽车产业链中游：原材料加工合成动力电池、电机、车身等零部件")
    sales = b.industry_type(2003, "整车进销", description="汽车产业链下游：零部件合成整车并进行批发、零售与出口")

    for it in (mining, parts, sales):
        _add_common_fields(b, it)

    # 各产业特有字段（只做展示与统计，合同不引用它们 —— 保证同一份合同模板三业通用）
    b.add_field(mining, "累计开采量", "mined_total", field_type="NUMBER", default_value="0", sort_order=20)
    b.add_field(mining, "矿区数", "mine_count", field_type="NUMBER", default_value="0", sort_order=21)
    b.add_field(parts, "累计零件产量", "parts_output", field_type="NUMBER", default_value="0", sort_order=20)
    b.add_field(parts, "年产能（件）", "capacity", field_type="NUMBER", default_value="0", sort_order=21)
    b.add_field(sales, "整车交付量", "delivered_units", field_type="NUMBER", default_value="0", sort_order=20)
    b.add_field(sales, "销售收入", "sales_revenue", field_type="NUMBER", default_value="0", sort_order=21)

    # ==================== ⑤ 地理与物流（先建地图，原料地点价要按节点定价） ====================
    mine_node = b.node_type("矿区", color="#b45309", description="原矿开采地")
    park = b.node_type("产业园区", color="#2563eb", description="加工制造基地")
    hub = b.node_type("物流枢纽", color="#0ea5e9", description="集运站 / 港口 / 铁路货场")
    market = b.node_type("销售中心", color="#7c3aed", description="整车展销与交付中心")

    road = b.path_type("公路", color="#94a3b8")
    rail = b.path_type("铁路", color="#a16207")
    water = b.path_type("内河航运", color="#0369a1")

    n_li = b.node("白云鄂博矿区", mine_node, region="上游资源区", x=140, y=120)
    n_alu = b.node("戈壁铝土矿区", mine_node, region="上游资源区", x=140, y=300)
    n_rub = b.node("橡胶硅砂基地", mine_node, region="上游资源区", x=140, y=480)
    n_up = b.node("上游集运站", hub, region="上游资源区", x=360, y=300)
    n_park = b.node("中部智造园", park, region="中部智造区", x=620, y=300)
    n_yard = b.node("中原铁路货场", hub, region="中部智造区", x=620, y=470)
    n_port = b.node("东部车都港", hub, region="东部车都", x=900, y=220)
    n_show = b.node("车都展销中心", market, region="东部车都", x=1040, y=380)

    b.edge(n_li, n_up, 120, road)
    b.edge(n_alu, n_up, 80, road)
    b.edge(n_rub, n_up, 160, road)
    b.edge(n_up, n_park, 420, rail)          # 干线：矿区 → 智造园（铁路）
    b.edge(n_park, n_up, 430, road)          # 反向独立连线（唯一约束是「起点+终点」）
    b.edge(n_up, n_port, 1200, water)        # 水运直达整车港
    b.edge(n_park, n_yard, 60, road)
    b.edge(n_yard, n_port, 400, rail)
    b.edge(n_park, n_port, 380, road)
    b.edge(n_port, n_park, 390, rail)
    b.edge(n_port, n_show, 60, road)

    # ==================== ④ 物资与产能 ====================
    diesel = b.fuel("柴油", price_per_liter="7.6")
    power = b.fuel("电力", price_per_liter="0.8")  # 每度电价：电动重卡 / 电力机车用

    li_ore = b.material("锂矿石", origin="白云鄂博矿区", carbon_emission_coefficient=0.52,
                        node_prices={n_li: "180", n_up: "195", n_park: "215", n_port: "240"})
    al_ore = b.material("铝土矿", origin="戈壁铝土矿区", carbon_emission_coefficient=0.41,
                        node_prices={n_alu: "165", n_up: "180", n_park: "205", n_port: "230"})
    fe_ore = b.material("铁矿石", origin="白云鄂博矿区", carbon_emission_coefficient=0.48,
                        node_prices={n_li: "120", n_up: "132", n_park: "150", n_port: "168"})
    rubber = b.material("天然橡胶", origin="橡胶硅砂基地", carbon_emission_coefficient=0.33,
                        node_prices={n_rub: "90", n_up: "98", n_park: "110", n_port: "126"})
    silica = b.material("石英砂", origin="橡胶硅砂基地", carbon_emission_coefficient=0.22,
                        node_prices={n_rub: "60", n_up: "66", n_park: "75", n_port: "86"})

    t_battery = b.tech("电池成组技术", tier=1, research_cost="80000", description="解锁动力电池包")
    t_motor = b.tech("电驱系统集成", tier=1, research_cost="60000", description="解锁驱动电机")
    t_light = b.tech("轻量化车身工艺", tier=1, research_cost="50000", description="解锁铝合金车身")
    t_platform = b.tech("整车平台化", tier=2, research_cost="200000",
                        description="解锁整车产品", prerequisites=[t_battery, t_motor])

    # 依赖方向固定：原料 → 零件 → 产品
    p_battery = b.part("动力电池包", materials={li_ore: 4, al_ore: 1}, tech=[t_battery])
    p_motor = b.part("驱动电机", materials={fe_ore: 2, al_ore: 2}, tech=[t_motor])
    p_body = b.part("铝合金车身", materials={al_ore: 4, fe_ore: 1}, tech=[t_light])
    p_tire = b.part("汽车轮胎", materials={rubber: 3, fe_ore: 1})
    p_cockpit = b.part("智能座舱域控", materials={silica: 3, al_ore: 1}, tech=[t_motor])

    prod_sedan = b.product("纯电轿车", parts={p_battery: 1, p_motor: 1, p_body: 1, p_tire: 4, p_cockpit: 1},
                           tech=[t_platform])
    prod_suv = b.product("纯电SUV", parts={p_battery: 1, p_motor: 2, p_body: 1, p_tire: 4, p_cockpit: 1},
                         tech=[t_platform])
    prod_truck = b.product("商用电动轻卡", parts={p_battery: 2, p_motor: 2, p_body: 1, p_tire: 6},
                           tech=[t_platform])

    b.line("电芯产线", price="2400000", labor_count=120, max_per_year="6000")
    b.line("电驱总装线", price="1600000", labor_count=80, max_per_year="8000")
    b.line("车身冲压线", price="1200000", labor_count=60, max_per_year="9000")
    b.line("整车总装线", price="3600000", labor_count=200, max_per_year="4000")

    b.infrastructure("智能充电站", footprint=80, price="600000", activation_price="30000",
                     carbon_reduction_bonus=0.04, happiness_index_bonus=0.01)
    b.infrastructure("汽车试验场", footprint=200, price="1500000", activation_price="80000",
                     happiness_index_bonus=0.03, per_capita_income_bonus=0.02)
    b.infrastructure("光伏电站", footprint=160, price="1200000", activation_price="50000",
                     employment_rate_bonus=0.02, carbon_reduction_bonus=0.12)

    b.warehouse("原料仓", "MATERIAL", capacity="30000", price="400000")
    b.warehouse("零件仓", "PART", capacity="20000", price="300000")
    b.warehouse("整车成品仓", "PRODUCT", capacity="8000", price="600000")
    b.warehouse("燃料储罐", "FUEL", capacity="10000", price="200000")

    b.vehicle("矿用自卸车", fuel=diesel, path_types=[road], fuel_consumption_per_km=0.45,
              max_cargo=60, price="900000", carbon_emission=1.2)
    b.vehicle("重型卡车", fuel=diesel, path_types=[road], fuel_consumption_per_km=0.35,
              max_cargo=30, price="260000", carbon_emission=0.9)
    b.vehicle("商品车运输车", fuel=diesel, path_types=[road], fuel_consumption_per_km=0.42,
              max_cargo=12, price="480000", carbon_emission=1.0)
    b.vehicle("电动重卡", fuel=power, path_types=[road], fuel_consumption_per_km=1.2,
              max_cargo=25, price="620000", carbon_emission=0.2)
    b.vehicle("货运列车", fuel=power, path_types=[rail], fuel_consumption_per_km=0.05,
              max_cargo=800, price="3200000", carbon_emission=0.25)
    b.vehicle("内河滚装船", fuel=diesel, path_types=[water], fuel_consumption_per_km=0.06,
              max_cargo=1500, price="5200000", carbon_emission=0.3)

    # ==================== ⑥ 科技与需求 ====================
    b.demand("东部车都", prod_sedan, 1200, note="城市通勤主力车型")
    b.demand("东部车都", prod_suv, 600, note="家庭用车")
    b.demand("中部智造区", prod_truck, 300, note="园区物流用车")
    b.demand("上游资源区", prod_truck, 120, note="矿区自用与通勤")

    # ==================== ③ 参赛主体（每家公司都在产业链上占一个位置） ====================
    up_region = b.region("上游资源区", description="锂 / 铝 / 铁矿与橡胶硅砂资源带")
    mid_region = b.region("中部智造区", description="动力电池、电驱与轻量化车身产业带")
    east_region = b.region("东部车都", description="整车制造、展销与出口集散地")

    # —— 原料开采 ——
    li_corp = _company(b, "西岭锂业", mining, up_region, node="白云鄂博矿区",
                       cash="1200000", bank="300000", quota="800",
                       inventory={"原矿": 120, "锂矿石": 40})
    al_corp = _company(b, "戈壁铝业", mining, up_region, node="戈壁铝土矿区",
                       cash="900000", bank="200000", quota="600",
                       inventory={"原矿": 80, "铝土矿": 30})
    fe_corp = _company(b, "白云矿业", mining, up_region, node="白云鄂博矿区",
                       cash="800000", bank="150000", quota="500",
                       inventory={"原矿": 60, "铁矿石": 25})

    # —— 零部件加工 ——
    battery_co = _company(b, "中原创能", parts, mid_region, node="中部智造园",
                          cash="1500000", bank="500000", quota="600",
                          inventory={"货物": 60, "锂矿石": 20})
    motor_co = _company(b, "智造电驱", parts, mid_region, node="中部智造园",
                        cash="1200000", bank="400000", quota="500",
                        inventory={"货物": 45})
    body_co = _company(b, "轻量化车身厂", parts, mid_region, node="中原铁路货场",
                       cash="1000000", bank="300000", quota="400",
                       inventory={"货物": 30})

    # —— 整车进销 ——
    oem_co = _company(b, "车都新能源", sales, east_region, node="东部车都港",
                      cash="3000000", bank="1000000", quota="400",
                      inventory={"货物": 40, "零件": 20})
    dealer_co = _company(b, "东都汽车销售", sales, east_region, node="车都展销中心",
                         cash="2000000", bank="800000", quota="300",
                         inventory={"货物": 25})
    export_co = _company(b, "车都出口贸易", sales, east_region, node="东部车都港",
                         cash="1800000", bank="600000", quota="300",
                         inventory={"货物": 18})

    # ==================== ⑦ 市场与规则 ====================
    # 合同类型：直接复用「合同类型代码化」脚本产出的四份 JSON（同源，不手写 JSON）
    ct_refs = _register_contract_types(b)

    # 预设合同实例：保持 DRAFT（草稿）不落账，开赛后由玩家填写并提交。
    # 注意：导入侧按「比赛 + 合同类型 + 名称」判重，而名称缺省取合同类型名，
    # 所以每种合同类型只预置一份（区分单据用参与方的 contractNumber）。
    b.contract(
        contract_type=ct_refs["auto-mining"],
        parties=[{"role": "miner", "company": li_corp, "contractNumber": "MIN-2026-001"}],
        inputs={"ore_type": "锂矿石", "quantity": 20, "royalty_rate": 60,
                "env_fee_rate": 8, "carbon_factor": 0.5},
        status="DRAFT",
    )
    b.contract(
        contract_type=ct_refs["auto-purchase-sale"],
        parties=[{"role": "seller", "company": li_corp, "contractNumber": "SL-2026-001"},
                 {"role": "buyer", "company": battery_co, "contractNumber": "BY-2026-001"}],
        inputs={"goods": {"锂矿石": 20}, "discount": 0},
        status="DRAFT",
    )
    b.contract(
        contract_type=ct_refs["auto-transport"],
        parties=[{"role": "client", "company": battery_co, "contractNumber": "PL-2026-001"},
                 {"role": "carrier", "company": oem_co, "contractNumber": "TR-2026-001"}],
        # ⚠️ 引擎执行时**不会**套用 inputSchema 的默认值（未提供的输入项按 0 参与运算），
        #    所以预置实例要把每个输入项都显式填好；路线 route 留给玩家按当轮货物选择。
        inputs={"rate_per_km": 12, "trips": 1, "cargo_weight": 20,
                "carbon_tax_rate": 0.05, "vehicles": {"重型卡车": 2}},
        status="DRAFT",
    )

    # 区域总览卡片（展示各环节的关键指标）
    b.card(up_region, li_corp, "cash", display_name="西岭锂业现金")
    b.card(up_region, li_corp, "inventory", display_name="西岭锂业库存")
    b.card(up_region, al_corp, "cash", display_name="戈壁铝业现金")
    b.card(mid_region, battery_co, "cash", display_name="中原创能现金")
    b.card(mid_region, battery_co, "inventory", display_name="中原创能库存")
    b.card(mid_region, motor_co, "cash", display_name="智造电驱现金")
    b.card(east_region, oem_co, "cash", display_name="车都新能源现金")
    b.card(east_region, oem_co, "inventory", display_name="车都新能源库存")
    b.card(east_region, dealer_co, "cash", display_name="东都汽车销售现金")

    # ==================== ⑧ 账号与权限 ====================
    # 每个玩家账号横跨「原料 → 加工 → 进销」三家公司，便于一个人跑通全链条
    chain_a = [li_corp, battery_co, oem_co]
    chain_b = [al_corp, motor_co, dealer_co]
    chain_c = [fe_corp, body_co, export_co]
    # 刻意不填 stock_company_scopes：本场不启用股票系统，账号不做任何股票范围绑定
    b.user("auto_player_a", role="PLAYER", display_name="玩家A（锂电链）",
           company_scopes=chain_a, view_company_scopes=chain_a,
           contract_view_company_scopes=chain_a)
    b.user("auto_player_b", role="PLAYER", display_name="玩家B（铝驱链）",
           company_scopes=chain_b, view_company_scopes=chain_b,
           contract_view_company_scopes=chain_b)
    b.user("auto_player_c", role="PLAYER", display_name="玩家C（铁矿车身链）",
           company_scopes=chain_c, view_company_scopes=chain_c,
           contract_view_company_scopes=chain_c)
    all_companies = chain_a + chain_b + chain_c
    b.user("auto_referee", role="COMPETITION_ADMIN", display_name="本场裁判",
           company_scopes=all_companies, view_company_scopes=all_companies,
           contract_view_company_scopes=all_companies,
           permissions=["contract:manage", "contract:audit", "contract:execute"])

    # 比赛内消息
    b.message(
        "开局公告",
        "欢迎参加 2026 汽车产业链测试赛。本场共三大产业：上游「原料开采」、"
        "中游「零部件加工」、下游「整车进销」。请先在「公司管理」核对本公司初始字段，"
        "再到「合同管理」查看三份待签合同（开采 / 购销 / 运输）。",
        to_all=True,
    )
    b.message(
        "产业链玩法说明",
        "① 开采企业用「开采合同」缴纳权利金与环保费取得原矿（扣减许可配额）；\n"
        "② 用「运输合同」把原矿从矿区运到中部智造园（按最短路径计费，超重加价）；\n"
        "③ 用「购销合同」把原料卖给加工企业，加工企业按零件配比生产零部件；\n"
        "④ 再用「运输合同」把零部件运到东部车都，用「购销合同」卖给整车企业；\n"
        "⑤ 整车企业按产品配比总装整车，交付东部车都的消费者需求。",
        to_all=True,
    )
    b.message("裁判提示", "合同执行金额请保留两位小数；提交前可用合同详情里的「试算」核对落账。", to_all=True)

    # 总览卡片的产业字段 id 回填（第二遍导入时生效）
    _backfill_card_field_ids(b)
    return b


# =============================================================================
# 内部工具
# =============================================================================


def _add_common_fields(b: CompetitionBuilder, industry_type) -> None:
    """给一个产业类型加上「三大产业共用」的那套字段。

    合同模板只引用这些 key，因此同一份合同可以被链上任意一环的公司使用。
    """
    for index, (label, key, field_type, _desc) in enumerate(COMMON_FIELDS, start=1):
        if key == "total_cash":
            continue
        kwargs = {}
        if field_type == "DICTIONARY":
            kwargs["config"] = {"valueType": "NUMBER"}
            kwargs["default_value"] = "{}"
        elif field_type == "NUMBER":
            kwargs["default_value"] = "0"
        elif field_type == "STRING":
            kwargs["default_value"] = ""
        b.add_field(industry_type, label, key, field_type=field_type, sort_order=index, **kwargs)
    # 计算字段：货币资金 = 现金 + 银行存款（与财年定时器字段互斥，这里不用定时器）
    b.add_field(
        industry_type,
        "货币资金",
        "total_cash",
        field_type="NUMBER",
        is_calculated=True,
        graph=_sum_graph("cash", "bank_deposit"),
        sort_order=4,
    )


def _sum_graph(key_a: str, key_b: str) -> dict:
    """构造「字段A + 字段B」的**产业计算图**（GGraph）。

    ⚠️ 这里刻意不直接用建包库自带的 `calc_node` / `calc_graph` 助手：
    它们产出的是「合同编辑器风格」的图（节点 `type` 直接写 `ADD` / `FIELD`，
    连线用 `from`/`to`/`fromPort`/`toPort`），而**产业计算字段求值器**
    （`apps/company_fields/calc.py::_eval_graph`）读的是前端「产业计算图」编辑器的 GGraph：

    - 节点 `type` 只能是 `output` / `value` / `if` / `assign`，数值源写在 `data.kind`；
    - 连线用 `source` / `target` / `sourceHandle` / `targetHandle`；
    - 必须**有且只有一个 `output` 汇点**，OP 节点的入参端口名取自 `OP_ARG_SPECS`
      （`ADD` → `left` / `right`）。

    用前一种结构建出来的计算字段，重算时会被直接跳过
    （日志提示「计算图无输出/求值为空」），字段永远是空的 —— 所以这里按求值器认识的结构书写。
    """
    return {
        "nodes": [
            {"id": "out", "type": "output", "data": {}, "position": {"x": 620, "y": 200}},
            {"id": "op_add", "type": "value", "data": {"kind": "OP", "op": "ADD"},
             "position": {"x": 380, "y": 200}},
            {"id": "f_a", "type": "value", "data": {"kind": "FIELD", "fieldKey": key_a},
             "position": {"x": 120, "y": 120}},
            {"id": "f_b", "type": "value", "data": {"kind": "FIELD", "fieldKey": key_b},
             "position": {"x": 120, "y": 280}},
        ],
        "edges": [
            {"id": "e_a", "source": "f_a", "target": "op_add", "sourceHandle": "out", "targetHandle": "left"},
            {"id": "e_b", "source": "f_b", "target": "op_add", "sourceHandle": "out", "targetHandle": "right"},
            {"id": "e_out", "source": "op_add", "target": "out", "sourceHandle": "out", "targetHandle": "value"},
        ],
    }


def _company(b: CompetitionBuilder, name, industry_type, region, *, node, cash, bank, quota, inventory):
    """登记一家公司：所在地、资金、配额、初始库存一次填齐。"""
    import json

    return b.company(
        name,
        industry_type=industry_type,
        region=region,
        field_values={
            "location": node,
            "cash": cash,
            "bank_deposit": bank,
            "quota": quota,
            "inventory": json.dumps(inventory, ensure_ascii=False),
            "ledger": "{}",
            "carbon": "0",
            "contract_amount": "0",
            "transport_km": "0",
            "last_deal": "开局初始化",
        },
    )


def _register_contract_types(b: CompetitionBuilder) -> dict:
    """把「合同类型代码化」脚本产出的三个合同类型登记进本包（同源，不手写 JSON）。"""
    refs: dict = {}
    for ct in build_contract_types():
        body = ct.payload()
        refs[body["key"]] = b.contract_type(
            body["key"],
            body["name"],
            description=body.get("description"),
            party_roles=body.get("partyRoles") or [],
            input_schema=body.get("inputSchema") or [],
            effects=body.get("effects") or [],
            conditions=body.get("conditions") or [],
            enabled=bool(body.get("enabled", True)),
        )
    return refs


def _backfill_card_field_ids(b: CompetitionBuilder) -> None:
    """回填区域总览卡片的 `industryFieldId`（数据库主键）。

    产业字段是**全局资源**，首次导入某个库时它们还不存在，所以卡片第一遍拿不到 id
    （只是取不到值，不会报错）。设置 `AUTO_CHAIN_COMPETITION_ID` 后，本函数会读取
    目标库已导出的「行业口径」归档，按 (产业类型 code, fieldKey) 查出真实 id 回填，
    再用 `--mode overwrite` 导一次即可刷新卡片。
    """
    if not COMPETITION_ID:
        print("[提示] 未设置 AUTO_CHAIN_COMPETITION_ID：总览卡片的 industryFieldId 保持占位 0"
              "（只影响卡片取值，不影响导入）")
        return
    try:
        from apps.preparation import archive

        reference = archive.build_export(COMPETITION_ID, scope="industry")
    except Exception as exc:  # noqa: BLE001 - 回填失败不应阻断建包
        print(f"[提示] 读取参照归档失败（{type(exc).__name__}: {exc}）；卡片字段 id 保持占位 0")
        return
    rows = ((reference.get("resources") or {}).get("industryFields") or {}).get("rows") or []
    if not rows:
        print("[提示] 目标库里还没有这些产业字段：卡片字段 id 保持占位 0，"
              "先导入一次，再带 AUTO_CHAIN_COMPETITION_ID 用 --mode overwrite 导一次即可回填")
        return
    try:
        b.resolve_field_ids(reference)
    except BuilderError as exc:
        print(f"[提示] 卡片字段 id 回填失败：{exc}")
    else:
        print(f"[提示] 已按比赛 #{COMPETITION_ID} 回填 {len(rows)} 条产业字段 id 到总览卡片")


if __name__ == "__main__":  # pragma: no cover - 手动运行入口：只打印产出摘要
    _builder = build()
    _archive = _builder.build()
    print(f"比赛名：{_archive['sourceCompetition']['name']}")
    for _res, _block in _archive["resources"].items():
        print(f"  {_block['label']:<14} {_block['count']:>4} 条  [{_res}]")
    _warnings = _builder.validate()
    print(f"体检提醒 {len(_warnings)} 条：")
    for _w in _warnings:
        print(f"  · {_w}")
