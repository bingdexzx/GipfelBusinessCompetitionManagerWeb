# -*- coding: utf-8 -*-
"""生成「比赛建包表格」模板 / 把 CSV 表集转成 xlsx。

用法
----

    cd backend

    # 1) 生成空白模板（每张表只有表头 + 一行示例 + 若干空行，另附「说明」表）
    .\\.venv\\Scripts\\python.exe examples/excel/make_template.py --out examples/excel/比赛建包模板.xlsx

    # 2) 把一套 CSV（一个目录，一张表一个 csv）打包成一个 xlsx
    .\\.venv\\Scripts\\python.exe examples/excel/make_template.py --from-sheets 我的表目录 --out 我的比赛.xlsx

    # 3) 反过来：把 xlsx 拆成 CSV 目录（方便进 git、方便 diff）
    .\\.venv\\Scripts\\python.exe examples/excel/make_template.py --from-sheets 我的比赛.xlsx --csv-out 我的表目录

    # 4) 打印规范（Markdown，可贴进文档）
    .\\.venv\\Scripts\\python.exe examples/excel/make_template.py --spec
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheet_spec import KIND_LABELS, SHEETS, example_rows, header_for, summarize_spec  # noqa: E402
from xlsx_io import load_tables, save_tables, write_xlsx  # noqa: E402

#: 空白模板里每张表预留的空行数
BLANK_ROWS = 3

#: 这些表在模板里**不给示例行**，改为一行注释提示（避免照抄示例就把系统默认改掉）
COMMENT_ONLY_SHEETS = {
    "股票参数": "# 留空 = 沿用系统默认；要改就按「参数 / 值」逐行填，参数名见规范（limitPct、maxMovePct、mmMinQty…）",
}


def template_tables() -> dict[str, list[list]]:
    """空白模板：说明表 + 每张规范表的**中文表头** / 示例行 / 空行。"""
    tables: dict[str, list[list]] = {}
    tables["说明"] = _notes_rows()
    for spec in SHEETS:
        header = [header_for(spec.name, col.key) for col in spec.columns]
        rows: list[list] = [header]
        if spec.name in COMMENT_ONLY_SHEETS:
            rows.append([COMMENT_ONLY_SHEETS[spec.name]] + [""] * (len(header) - 1))
        else:
            rows.extend(list(row) for row in example_rows(spec))
        rows.extend([[""] * len(header) for _ in range(BLANK_ROWS)])
        tables[spec.name] = rows
    return tables


def _notes_rows() -> list[list]:
    rows: list[list] = [
        ["比赛建包表格 · 使用说明（本表只建「比赛框架」）"],
        [""],
        ["怎么用"],
        ["1. 一张表 = 一类内容；只填你要建的表，没填的表完全不参与产出（表与表相互隔离）。"],
        ["2. 第一行是中文表头，不要改；需要对照代码时看「表头 ↔ 参数名对照」那一节。列顺序随意。"],
        ["3. 以 # 开头的行是注释行；整行空白会被忽略。"],
        ["4. 单元格语法：是/否 表示布尔；分号分隔表示列表；`名称:数量` 或 `名称*数量` 表示键值；以 { 或 [ 开头的单元格按 JSON 解析。"],
        ["5. 建包命令：python examples/excel/build_from_sheets.py 本文件.xlsx --create-competition [--dry-run]"],
        ["6. 英文参数名同样可用（老文件兼容）；中文表头与参数名指向同一列，不要同时写两列。"],
        [""],
        ["只建框架，不建运行数据"],
        ["本表格覆盖：比赛、财年、股票参数（市场规则）、行业口径（产业类型 / 产业字段）、区域、"
         "地图与路径、物资与产能（燃料 / 原料 / 科技 / 生产线 / 基建 / 仓库 / 零件 / 产品 / 载具）、"
         "消费者需求、合同类型（由代码脚本产出）。"],
        ["以下内容绑定具体公司与人，请在界面维护（或用代码建包脚本），不要放进表格："],
        ["  · 公司、公司字段初始值 → 公司管理"],
        ["  · 账号与权限 → 账号管理"],
        ["  · 区域总览卡片 → 区域总览"],
        ["  · 比赛内的预置合同（合同实例） → 合同管理"],
        ["  · 比赛内消息 → 消息中心"],
        ["  · 个股、资金账户 → 股票管理（PE 联动公司/字段、资金账户绑定字段都是主键引用）"],
        ["  · 持仓 / 委托 / K 线 → 撮合与「推进轮次」在运行时生成，无法预置"],
        ["工作簿里若出现这些表名，程序会提示「该去哪里维护」，不会静默忽略。"],
        [""],
        ["表清单"],
        ["表名", "分组", "用途", "列（* = 必填）"],
    ]
    for spec in SHEETS:
        cols = "、".join(
            (header_for(spec.name, col.key) + "*") if col.required else header_for(spec.name, col.key)
            for col in spec.columns
        )
        rows.append([spec.name, spec.scope, spec.purpose, cols])
    rows.append([""])
    rows.append(["表头 ↔ 参数名对照"])
    rows.append(["表名", "中文表头", "参数名", "类型", "必填"])
    for spec in SHEETS:
        for col in spec.columns:
            rows.append([spec.name, header_for(spec.name, col.key), col.key,
                         KIND_LABELS.get(col.kind, col.kind), "是" if col.required else ""])
    return rows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="生成比赛建包表格模板 / 转换表格格式")
    parser.add_argument("--out", default=None, help="写出的 xlsx 路径")
    parser.add_argument("--from-sheets", default=None,
                        help="来源：CSV 目录（打包成 xlsx）或 xlsx（拆成 CSV，需 --csv-out）")
    parser.add_argument("--csv-out", default=None, help="同时写出一套 CSV 目录")
    parser.add_argument("--spec", action="store_true", help="打印规范（Markdown）后退出")
    args = parser.parse_args(argv)

    if args.spec:
        print(summarize_spec())
        return 0

    if args.from_sheets:
        source = Path(args.from_sheets)
        if not source.exists():
            print(f"✗ 来源不存在：{source}", file=sys.stderr)
            return 2
        tables = load_tables(source)
        print(f"读取 {source}：{len(tables)} 张表")
    else:
        tables = template_tables()
        print(f"生成空白模板：{len(tables)} 张表")

    if args.csv_out:
        save_tables(Path(args.csv_out), tables)
        print(f"已写出 CSV 目录：{args.csv_out}")

    if args.out:
        out = Path(args.out)
        write_xlsx(out, tables)
        print(f"已写出 xlsx：{out}（{out.stat().st_size / 1024:.1f} KB）")
    elif not args.csv_out:
        # 没有 --out 也没有 --csv-out 时给个默认动作，避免「什么都没发生」
        default = Path(__file__).resolve().parent / "比赛建包模板.xlsx"
        write_xlsx(default, tables)
        print(f"已写出 xlsx：{default}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
