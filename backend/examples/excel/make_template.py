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

from sheet_spec import KIND_LABELS, SHEETS, summarize_spec  # noqa: E402
from xlsx_io import load_tables, save_tables, write_xlsx  # noqa: E402

#: 空白模板里每张表预留的空行数
BLANK_ROWS = 3

#: 「公司」表额外列示例（列名即 field_key，值是该公司的字段初始值）
COMPANY_EXTRA_COLUMNS = ("location", "cash", "bank_deposit", "quota", "inventory")


def template_tables() -> dict[str, list[list]]:
    """空白模板：说明表 + 每张规范表的表头 / 示例行 / 空行。"""
    tables: dict[str, list[list]] = {}
    tables["说明"] = _notes_rows()
    for spec in SHEETS:
        header = [col.key for col in spec.columns]
        if spec.allow_extra_columns:
            header += list(COMPANY_EXTRA_COLUMNS)
        rows: list[list] = [header]
        if spec.example:
            rows.append(list(spec.example))
        rows.extend([[""] * len(header) for _ in range(BLANK_ROWS)])
        tables[spec.name] = rows
    return tables


def _notes_rows() -> list[list]:
    rows: list[list] = [
        ["比赛建包表格规范 · 使用说明"],
        [""],
        ["怎么用"],
        ["1. 一张表 = 一类内容；只填你要建的表，没填的表完全不参与产出（表与表相互隔离）。"],
        ["2. 第一行是表头，列名不要改（就是建包库的参数名）；列顺序随意，多余列会被拒绝（公司表除外）。"],
        ["3. 以 # 开头的行是注释行；整行空白会被忽略。"],
        ["4. 单元格语法：是/否 表示布尔；分号分隔表示列表；`名称:数量` 或 `名称*数量` 表示键值；以 { 或 [ 开头的单元格按 JSON 解析。"],
        ["5. 建包命令：python examples/excel/build_from_sheets.py 本文件.xlsx --competition <比赛id> [--dry-run]"],
        ["6. 股票系统不在本规范内（没有股票 / 资金账户 / 股票参数三类表）。"],
        [""],
        ["表清单"],
        ["表名", "分组", "用途", "列（* = 必填）"],
    ]
    for spec in SHEETS:
        cols = "、".join(
            f"{col.key}*" if col.required else col.key for col in spec.columns
        )
        if spec.allow_extra_columns:
            cols += "、（额外列：列名 = field_key，填公司的产业字段初始值）"
        rows.append([spec.name, spec.scope, spec.purpose, cols])
    rows.append([""])
    rows.append(["列类型说明"])
    for kind, label in KIND_LABELS.items():
        rows.append([kind, label])
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
