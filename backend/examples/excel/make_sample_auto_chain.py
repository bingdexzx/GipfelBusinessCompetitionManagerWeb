# -*- coding: utf-8 -*-
"""生成「汽车产业链测试赛」的表格建包文件（Excel 示例 + 可选 CSV 表集）。

它与代码建包脚本 [`examples/competitions/auto_chain_competition.py`](../competitions/auto_chain_competition.py)
描述的是**同一场比赛**：三大产业（原料开采 / 零部件加工 / 整车进销）、9 家公司、
汽车零部件与整车配方、地图与物流、以及开采 / 购销 / 运输三大合同。
用来对比「代码建包」与「表格建包」两种写法的等价性。

用法
----

    cd backend

    # 生成 Excel 示例（仓库里已带一份，改数据后重新生成即可）
    .\\.venv\\Scripts\\python.exe examples/excel/make_sample_auto_chain.py

    # 同时导出成 CSV 表集（便于进 git / diff / 手工改）
    .\\.venv\\Scripts\\python.exe examples/excel/make_sample_auto_chain.py --csv-out examples/excel/汽车产业链示例

    # 直接用它建一场新比赛
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py examples/excel/汽车产业链示例.xlsx --inspect
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheet_spec import SHEET_BY_NAME, header_for  # noqa: E402
from xlsx_io import save_tables, write_xlsx  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_XLSX = HERE / "汽车产业链示例.xlsx"

COMPETITION_NAME = "2026 汽车产业链测试赛"
#: 合同类型走「合同类型代码化」脚本：表格里只写脚本路径，复杂逻辑仍留在代码里
CONTRACT_SCRIPT = "examples/contracts/auto_chain_contracts.py"

INDUSTRIES = (
    (2001, "原料开采", "汽车产业链上游：锂 / 铝 / 铁矿石与橡胶硅砂开采"),
    (2002, "零部件加工", "汽车产业链中游：原材料加工合成动力电池、电机、车身等零部件"),
    (2003, "整车进销", "汽车产业链下游：零部件合成整车并进行批发、零售与出口"),
)

#: 三大产业共用的字段：(显示名, field_key, 类型, 默认值, 是否计算, 计算图, 类型配置)
COMMON_FIELDS = (
    ("所在地", "location", "STRING", "", "", "", ""),
    ("现金", "cash", "NUMBER", "0", "", "", ""),
    ("银行存款", "bank_deposit", "NUMBER", "0", "", "", ""),
    ("许可配额", "quota", "NUMBER", "0", "", "", ""),
    ("库存台账", "inventory", "DICTIONARY", "{}", "", "", "NUMBER"),
    ("业务台账", "ledger", "DICTIONARY", "{}", "", "", "NUMBER"),
    ("碳排放", "carbon", "NUMBER", "0", "", "", ""),
    ("累计合同额", "contract_amount", "NUMBER", "0", "", "", ""),
    ("累计运输里程", "transport_km", "NUMBER", "0", "", "", ""),
    ("最近业务摘要", "last_deal", "STRING", "", "", "", ""),
    ("货币资金", "total_cash", "NUMBER", "", "是", "cash + bank_deposit", ""),
)

#: 各产业特有字段：code → ((显示名, field_key, 类型, 默认值), ...)
EXTRA_FIELDS = {
    2001: (("累计开采量", "mined_total", "NUMBER", "0"), ("矿区数", "mine_count", "NUMBER", "0")),
    2002: (("累计零件产量", "parts_output", "NUMBER", "0"), ("年产能（件）", "capacity", "NUMBER", "0")),
    2003: (("整车交付量", "delivered_units", "NUMBER", "0"), ("销售收入", "sales_revenue", "NUMBER", "0")),
}

COMPANY_HEADER_EXTRA = ("所在地", "现金", "银行存款", "许可配额", "库存台账")

#: 公司：行业、区域、所在地节点、现金、银行存款、配额、初始库存
COMPANIES = (
    ("西岭锂业", "原料开采", "上游资源区", "白云鄂博矿区", "1200000", "300000", "800", {"原矿": 120, "锂矿石": 40}),
    ("戈壁铝业", "原料开采", "上游资源区", "戈壁铝土矿区", "900000", "200000", "600", {"原矿": 80, "铝土矿": 30}),
    ("白云矿业", "原料开采", "上游资源区", "白云鄂博矿区", "800000", "150000", "500", {"原矿": 60, "铁矿石": 25}),
    ("中原创能", "零部件加工", "中部智造区", "中部智造园", "1500000", "500000", "600", {"货物": 60, "锂矿石": 20}),
    ("智造电驱", "零部件加工", "中部智造区", "中部智造园", "1200000", "400000", "500", {"货物": 45}),
    ("轻量化车身厂", "零部件加工", "中部智造区", "中原铁路货场", "1000000", "300000", "400", {"货物": 30}),
    ("车都新能源", "整车进销", "东部车都", "东部车都港", "3000000", "1000000", "400", {"货物": 40, "零件": 20}),
    ("东都汽车销售", "整车进销", "东部车都", "车都展销中心", "2000000", "800000", "300", {"货物": 25}),
    ("车都出口贸易", "整车进销", "东部车都", "东部车都港", "1800000", "600000", "300", {"货物": 18}),
)

NODE_TYPES = (
    ("矿区", "原矿开采地", "#b45309"),
    ("产业园区", "加工制造基地", "#2563eb"),
    ("物流枢纽", "集运站 / 港口 / 铁路货场", "#0ea5e9"),
    ("销售中心", "整车展销与交付中心", "#7c3aed"),
)

PATH_TYPES = (
    ("公路", "通用公路运输", "#94a3b8"),
    ("铁路", "大宗干线运输", "#a16207"),
    ("内河航运", "港口水运", "#0369a1"),
)

MAP_NODES = (
    ("白云鄂博矿区", "矿区", "上游资源区", 140, 120),
    ("戈壁铝土矿区", "矿区", "上游资源区", 140, 300),
    ("橡胶硅砂基地", "矿区", "上游资源区", 140, 480),
    ("上游集运站", "物流枢纽", "上游资源区", 360, 300),
    ("中部智造园", "产业园区", "中部智造区", 620, 300),
    ("中原铁路货场", "物流枢纽", "中部智造区", 620, 470),
    ("东部车都港", "物流枢纽", "东部车都", 900, 220),
    ("车都展销中心", "销售中心", "东部车都", 1040, 380),
)

MAP_EDGES = (
    ("白云鄂博矿区", "上游集运站", 120, "公路"),
    ("戈壁铝土矿区", "上游集运站", 80, "公路"),
    ("橡胶硅砂基地", "上游集运站", 160, "公路"),
    ("上游集运站", "中部智造园", 420, "铁路"),
    ("中部智造园", "上游集运站", 430, "公路"),
    ("上游集运站", "东部车都港", 1200, "内河航运"),
    ("中部智造园", "中原铁路货场", 60, "公路"),
    ("中原铁路货场", "东部车都港", 400, "铁路"),
    ("中部智造园", "东部车都港", 380, "公路"),
    ("东部车都港", "中部智造园", 390, "铁路"),
    ("东部车都港", "车都展销中心", 60, "公路"),
)

FUELS = (("柴油", "7.6"), ("电力", "0.8"))

#: 原料：(名称, 产地, 碳排系数, 类型, 地点价)
MATERIALS = (
    ("锂矿石", "白云鄂博矿区", "0.52", "NORMAL", "白云鄂博矿区:180; 上游集运站:195; 中部智造园:215; 东部车都港:240"),
    ("铝土矿", "戈壁铝土矿区", "0.41", "NORMAL", "戈壁铝土矿区:165; 上游集运站:180; 中部智造园:205; 东部车都港:230"),
    ("铁矿石", "白云鄂博矿区", "0.48", "NORMAL", "白云鄂博矿区:120; 上游集运站:132; 中部智造园:150; 东部车都港:168"),
    ("天然橡胶", "橡胶硅砂基地", "0.33", "NORMAL", "橡胶硅砂基地:90; 上游集运站:98; 中部智造园:110; 东部车都港:126"),
    ("石英砂", "橡胶硅砂基地", "0.22", "NORMAL", "橡胶硅砂基地:60; 上游集运站:66; 中部智造园:75; 东部车都港:86"),
)

TECH = (
    ("电池成组技术", 1, "80000", "解锁动力电池包", ""),
    ("电驱系统集成", 1, "60000", "解锁驱动电机", ""),
    ("轻量化车身工艺", 1, "50000", "解锁铝合金车身", ""),
    ("整车平台化", 2, "200000", "解锁整车产品", "电池成组技术; 电驱系统集成"),
)

LINES = (
    ("电芯产线", "2400000", 120, "6000"),
    ("电驱总装线", "1600000", 80, "8000"),
    ("车身冲压线", "1200000", 60, "9000"),
    ("整车总装线", "3600000", 200, "4000"),
)

INFRASTRUCTURES = (
    ("智能充电站", 80, "600000", "30000", "", "", "", "0.01", "", "0.04"),
    ("汽车试验场", 200, "1500000", "80000", "", "", "", "0.03", "0.02", ""),
    ("光伏电站", 160, "1200000", "50000", "0.02", "", "", "", "", "0.12"),
)

WAREHOUSES = (
    ("原料仓", "MATERIAL", "30000", "400000"),
    ("零件仓", "PART", "20000", "300000"),
    ("整车成品仓", "PRODUCT", "8000", "600000"),
    ("燃料储罐", "FUEL", "10000", "200000"),
)

PARTS = (
    ("动力电池包", "锂矿石*4; 铝土矿*1", "电池成组技术"),
    ("驱动电机", "铁矿石*2; 铝土矿*2", "电驱系统集成"),
    ("铝合金车身", "铝土矿*4; 铁矿石*1", "轻量化车身工艺"),
    ("汽车轮胎", "天然橡胶*3; 铁矿石*1", ""),
    ("智能座舱域控", "石英砂*3; 铝土矿*1", "电驱系统集成"),
)

PRODUCTS = (
    ("纯电轿车", "动力电池包*1; 驱动电机*1; 铝合金车身*1; 汽车轮胎*4; 智能座舱域控*1", "整车平台化"),
    ("纯电SUV", "动力电池包*1; 驱动电机*2; 铝合金车身*1; 汽车轮胎*4; 智能座舱域控*1", "整车平台化"),
    ("商用电动轻卡", "动力电池包*2; 驱动电机*2; 铝合金车身*1; 汽车轮胎*6", "整车平台化"),
)

VEHICLES = (
    ("矿用自卸车", "柴油", "公路", "0.45", 60, "900000", "1.2"),
    ("重型卡车", "柴油", "公路", "0.35", 30, "260000", "0.9"),
    ("商品车运输车", "柴油", "公路", "0.42", 12, "480000", "1.0"),
    ("电动重卡", "电力", "公路", "1.2", 25, "620000", "0.2"),
    ("货运列车", "电力", "铁路", "0.05", 800, "3200000", "0.25"),
    ("内河滚装船", "柴油", "内河航运", "0.06", 1500, "5200000", "0.3"),
)

DEMANDS = (
    ("东部车都", "纯电轿车", 1200, "城市通勤主力车型"),
    ("东部车都", "纯电SUV", 600, "家庭用车"),
    ("中部智造区", "商用电动轻卡", 300, "园区物流用车"),
    ("上游资源区", "商用电动轻卡", 120, "矿区自用与通勤"),
)

CARDS = (
    ("上游资源区", "西岭锂业", "cash", "西岭锂业现金"),
    ("上游资源区", "西岭锂业", "inventory", "西岭锂业库存"),
    ("上游资源区", "戈壁铝业", "cash", "戈壁铝业现金"),
    ("中部智造区", "中原创能", "cash", "中原创能现金"),
    ("中部智造区", "中原创能", "inventory", "中原创能库存"),
    ("中部智造区", "智造电驱", "cash", "智造电驱现金"),
    ("东部车都", "车都新能源", "cash", "车都新能源现金"),
    ("东部车都", "车都新能源", "inventory", "车都新能源库存"),
    ("东部车都", "东都汽车销售", "cash", "东都汽车销售现金"),
)

CONTRACT_TYPES = (
    ("auto-mining", "开采合同", "开采企业向矿区管理方缴纳权利金与环保费，扣减许可配额并把原矿入库"),
    ("auto-purchase-sale", "购销合同", "按卖方所在地价结算货款，货物出库 / 入库并登记双方台账"),
    ("auto-transport", "运输合同", "按最短路径路程与载具计费，超重加价，里程与碳排计入台账"),
)

CONTRACT_INSTANCES = (
    ("auto-mining", "开采合同", "miner=西岭锂业|MIN-2026-001",
     "ore_type=锂矿石; quantity=20; royalty_rate=60; env_fee_rate=8; carbon_factor=0.5", "DRAFT"),
    ("auto-purchase-sale", "购销合同",
     "seller=西岭锂业|SL-2026-001; buyer=中原创能|BY-2026-001",
     'goods={"锂矿石": 20}; discount=0', "DRAFT"),
    ("auto-transport", "运输合同",
     "client=中原创能|PL-2026-001; carrier=车都新能源|TR-2026-001",
     'rate_per_km=12; trips=1; cargo_weight=20; carbon_tax_rate=0.05; vehicles={"重型卡车": 2}', "DRAFT"),
)

MESSAGES = (
    ("开局公告",
     "欢迎参加 2026 汽车产业链测试赛。本场共三大产业：上游「原料开采」、中游「零部件加工」、下游「整车进销」。"
     "请先在「公司管理」核对本公司初始字段，再到「合同管理」查看三份待签合同（开采 / 购销 / 运输）。"),
    ("产业链玩法说明",
     "① 开采企业用「开采合同」缴纳权利金与环保费取得原矿（扣减许可配额）；\\n"
     "② 用「运输合同」把原矿从矿区运到中部智造园（按最短路径计费，超重加价）；\\n"
     "③ 用「购销合同」把原料卖给加工企业，加工企业按零件配比生产零部件；\\n"
     "④ 再用「运输合同」把零部件运到东部车都，用「购销合同」卖给整车企业；\\n"
     "⑤ 整车企业按产品配比总装整车，交付东部车都的消费者需求。"),
    ("裁判提示", "合同执行金额请保留两位小数；提交前可用合同详情里的「试算」核对落账。"),
)

CHAIN_A = "西岭锂业; 中原创能; 车都新能源"
CHAIN_B = "戈壁铝业; 智造电驱; 东都汽车销售"
CHAIN_C = "白云矿业; 轻量化车身厂; 车都出口贸易"
ALL_COMPANIES = "西岭锂业; 戈壁铝业; 白云矿业; 中原创能; 智造电驱; 轻量化车身厂; 车都新能源; 东都汽车销售; 车都出口贸易"

USERS = (
    ("auto_player_a", "PLAYER", "玩家A（锂电链）", CHAIN_A, CHAIN_A, CHAIN_A, "", ""),
    ("auto_player_b", "PLAYER", "玩家B（铝驱链）", CHAIN_B, CHAIN_B, CHAIN_B, "", ""),
    ("auto_player_c", "PLAYER", "玩家C（铁矿车身链）", CHAIN_C, CHAIN_C, CHAIN_C, "", ""),
    ("auto_referee", "COMPETITION_ADMIN", "本场裁判", ALL_COMPANIES, ALL_COMPANIES, ALL_COMPANIES, "",
     "contract:manage; contract:audit; contract:execute"),
)


def _h(sheet: str) -> list[str]:
    """取某张表的表头（始终与规范一致：中文表头，改动规范后自动跟随）。"""
    return [header_for(sheet, col.key) for col in SHEET_BY_NAME[sheet].columns]


def sample_tables() -> dict[str, list[list]]:
    """把上面这份比赛内容渲染成「一表一资源」的表格集合（表头全中文）。"""
    return {
        "说明": [
            ["汽车产业链测试赛 · 表格建包示例"],
            ["与代码建包脚本 examples/competitions/auto_chain_competition.py 描述同一场比赛。"],
            ["股票系统不在本规范内：本示例不产出任何股票 / 资金账户 / 股票参数。"],
            ["用法：python examples/excel/build_from_sheets.py examples/excel/汽车产业链示例.xlsx --inspect"],
            ["导入：python examples/excel/build_from_sheets.py examples/excel/汽车产业链示例.xlsx --create-competition"],
        ],
        "比赛": [_h("比赛"), [COMPETITION_NAME, "ACTIVE"]],
        "财年": [_h("财年"), ["2026", "ACTIVE"]],
        "产业类型": [_h("产业类型")] + [[str(c), n, d] for c, n, d in INDUSTRIES],
        "产业字段": _industry_field_rows(),
        "区域": [_h("区域"),
                 ["上游资源区", "锂 / 铝 / 铁矿与橡胶硅砂资源带"],
                 ["中部智造区", "动力电池、电驱与轻量化车身产业带"],
                 ["东部车都", "整车制造、展销与出口集散地"]],
        "公司": [_h("公司") + list(COMPANY_HEADER_EXTRA)] + [
            [name, industry, region, "ACTIVE", node, cash, bank, quota,
             json.dumps(inventory, ensure_ascii=False)]
            for name, industry, region, node, cash, bank, quota, inventory in COMPANIES
        ],
        "公司字段值": [
            _h("公司字段值"),
            ["西岭锂业", "最近业务摘要", "开局初始化"],
            ["中原创能", "业务台账", '{"开局盘点": 1}'],
            ["车都新能源", "业务台账", '{"开局盘点": 1}'],
        ],
        "地图节点类型": [_h("地图节点类型")] + [list(x) for x in NODE_TYPES],
        "路径类型": [_h("路径类型")] + [list(x) for x in PATH_TYPES],
        "地图节点": [_h("地图节点")] + [list(x) for x in MAP_NODES],
        "地图连线": [_h("地图连线")] + [list(x) for x in MAP_EDGES],
        "燃料": [_h("燃料")] + [list(x) for x in FUELS],
        "原料": [_h("原料")] + [list(x) for x in MATERIALS],
        "科技": [_h("科技")] + [list(x) for x in TECH],
        "生产线": [_h("生产线")] + [list(x) for x in LINES],
        "基建": [_h("基建")] + [list(x) for x in INFRASTRUCTURES],
        "仓库": [_h("仓库")] + [list(x) for x in WAREHOUSES],
        "零件": [_h("零件")] + [list(x) for x in PARTS],
        "产品": [_h("产品")] + [list(x) for x in PRODUCTS],
        "载具": [_h("载具")] + [list(x) for x in VEHICLES],
        "消费者需求": [_h("消费者需求")] + [list(x) for x in DEMANDS],
        "区域总览卡片": [_h("区域总览卡片")] + [list(x) for x in CARDS],
        "合同类型": [_h("合同类型")] + [list(x) + [CONTRACT_SCRIPT] for x in CONTRACT_TYPES],
        "合同实例": [_h("合同实例")] + [list(x) for x in CONTRACT_INSTANCES],
        "消息": [_h("消息")] + [[t, c, "是"] for t, c in MESSAGES],
        "账号": [_h("账号")] + [list(x) for x in USERS],
    }


def _industry_field_rows() -> list[list]:
    rows: list[list] = [_h("产业字段")]
    for code, _name, _desc in INDUSTRIES:
        for index, (fname, key, ftype, default, calc, graph, config) in enumerate(COMMON_FIELDS, start=1):
            rows.append([str(code), fname, key, ftype, default, calc, graph, "", "", "",
                         str(index), "是", config])
        for offset, (fname, key, ftype, default) in enumerate(EXTRA_FIELDS[code],
                                                             start=len(COMMON_FIELDS) + 1):
            rows.append([str(code), fname, key, ftype, default, "", "", "", "", "",
                         str(offset), "是", ""])
    return rows


def minimal_tables() -> dict[str, list[list]]:
    """最小可用示例（教程用）：2 个产业、2 家公司、1 份能真正执行的购销合同。

    刻意只用最少的 9 张表 —— 复制这份就能改成自己的比赛。
    """
    fields = [
        _h("产业字段"),
        ["9001", "所在地", "location", "STRING", "", "", "", "", "", "", "1", "是", ""],
        ["9001", "现金", "cash", "NUMBER", "0", "", "", "", "", "", "2", "是", ""],
        ["9001", "库存", "inventory", "DICTIONARY", "{}", "", "", "", "", "", "3", "是", "NUMBER"],
        ["9002", "所在地", "location", "STRING", "", "", "", "", "", "", "1", "是", ""],
        ["9002", "现金", "cash", "NUMBER", "0", "", "", "", "", "", "2", "是", ""],
        ["9002", "库存", "inventory", "DICTIONARY", "{}", "", "", "", "", "", "3", "是", "NUMBER"],
    ]
    sale_effects = [
        {"kind": "FIELD", "party": "buyer", "fieldKey": "cash", "op": "SUB",
         "value": {"type": "INPUT", "key": "amount"}},
        {"kind": "FIELD", "party": "seller", "fieldKey": "cash", "op": "ADD",
         "value": {"type": "INPUT", "key": "amount"}},
    ]
    sale_conditions = [
        {"kind": "FIELD_COMPARE", "party": "buyer", "fieldKey": "cash", "op": "GTE",
         "value": {"type": "INPUT", "key": "amount"}, "errorMessage": "买方现金不足以支付货款"},
    ]
    return {
        "说明": [
            ["最小可用示例（教程用）"],
            ["2 个产业 / 2 家公司 / 1 份能真正执行的购销合同；只用了 9 张表。"],
            ["用法：python examples/excel/build_from_sheets.py examples/excel/最小示例.xlsx --create-competition"],
        ],
        "比赛": [_h("比赛"), ["微型测试赛（教程示例）", "ACTIVE"]],
        "财年": [_h("财年"), ["2026", "ACTIVE"]],
        "产业类型": [_h("产业类型"),
                     ["9001", "原料开采", "上游：矿石"],
                     ["9002", "零件加工", "中游：毛坯"]],
        "产业字段": fields,
        "区域": [_h("区域"), ["东区", "矿区"], ["西区", "厂区"]],
        "公司": [_h("公司") + ["所在地", "现金", "库存"],
                 ["甲矿场", "原料开采", "东区", "ACTIVE", "东矿", "500000", '{"矿石": 100}'],
                 ["乙工厂", "零件加工", "西区", "ACTIVE", "西厂", "500000", "{}"]],
        "地图节点类型": [_h("地图节点类型"), ["城市", "通用节点", "#3b82f6"]],
        "路径类型": [_h("路径类型"), ["公路", "通用公路", "#94a3b8"]],
        "地图节点": [_h("地图节点"), ["东矿", "城市", "东区", "100", "100"],
                     ["西厂", "城市", "西区", "400", "100"]],
        "地图连线": [_h("地图连线"), ["东矿", "西厂", "100", "公路"]],
        "燃料": [_h("燃料"), ["柴油", "7.5"]],
        "原料": [_h("原料"), ["矿石", "东矿", "0.5", "NORMAL", "东矿:120"]],
        "零件": [_h("零件"), ["毛坯", "矿石*2", ""]],
        "产品": [_h("产品"), ["成品", "毛坯*1", ""]],
        "载具": [_h("载具"), ["卡车", "柴油", "公路", "0.3", "30", "200000", "0.8"]],
        "合同类型": [
            _h("合同类型"),
            ["mini-sale", "简易购销合同", "买方付钱给卖方", "", "seller=卖方; buyer=买方",
             json.dumps([{"key": "amount", "label": "成交金额", "type": "NUMBER",
                          "required": True, "default": "1000"}], ensure_ascii=False),
             json.dumps(sale_effects, ensure_ascii=False),
             json.dumps(sale_conditions, ensure_ascii=False), "是"],
        ],
        "合同实例": [
            _h("合同实例"),
            ["mini-sale", "简易购销合同", "seller=甲矿场|S-001; buyer=乙工厂|B-001",
             "amount=1200", "DRAFT"],
        ],
        "账号": [_h("账号"),
                 ["demo_player", "PLAYER", "演示玩家", "甲矿场; 乙工厂", "甲矿场; 乙工厂",
                  "甲矿场; 乙工厂", "", "", "是"]],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="生成汽车产业链测试赛的表格建包文件")
    parser.add_argument("--out", default=str(DEFAULT_XLSX), help="写出的 xlsx 路径")
    parser.add_argument("--csv-out", default=None, help="同时写出一套 CSV 表集目录")
    parser.add_argument("--csv-only", action="store_true", help="只写 CSV 表集，不写 xlsx")
    parser.add_argument("--minimal", action="store_true",
                        help="改为生成「最小示例.xlsx」（教程用的 9 张表小样例）")
    args = parser.parse_args(argv)

    if args.minimal:
        tables = minimal_tables()
        out = Path(args.out) if args.out != str(DEFAULT_XLSX) else HERE / "最小示例.xlsx"
        write_xlsx(out, tables)
        print(f"已写出最小示例：{out}（{out.stat().st_size / 1024:.1f} KB，{len(tables)} 张表）")
        return 0

    tables = sample_tables()
    if args.csv_out:
        save_tables(Path(args.csv_out), tables)
        print(f"已写出 CSV 表集：{args.csv_out}（{len(tables)} 张表）")
    if not args.csv_only:
        out = Path(args.out)
        write_xlsx(out, tables)
        print(f"已写出 xlsx：{out}（{out.stat().st_size / 1024:.1f} KB，{len(tables)} 张表）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
