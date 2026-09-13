# -*- coding: utf-8 -*-
"""生成「汽车产业链」比赛的**框架**表格（Excel 示例 + 可选 CSV 表集）。

框架 = 换一场比赛仍然成立的部分：三大产业（原料开采 / 零部件加工 / 整车进销）、
行业字段口径、地图与物流网络、物资与产能（原料 / 零件 / 产品 / 科技 / 载具…）、
消费者需求、以及开采 / 购销 / 运输三大合同类型。

**参赛主体与运行期内容不在表格里**：公司、公司字段值、账号、区域总览卡片、
比赛内的合同实例、消息 —— 这些绑定具体公司与人，请在界面维护，
或用代码建包脚本 `examples/competitions/auto_chain_competition.py`（它会把框架 + 主体一次建齐）。
两者描述的是同一场比赛，可以混用：先用本表格建框架，再用脚本或界面补主体。

用法
----

    cd backend

    # 生成 Excel 示例（仓库里已带一份，改数据后重新生成即可）
    .\\.venv\\Scripts\\python.exe examples/excel/make_sample_auto_chain.py

    # 同时导出成 CSV 表集（便于进 git / diff / 手工改）
    .\\.venv\\Scripts\\python.exe examples/excel/make_sample_auto_chain.py --csv-out examples/excel/汽车产业链示例

    # 只看会建出什么
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py examples/excel/汽车产业链示例.xlsx --inspect
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheet_spec import SHEET_BY_NAME, header_for  # noqa: E402
from xlsx_io import save_tables, write_xlsx  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_XLSX = HERE / "汽车产业链示例.xlsx"

COMPETITION_NAME = "2026 汽车产业链测试赛"
CONTRACT_SCRIPT = "examples/contracts/auto_chain_contracts.py"
MINI_CONTRACT_SCRIPT = "examples/contracts/mini_contracts.py"

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

#: 合同类型**只由代码脚本创建**（合同类型代码化建库）：
#: 表格里只写「脚本路径 + 类型标识」，四份 JSON 全部由 `apps.contracts.builder.ContractType` 产出。
#: 比赛内的合同实例、区域总览卡片、消息、公司、账号属于运行期内容，**不进表格**。
CONTRACT_TYPE_REFS = (
    (CONTRACT_SCRIPT, "auto-mining"),
    (CONTRACT_SCRIPT, "auto-purchase-sale"),
    (CONTRACT_SCRIPT, "auto-transport"),
)


def _h(sheet: str) -> list[str]:
    """取某张表的表头（始终与规范一致：中文表头，改动规范后自动跟随）。"""
    return [header_for(sheet, col.key) for col in SHEET_BY_NAME[sheet].columns]


def sample_tables() -> dict[str, list[list]]:
    """把上面这份比赛**框架**渲染成「一表一类内容」的表格集合（表头全中文）。"""
    return {
        "说明": [
            ["汽车产业链 · 比赛框架表格示例"],
            [""],
            ["本表格只描述「比赛框架」：产业口径、地图与物流、物资与产能、需求、合同类型。"],
            ["参赛主体与运行期内容不在表格里（公司、公司字段值、账号、区域总览卡片、合同实例、消息）："],
            ["  · 界面维护：公司管理 / 账号管理 / 区域总览 / 合同管理 / 消息中心；"],
            ["  · 或一次建齐（框架 + 主体）：python manage.py build_competition "
             "examples/competitions/auto_chain_competition.py --competition <比赛id>"],
            ["股票系统同样不在本规范内：本示例不产出任何股票 / 资金账户 / 股票参数。"],
            [""],
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
        "合同类型": [_h("合同类型")] + [[script, key, "是"] for script, key in CONTRACT_TYPE_REFS],
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
    """最小框架示例（教程用）：2 个产业、一条矿区→工厂的物流线、1 份购销合同模板。

    刻意只用最少的表 —— 复制这份就能改成自己的比赛框架。
    合同类型只写脚本路径（由 `examples/contracts/mini_contracts.py` 产出四份 JSON）；
    公司 / 账号 / 预置合同不在表格里（它们属于运行期内容）。
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
    return {
        "说明": [
            ["最小框架示例（教程用）"],
            [""],
            ["2 个产业 + 一条「东矿 → 西厂」物流线 + 一份购销合同模板；只用了 14 张表。"],
            ["合同类型只写脚本路径（examples/contracts/mini_contracts.py），四份 JSON 由代码产出。"],
            ["公司 / 账号 / 预置合同属于运行期内容，不在表格里："],
            ["  · 建完框架后到「公司管理」建公司、到「账号管理」建账号、到「合同管理」建合同；"],
            ["  · 想一次建齐可参考 examples/competitions/auto_chain_competition.py（代码建包）。"],
            [""],
            ["用法：python examples/excel/build_from_sheets.py examples/excel/最小示例.xlsx --create-competition"],
        ],
        "比赛": [_h("比赛"), ["微型测试赛（教程示例）", "ACTIVE"]],
        "财年": [_h("财年"), ["2026", "ACTIVE"]],
        "产业类型": [_h("产业类型"),
                     ["9001", "原料开采", "上游：矿石"],
                     ["9002", "零件加工", "中游：毛坯"]],
        "产业字段": fields,
        "区域": [_h("区域"), ["东区", "矿区"], ["西区", "厂区"]],
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
        "消费者需求": [_h("消费者需求"), ["西区", "成品", "500", "厂区需求"]],
        "合同类型": [
            _h("合同类型"),
            [MINI_CONTRACT_SCRIPT, "mini-sale", "是"],
        ],
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
