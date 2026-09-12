# -*- coding: utf-8 -*-
"""建包库完整示例：用一段简单代码建出「2026 春季钢铁商赛」的全部比赛内容。

这是**可运行的建包脚本**，覆盖 archive 支持导入的全部 35 类资源。
直接照抄改数即可用于自己的比赛。

用法（在 backend 目录下执行）：

    # 1) 只看会建出什么（不连数据库）
    python manage.py build_competition examples/competitions/demo_competition.py --inspect

    # 2) 导出归档 JSON（可从前端「比赛准备 → 导入归档」上传）
    python manage.py build_competition examples/competitions/demo_competition.py --out demo.json

    # 3) 预演导入（事务回滚，不留痕）
    python manage.py build_competition examples/competitions/demo_competition.py --competition <比赛id> --dry-run

    # 4) 真正导入
    python manage.py build_competition examples/competitions/demo_competition.py --competition <比赛id>

也可以完全脱离 Django 使用：

    from apps.preparation.builder import CompetitionBuilder   # 或把本文件当普通脚本跑
"""
from apps.preparation.builder import CompetitionBuilder, calc_graph, calc_node


def build() -> CompetitionBuilder:
    """返回构建好的一场比赛（本文件即为「用代码写比赛」的模板）。"""

    # ==================== ① 比赛基础 ====================
    b = CompetitionBuilder(
        "2026 春季钢铁商赛",
        status="ACTIVE",
        # 地图背景图（可选）：仅记录地址与尺寸，不搬运图片本体
        map_background={"url": "/uploads/maps/steel-2026.png", "filename": "steel-2026.png",
                        "width": 1920, "height": 1080},
    )
    # 财年：新建财年 / 由非 ACTIVE 改为 ACTIVE 会触发 FY_START 定时器
    b.fiscal_year(2026)
    # 股票系统参数（可选）：不设置就沿用系统默认
    b.stock_config_set(
        {
            "limitPct": 0.1,      # 单轮限幅
            "maxMovePct": 0.08,   # 单轮最大波动（应 ≤ limitPct）
            "mmMinQty": 100,      # 做市商最小数量
            "mmMaxQty": 5000,     # 做市商最大数量（应 ≥ mmMinQty）
        }
    )

    # ==================== ② 行业口径（全局资源，各比赛共用） ====================
    steel = b.industry_type(1, "钢铁", description="钢铁冶炼与加工")
    # 「所在地」字段：地图与运费逻辑依赖它，每个产业类型都要有
    b.add_field(steel, "所在地", "location", field_type="STRING", sort_order=1)
    b.add_field(steel, "现金", "cash", field_type="NUMBER", default_value="0", sort_order=2)
    b.add_field(steel, "银行存款", "bank_deposit", field_type="NUMBER", default_value="0", sort_order=3)
    # 计算字段：由计算图自动推导（与财年定时器字段互斥）
    b.add_field(
        steel,
        "货币资金",
        "total_cash",
        field_type="NUMBER",
        is_calculated=True,
        graph=calc_graph(
            calc_node("add", node_id="sum"),
            calc_node("field", node_id="cash_in", fieldKey="cash"),
            calc_node("field", node_id="bank_in", fieldKey="bank_deposit"),
        ),
        sort_order=4,
    )
    # 财年定时器字段：每年开始自动改写（例如按年计提利息前重置预算）
    b.add_field(
        steel,
        "年度预算",
        "annual_budget",
        field_type="NUMBER",
        timer_enabled=True,
        timer_trigger="FY_START",
        timer_value="1000000",
        sort_order=5,
    )

    # ==================== ③ 参赛主体 ====================
    east = b.region("东区", description="沿海钢铁产业带")
    west = b.region("西区", description="内陆装备制造带")
    a_steel = b.company(
        "甲钢铁集团", industry_type=steel, region=east,
        field_values={"location": "东区港", "cash": "800000", "bank_deposit": "200000"},
    )
    b_steel = b.company(
        "乙特钢", industry_type=steel, region=west,
        field_values={"location": "西区站", "cash": "500000", "bank_deposit": "500000"},
    )
    c_machine = b.company(
        "丙机械", industry_type=steel, region=west,
        field_values={"location": "西区站", "cash": "600000", "bank_deposit": "400000"},
    )

    # ==================== ⑤ 地理与物流 ====================
    city = b.node_type("城市", color="#3b82f6", description="内陆城市节点")
    port = b.node_type("港口", color="#0ea5e9", description="沿海港口节点")
    road = b.path_type("公路", color="#94a3b8")
    rail = b.path_type("铁路", color="#a16207")
    sea = b.path_type("海运", color="#0369a1")

    n_port = b.node("东区港", port, region="东区", x=320, y=180)
    n_west = b.node("西区站", city, region="西区", x=760, y=260)
    n_mine = b.node("北山矿", city, region="西区", x=640, y=80)
    n_sea = b.node("外海港", port, region="东区", x=120, y=60)

    b.edge(n_port, n_west, 420, rail)
    b.edge(n_mine, n_west, 180, road)
    b.edge(n_port, n_sea, 260, sea)
    b.edge(n_west, n_port, 430, road)  # 反向也算一条独立连线（唯一约束是「起点+终点」）

    # ==================== ④ 物资与产能 ====================
    diesel = b.fuel("柴油", price_per_liter="7.5")
    iron = b.material(
        "铁矿石", origin="北山矿", carbon_emission_coefficient=0.52,
        node_prices={n_mine: "120", n_port: "138"},  # 地点价：按地图节点差异定价
    )
    coal = b.material("焦煤", origin="北山矿", carbon_emission_coefficient=0.68, type="NORMAL")

    t_smelt = b.tech("高炉冶炼", tier=1, research_cost="5000", description="解锁铁锭生产")
    t_roll = b.tech("热轧工艺", tier=2, research_cost="12000", prerequisites=[t_smelt])

    # 依赖方向固定为「原料 → 零件 → 产品」：零件配比只能引用原料，产品配比只能引用零件
    # （模型里没有「零件用零件」的关系，写错会被建包库直接拦下）。
    p_iron = b.part("铁锭", materials={iron: 2, coal: 1}, tech=[t_smelt])
    p_billet = b.part("粗钢坯", materials={iron: 3, coal: 2}, tech=[t_smelt])
    p_slab = b.part("热轧板坯", materials={iron: 4, coal: 1}, tech=[t_roll])
    prod_plate = b.product("热轧钢板", parts={p_slab: 2, p_billet: 1}, tech=[t_roll])
    prod_rebar = b.product("螺纹钢", parts={p_billet: 2})

    b.line("一号高炉线", price="1200000", labor_count=40, max_per_year="5000")
    b.line("二号轧钢线", price="800000", labor_count=25, max_per_year="8000")
    b.infrastructure(
        "自备电厂", footprint=120, price="900000", activation_price="50000",
        employment_rate_bonus=0.02, population_bonus=0.01, happiness_index_bonus=0.01,
        per_capita_income_bonus=0.03, carbon_reduction_bonus=0.05,
    )
    b.warehouse("原料仓", "MATERIAL", capacity="20000", price="300000")
    b.warehouse("零件仓", "PART", capacity="10000", price="200000")
    b.warehouse("成品仓", "PRODUCT", capacity="15000", price="250000")
    b.warehouse("燃料罐", "FUEL", capacity="8000", price="150000")

    truck = b.vehicle(
        "重型卡车", fuel=diesel, path_types=[road], fuel_consumption_per_km=0.35,
        max_cargo=30, price="260000", carbon_emission=0.9,
    )
    b.vehicle(
        "货运列车", fuel=diesel, path_types=[rail], fuel_consumption_per_km=0.08,
        max_cargo=500, price="1800000", carbon_emission=0.4,
    )
    b.vehicle(
        "散货船", fuel=diesel, path_types=[sea], fuel_consumption_per_km=0.05,
        max_cargo=2000, price="5200000", carbon_emission=0.3,
    )

    # ==================== ⑥ 科技与需求 ====================
    b.demand("东区", prod_plate, 1200, note="基建用钢")
    b.demand("西区", prod_rebar, 900, note="房地产用钢")
    b.demand("西区", prod_plate, 400)

    # ==================== ⑦ 市场与规则 ====================
    # 区域总览卡片：把公司字段展示到区域页面上。
    # 卡片里的 industryFieldId 是数据库主键，纯代码建包时先用占位值 0，
    # 导入后用 resolve_field_ids(导出的归档) 回填再导一次（见文件末尾注释）。
    b.card(east, a_steel, "cash", display_name="现金")
    b.card(east, a_steel, "total_cash", display_name="货币资金")
    b.card(west, b_steel, "cash", display_name="现金")
    b.card(west, c_machine, "cash", display_name="现金")

    contract_sale = b.contract_type(
        "steel-sale",
        "钢材销售合同",
        description="买方以现金向卖方采购热轧钢板",
        party_roles=[
            {"role": "seller", "label": "卖方"},
            {"role": "buyer", "label": "买方"},
        ],
        input_schema=[
            {"key": "quantity", "label": "数量", "type": "NUMBER", "required": True},
            {"key": "unitPrice", "label": "单价", "type": "NUMBER", "required": True},
            {"key": "amount", "label": "金额", "type": "NUMBER", "required": False},
        ],
        conditions=[
            {"kind": "FIELD", "party": "buyer", "fieldKey": "cash", "op": "GTE",
             "value": {"from": "input", "key": "amount"}},
        ],
        effects=[
            {"kind": "FIELD", "party": "buyer", "fieldKey": "cash", "op": "SUB",
             "value": {"from": "input", "key": "amount"}},
            {"kind": "FIELD", "party": "seller", "fieldKey": "cash", "op": "ADD",
             "value": {"from": "input", "key": "amount"}},
        ],
    )
    contract_loan = b.contract_type(
        "bank-loan",
        "银行贷款合同",
        description="公司从银行取得贷款，现金增加、银行存款减少",
        party_roles=[
            {"role": "bank", "label": "银行", "isHost": True},
            {"role": "borrower", "label": "借款方"},
        ],
        input_schema=[{"key": "amount", "label": "贷款金额", "type": "NUMBER", "required": True}],
        effects=[
            {"kind": "FIELD", "party": "borrower", "fieldKey": "cash", "op": "ADD",
             "value": {"from": "input", "key": "amount"}},
            {"kind": "FIELD", "party": "borrower", "fieldKey": "bank_deposit", "op": "SUB",
             "value": {"from": "input", "key": "amount"}},
        ],
    )
    # 预设合同实例：保持 DRAFT（草稿）就不会落账，开赛后由玩家填写并提交。
    # 注意：合同名缺省取「合同类型名」，这也是导入侧的判重口径
    #（同一合同类型在一场比赛内通常只预置一份；区分不同实例请用参与方的 contractNumber）。
    b.contract(
        contract_type=contract_sale,
        parties=[
            {"role": "seller", "company": a_steel, "contractNumber": "S-2026-001"},
            {"role": "buyer", "company": c_machine, "contractNumber": "B-2026-001"},
        ],
        inputs={"quantity": 300, "unitPrice": 3200, "amount": 960000},
        status="DRAFT",
    )
    b.contract(
        contract_type=contract_loan,
        parties=[{"role": "borrower", "company": b_steel, "contractNumber": "L-2026-001"}],
        inputs={"amount": 500000},
        status="DRAFT",
    )

    b.stock(
        "600001", "甲钢铁", company=a_steel, total_shares="12000",
        init_net_profit="8000", init_price="12.5", industry_pe=15.0,
    )
    b.stock(
        "600002", "乙特钢", company=b_steel, total_shares="30000",
        init_net_profit="9000", init_price="9.8",
    )
    b.stock("600003", "丙机械", company=c_machine, total_shares="20000",
            init_net_profit="4000", init_price="18.2")

    # ==================== ⑧ 账号与权限 ====================
    # 先把账号登记出来，才能给资金账户指定「用户账户」
    p_a = b.user("player_a", role="PLAYER", display_name="甲钢铁操盘手",
                 company_scopes=[a_steel], view_company_scopes=[a_steel],
                 contract_view_company_scopes=[a_steel], stock_company_scopes=[a_steel])
    b.user("player_b", role="PLAYER", display_name="乙特钢操盘手",
           company_scopes=[b_steel], view_company_scopes=[b_steel],
           contract_view_company_scopes=[b_steel], stock_company_scopes=[b_steel])
    b.user("player_c", role="PLAYER", display_name="丙机械操盘手",
           company_scopes=[c_machine], view_company_scopes=[c_machine],
           contract_view_company_scopes=[c_machine], stock_company_scopes=[c_machine])
    b.user(
        "referee", role="COMPETITION_ADMIN", display_name="本场裁判",
        company_scopes=[a_steel, b_steel, c_machine],
        view_company_scopes=[a_steel, b_steel, c_machine],
        contract_view_company_scopes=[a_steel, b_steel, c_machine],
        permissions=["contract:manage", "contract:audit", "contract:execute"],
    )

    # 资金账户：公司账户（下单资金来源）
    b.account("甲钢铁资金户", owner=a_steel, cash_balance="1000000")
    b.account("乙特钢资金户", owner=b_steel, cash_balance="1000000")
    b.account("丙机械资金户", owner=c_machine, cash_balance="1000000")
    # 资金账户：用户账户（用户名必须已 user() 登记）
    b.account("甲钢铁操盘手备用金", username=p_a.name, cash_balance="200000")

    # 比赛内消息
    b.message(
        "开局公告",
        "欢迎参加 2026 春季钢铁商赛。请先在「公司管理」核对本公司初始字段，"
        "再前往「合同管理」查看待签合同。第一财年将于开赛后正式开始。",
        to_all=True,
    )
    b.message("裁判提示", "任何金额填写请保留两位小数，避免浮点误差。", to_all=True)

    return b


# ==================== 关于总览卡片的字段 id 回填 ====================
# 卡片的 industryFieldId 是数据库主键，而产业字段是全局资源、跨比赛复用。
# 首次导入某个数据库时字段还不存在，因此第一次导入后卡片取不到值，属正常现象：
#
#   1) 先导入一次（会把产业类型与字段建出来）：
#        python manage.py build_competition examples/competitions/demo_competition.py --competition 7
#   2) 从目标库导出「行业口径」分组（GET /api/preparations/archive/export?scope=industry），
#      或直接读库里的 industry_fields 表，拿到真实字段 id；
#   3) 在脚本里回填：
#        b.resolve_field_ids(json.loads(Path("industry.json").read_text(encoding="utf-8")))
#   4) 再导入一次（覆盖模式即可刷新卡片）：
#        python manage.py build_competition examples/competitions/demo_competition.py \
#            --competition 7 --mode overwrite
