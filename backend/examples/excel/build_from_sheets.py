# -*- coding: utf-8 -*-
"""用**表格文件**（Excel / CSV 目录）建一场比赛的**框架**：读表 → 建包 → 导入。

一张工作表 = 一类内容，表与表之间相互隔离：只填你要建的那几张表即可，
没出现的表完全不参与产出。规范见 [`sheet_spec.py`](sheet_spec.py) 与
[`docs/比赛Excel建包规范.md`](../../../docs/比赛Excel建包规范.md)。

**只建框架，不建运行数据**：参赛主体（公司 / 公司字段值）、账号、区域总览卡片、
比赛内的合同实例、消息都不在表格规范内 —— 它们绑定具体公司、具体人和具体主键，
请在前端界面维护，或用代码建包脚本 `examples/competitions/auto_chain_competition.py`。
工作簿里若出现这些表名，程序会提示「该去哪里维护」。

本脚本**没有新的落库路径**：它把表格翻译成 `CompetitionBuilder` 的调用，
产出与代码建包/前端导入完全同构的归档 JSON，再交给既有的
`apps.preparation.archive.apply_import` 落库。

用法
----

    cd backend

    # 0) 看看规范里有哪些表、每张表有哪些列
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py --spec

    # 1) 生成一份空白模板（含表头、示例行、说明表）
    .\\.venv\\Scripts\\python.exe examples/excel/make_template.py --out 比赛建包模板.xlsx

    # 2) 只读表格、打印会建出什么（不连库、不写任何东西）
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --inspect

    # 3) 写出归档 JSON（可以拿去前端「导入归档」上传）
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --out 我的比赛.json

    # 4) 建比赛 + 导入（预演 → 真导）
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --create-competition --dry-run
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --create-competition

    # 5) 导入到已存在的比赛；或只导某个分组 / 只处理指定几张表
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 189 --scope supply
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 189 --sheets 产业类型,产业字段

退出码：0 成功；1 表格格式错误或导入出现 problem；2 用法错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# 允许直接 `python examples/excel/build_from_sheets.py`（不用先装包）
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django  # noqa: E402

django.setup()

from apps.preparation.builder import BuilderError, CompetitionBuilder, RESOURCE_ORDER  # noqa: E402

from sheet_spec import (  # noqa: E402
    NOTES_SHEET_NAMES,
    OUT_OF_SCOPE_SHEETS,
    SHEET_BY_NAME,
    SHEETS,
    SheetContext,
    SheetFormatError,
    header_aliases,
    header_for,
    summarize_spec,
)
from xlsx_io import inspect_workbook, load_tables  # noqa: E402


class SheetBuildError(Exception):
    """整表读取/建包过程中的可读错误（带工作表与行号）。"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="用表格文件（Excel / CSV 目录）建比赛")
    parser.add_argument("source", nargs="?", help="表格文件（.xlsx）或存放 CSV 的目录")
    parser.add_argument("--inspect", action="store_true", help="只打印产出摘要，不导入")
    parser.add_argument("--out", default=None, help="把产出的归档 JSON 写到该路径")
    parser.add_argument("--force", action="store_true",
                        help="允许 --out 覆盖已存在的归档（默认拒绝，避免残缺包替换完整归档）")
    parser.add_argument("--run-scripts", action="store_true",
                        help="允许执行「合同类型」表里写的 Python 脚本（纯 --inspect 预览默认不执行）")
    parser.add_argument("--competition", type=int, default=None, help="导入到该比赛 id")
    parser.add_argument("--dry-run", action="store_true", help="预演导入（事务回滚，不落库）")
    parser.add_argument("--mode", choices=["append", "overwrite"], default="append")
    parser.add_argument("--allow-non-empty", action="store_true", help="允许导入到已有数据的比赛")
    parser.add_argument("--scope", default=None, help="只导入某个分组：competition/industry/geo/supply/tech/market")
    parser.add_argument("--sheets", default=None, help="只处理这些表（逗号分隔，如 产业类型,产业字段）")
    parser.add_argument("--name", default=None, help="比赛名（覆盖「比赛」表里的名称；表里没有「比赛」表时是兜底名）")
    parser.add_argument("--create-competition", action="store_true",
                        help="按「比赛」表的名称新建一场比赛（同名已存在则复用），再导入")
    parser.add_argument("--spec", action="store_true", help="打印表格规范（Markdown）后退出")
    parser.add_argument("--list-sheets", action="store_true", help="列出规范里的表清单后退出")
    args = parser.parse_args(argv)

    if args.spec:
        print(summarize_spec())
        return 0
    if args.list_sheets:
        for spec in SHEETS:
            print(f"{spec.name:<12} 分组 {spec.scope:<12} {spec.purpose}")
        return 0
    if not args.source:
        parser.error("请给出表格文件（.xlsx）或存放 CSV 的目录；用 --spec 查看规范")

    out_written: Path | None = None
    # 审计 Z-08：纯预览（--inspect 且不产出/不导入）默认**不执行**工作簿里指定的脚本；
    # 需要真产出或真导入时才执行（也可显式加 --run-scripts）。
    run_scripts = bool(
        args.run_scripts
        or args.out is not None
        or args.competition is not None
        or not args.inspect
    )
    try:
        builder, stats, notes = build_from_tables(
            Path(args.source), only_sheets=args.sheets, fallback_name=args.name,
            name_override=args.name, run_scripts=run_scripts,
        )
        if args.competition is not None:
            _try_resolve_card_fields(builder, args.competition, notes)
        archive = builder.build()

        competition_id = args.competition
        if args.create_competition and competition_id is None:
            competition_id, reused = _create_competition(
                archive["sourceCompetition"]["name"],
                archive["resources"].get("competitionMeta", {}),
                dry_run=bool(args.dry_run),
            )
            args.competition = competition_id
            # 审计 Z-06：复用已有比赛时它大概率已有数据，占用保护会拒绝导入（退出码 2），
            # 与文档「同名比赛会复用、一条命令可反复执行」相矛盾。append 模式是纯增量、
            # 不会改动既有数据，故自动放行；overwrite 是破坏性模式，仍要求显式 --allow-non-empty。
            if reused and not args.allow_non_empty:
                if args.mode == "append":
                    args.allow_non_empty = True
                    print(
                        "提示：复用的是已有比赛，append 模式只补缺、不改动既有数据，"
                        "已自动允许在非空比赛上继续导入"
                        "（如需覆盖既有数据请显式使用 --mode overwrite --allow-non-empty）"
                    )
                else:
                    print(
                        "提示：复用的是已有比赛且当前为 overwrite（覆盖）模式。"
                        "若确认要覆盖既有数据，请追加 --allow-non-empty；本次将按占用保护拒绝导入。",
                        file=sys.stderr,
                    )

        if args.out:
            out_path = Path(args.out)
            # 审计 Z-07：改前无条件覆盖 —— 对同一路径跑两遍、或 `--sheets 产业类型,产业字段
            # --out 框架.json` 这种子集导出，会把上一次的完整归档替换成残缺包，而用户手里
            # 没有任何旧副本（归档是拿去前端「导入归档」的交付物）。
            if out_path.exists() and not args.force:
                print(
                    f"✗ 归档已存在：{out_path}\n"
                    f"  为避免「子集导出/重复导出」把完整归档覆盖成残缺包，默认拒绝覆盖。\n"
                    f"  如确认要覆盖请加 --force；或改写到新文件（例如 "
                    f"{out_path.with_name(out_path.stem + '.' + time.strftime('%Y%m%d_%H%M%S') + out_path.suffix)}）。",
                    file=sys.stderr,
                )
                return 2
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(archive, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            out_written = out_path
            resource_rows = [
                (name, len((block or {}).get("rows") or []))
                for name, block in (archive.get("resources") or {}).items()
            ]
            total_rows = sum(n for _n, n in resource_rows)
            print(f"本次归档含 {len(resource_rows)} 类资源、{total_rows} 条记录："
                  + "、".join(f"{n}×{c}" for n, c in sorted(resource_rows)))
            if args.sheets:
                print(
                    "注意：本次使用了 --sheets 过滤，归档里**只有这些表**的资源；"
                    "不要用它替换完整归档（重复导入同一比赛请用同一份完整归档）。",
                    file=sys.stderr,
                )
    except (zipfile.BadZipFile, OSError) as exc:
        # 审计 Z-05：损坏文件 / 被 Excel 占用 / 无权限 / --out 写盘失败 / 建比赛失败
        # 原本直接抛 Python 堆栈，与规范承诺的「中文可读提示」不符
        print(
            f"✗ 读取或写出文件失败：{type(exc).__name__}: {exc}\n"
            f"  请确认：① 文件是 .xlsx/.xlsm（Excel 2003 的 .xls 请先用 Excel「另存为」.xlsx）；"
            f"② 该文件当前没有被 Excel 打开占用；③ 当前用户对源文件与 --out 目标目录有读写权限。",
            file=sys.stderr,
        )
        return 1
    except (SheetFormatError, SheetBuildError, BuilderError, ValueError) as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"表格来源：{args.source}")
    print(f"比赛名：{archive['sourceCompetition']['name']}")

    print("已处理的工作表：")
    for name, count in stats.items():
        print(f"  - {name:<12} {count:>4} 行")
    if notes:
        print("--- 提示 ---")
        for text in notes:
            print(f"  · {text}")

    warnings = builder.validate()
    if warnings:
        print(f"--- 体检提醒（{len(warnings)} 条）---")
        for text in warnings:
            print(f"  · {text}")

    if out_written is not None:
        print(f"已写出归档：{out_written}")

    if args.inspect or (not args.out and args.competition is None):
        _print_summary(archive, empty_sheets=_empty_sheet_names(stats))
        return 0

    if args.competition is not None and args.competition < 0:
        # Z-09：dry-run 且比赛尚不存在 —— 没有可导入的目标（也不该为了预演去建库），
        # 只做建包预览
        print("预演：比赛尚不存在（dry-run 不落库），本次只做建包预览")
        _print_summary(archive, empty_sheets=_empty_sheet_names(stats))
        return 0

    if args.competition is not None:
        return _import(archive, args.competition, args)
    return 0


# =============================================================================
# 表格 → 构建器
# =============================================================================


def build_from_tables(
    source: Path,
    *,
    only_sheets: str | None = None,
    fallback_name: str | None = None,
    name_override: str | None = None,
    run_scripts: bool = True,
) -> tuple[CompetitionBuilder, dict[str, int], list[str]]:
    """读取表格并逐表交给建包库，返回 (构建器, 每表行数, 提示)。

    注意：**表格里出现的表都会被处理**（`only_sheets` 除外）。引用解析依赖它们
    （例如「公司」表引用「产业类型」，「零件」表引用「原料」），所以不要按分组去裁表；
    `--scope` 只用来限制**导入范围**。

    `run_scripts=False`（`--inspect` 纯预览）时不执行「合同类型」表里写的 Python 脚本
    （审计 Z-08：工作簿是可转发文件，一格路径就能让打开者的机器执行任意本地脚本）。
    """
    if not source.exists():
        raise SheetBuildError(f"表格来源不存在：{source}")
    tables = load_tables(source)
    selected = {s.strip() for s in only_sheets.split(",") if s.strip()} if only_sheets else None

    notes: list[str] = []
    meta = _competition_meta(tables, fallback_name or source.stem, override_name=name_override)
    builder = CompetitionBuilder(meta["name"], status=meta["status"], map_background=meta["map_background"])

    ctx = SheetContext(
        builder=builder,
        base_dir=source.parent if source.is_file() else source,
        run_scripts=run_scripts,
    )
    stats: dict[str, int] = {}
    empty_sheets: list[str] = []   # 审计 Z-12 余项：表头在、数据为空的工作表
    problems: list[str] = []      # 审计 Z-13：收集全部行级错误后一次性报出

    # 审计 Z-12 余项：隐藏工作表/隐藏行里的数据**照常会被建进比赛**（不改读取行为，
    # 否则会静默丢数据），但必须让用户知道"界面上看不到的东西已经进库了"。
    try:
        wb_info = inspect_workbook(source)
    except Exception:  # noqa: BLE001 - 体检失败不影响建包
        wb_info = {"hidden_sheets": [], "sheets_with_hidden_rows": []}
    if wb_info["hidden_sheets"]:
        notes.append(
            "以下工作表在工作簿里被**隐藏**，但其内容仍会被读取并建进比赛："
            + "、".join(wb_info["hidden_sheets"])
        )
    if wb_info["sheets_with_hidden_rows"]:
        notes.append(
            "以下工作表里有**被隐藏的行**，这些行也会被读取（请确认不是草稿/废弃数据）："
            + "、".join(wb_info["sheets_with_hidden_rows"])
        )

    for name in tables:
        if name in NOTES_SHEET_NAMES:
            continue
        if name in OUT_OF_SCOPE_SHEETS:
            notes.append(f"工作表「{name}」不属于表格规范的「比赛框架」，已跳过：{OUT_OF_SCOPE_SHEETS[name]}")
        elif name not in SHEET_BY_NAME:
            notes.append(f"工作表「{name}」不在规范内，已忽略"
                         f"（可选：{'、'.join(s.name for s in SHEETS)}）")

    for spec in SHEETS:
        if spec.handler is None:      # 「比赛」表已在构造构建器时消费
            continue
        if selected is not None and spec.name not in selected:
            continue
        if spec.name not in tables:
            continue
        rows = _table_rows(spec, tables[spec.name])
        if not rows:
            # 审计 Z-12 余项：表格里放了一张「稍后再填」的空表（只有表头）时，改前它既不出现在
            # 归档里、也没有任何提示 —— 用户以为"空段"已经建好，导入后却发现比赛根本没有该段。
            # 这里明确提示：本次不会产出该资源的任何行。
            empty_sheets.append(spec.name)
        for row_no, row in rows:
            ctx.row_no = row_no
            try:
                spec.handler(ctx, row)
            except SheetFormatError as exc:
                # 审计 Z-13：改前遇到第一个错误就 raise —— 用户改一处跑一次，十几行的表要来回
                # 十几轮。现在把每一处错误都收集起来（最多 20 条），最后一次性报全，仍不产出归档。
                problems.append(f"[{spec.name}] 第 {row_no} 行：{exc}")
            except BuilderError as exc:
                problems.append(
                    f"[{spec.name}] 第 {row_no} 行：{exc}"
                    f"{_reference_hint(str(exc), tables, selected)}"
                )
        stats[spec.name] = len(rows)

    if problems:
        head = problems[:20]
        more = f"\n…另有 {len(problems) - len(head)} 条同类错误未列出" if len(problems) > len(head) else ""
        raise SheetBuildError(
            f"表格里有 {len(problems)} 处错误，已全部列出（请一次改完再跑）：\n  - "
            + "\n  - ".join(head)
            + more
        )

    notes.extend(ctx.notes)
    if empty_sheets:
        # 审计 Z-12 余项：空表（只有表头）不会产出任何行 —— 归档里**没有该资源段**，
        # 与"段存在但 0 行"在导入侧的语义不同（缺段会被忽略）。必须显式提示。
        notes.append(
            "以下工作表只有表头、没有任何数据行，本次**不会**产出对应资源"
            "（归档里没有该段，导入后比赛也没有该部分）："
            + "、".join(sorted(empty_sheets))
        )
    notes.append(f"共处理 {len(stats)} 张表、{sum(stats.values())} 行数据"
                 "（只处理出现在表格里的表，其余表完全不参与产出）")
    return builder, stats, notes


def _create_competition(name: str, meta_block: dict, *, dry_run: bool = False) -> tuple[int, bool]:
    """按表格里的比赛名新建（或复用同名）比赛，返回 `(比赛 id, 是否复用了已有比赛)`。

    只做一件事：写入 `Competition` 这一行（比赛名全局唯一，同名直接复用），
    其余内容仍由既有导入引擎落库。

    审计 Z-09：`--dry-run` 时**不落库**（改前先 create 再 apply_import，而 create 在这次
    事务之外 → 预演也会真实建出一场空比赛，与规范「一行都不落库」的承诺相反）。
    审计 Z-06：是否复用要回传给调用方 —— 复用已有（很可能非空）比赛时需要据此放宽占用保护，
    否则文档承诺的「同名比赛会复用、一条命令可反复执行」在第二遍就以退出码 2 失败。
    """
    from apps.competitions.models import Competition

    status = "ACTIVE"
    rows = meta_block.get("rows") or []
    if rows and isinstance(rows[0], dict):
        status = str(rows[0].get("status") or status).upper()
    competition = Competition.objects.filter(name=name).first()
    if competition is not None:
        print(f"复用已有比赛：#{competition.id}「{competition.name}」（状态 {competition.status}）")
        return competition.id, True
    if dry_run:
        print(f"预演：将新建比赛「{name}」（状态 {status}）—— dry-run 不落库")
        return -1, False
    competition = Competition.objects.create(name=name, status=status)
    print(f"已新建比赛：#{competition.id}「{competition.name}」（状态 {competition.status}）")
    return competition.id, False


def _reference_hint(message: str, tables: dict, selected: set[str] | None) -> str:
    """引用缺失时补一句可执行的提示（表格隔离最容易踩的坑）。"""
    if "产业类型" not in message:
        return ""
    missing_sheet = "产业类型" not in tables
    skipped = selected is not None and "产业类型" in tables and "产业类型" not in selected
    if missing_sheet:
        return "；本工作簿里没有「产业类型」表——请把它一并放进来（它是全局口径，很小）"
    if skipped:
        return "；本工作簿里有「产业类型」表，但被 --sheets 过滤掉了，请把它包含进来"
    return ""


def _competition_meta(tables: dict[str, list[list[str]]], fallback_name: str,
                      override_name: str | None = None) -> dict:
    """从「比赛」表读比赛基础信息；没有该表时用兜底名（便于按分组拆多份表格）。

    显式传入的 `--name` 优先于表格里的名称。
    """
    name = fallback_name
    status = "ACTIVE"
    background = None
    rows = tables.get("比赛") or []
    data = _table_rows(SHEET_BY_NAME["比赛"], rows)
    for _row_no, row in data[:1]:
        name = override_name or row.get("name") or name
        status = (row.get("status") or status).upper()
        url = (row.get("map_background_url") or "").strip()
        if url:
            background = {"url": url, "filename": url.rsplit("/", 1)[-1],
                          "width": float(row["map_background_width"]) if row.get("map_background_width") else 0,
                          "height": float(row["map_background_height"]) if row.get("map_background_height") else 0}
    if override_name and not data:
        name = override_name
    return {"name": name, "status": status, "map_background": background}


# Excel 公式错误值（审计 Z-12）：这些不是用户想写进比赛的内容，必须显式拒绝而不是当普通文本
EXCEL_ERROR_VALUES = frozenset({
    "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!", "#GETTING_DATA",
})


def is_comment_row(cells: list[str]) -> bool:
    """整行注释判定：首格以 `#` / `//` 开头，**且该行没有其它非空单元格**。

    审计 Z-01：改前只要首格以 `#` 开头就整行丢弃，于是
      - 公式错误值（`#N/A` `#REF!` `#DIV/0!` …）所在的数据行整行消失（恰恰是最该被看见的行）；
      - 以 `#` 开头的正式名称（`#1 号矿区`）无法录入；
    且 `--inspect` 的「已处理 N 行」、归档、导入结果会一致地少一行 —— 用户完全看不到。
    现在只有真正的「整行注释」才跳过，其余照常当数据行解析（必要时由必填列校验报错）。
    """
    if not cells:
        return False
    first = cells[0]
    if not (first.startswith("#") or first.startswith("//")):
        return False
    return all(c == "" for c in cells[1:])


def _table_rows(spec, table: list[list[str]]) -> list[tuple[int, dict]]:
    """把工作表切成 [(行号, {参数名: 单元格文本})]。

    - 表头可以是**中文**（推荐，见 `sheet_spec.HEADERS`）或英文参数名，两者等价；
    - 规范之外的列会报错（「公司」表例外：额外列当作该公司的产业字段初始值）；
    - 整行空白跳过；整行注释（首格以 `#` / `//` 开头且该行无其它非空单元格）跳过。
    """
    header_index = None
    raw_headers: list[str] = []
    for index, raw in enumerate(table):
        cells = [str(c or "").strip() for c in raw]
        if any(cells):
            header_index, raw_headers = index, cells
            break
    if header_index is None:
        return []

    alias = header_aliases(spec)
    headers = [alias.get(h, h) for h in raw_headers]   # 中文表头 → 参数名
    known = {col.key for col in spec.columns}

    unknown = [h for h in headers if h and h not in known]
    if unknown and not spec.allow_extra_columns:
        raise SheetFormatError(
            f"[{spec.name}] 表头里有规范之外的列：{'、'.join(unknown)}；本表可用列："
            + "、".join(f"{header_for(spec.name, col.key)}（{col.key}）" for col in spec.columns)
        )
    missing_required = [header_for(spec.name, col.key) for col in spec.columns
                        if col.required and col.key not in headers]
    if missing_required:
        raise SheetFormatError(f"[{spec.name}] 缺少必填列：{'、'.join(missing_required)}")
    duplicated = sorted({h for h in headers if h and headers.count(h) > 1})
    if duplicated:
        raise SheetFormatError(
            f"[{spec.name}] 表头重复（中文表头与英文参数名指向同一列，只保留一个即可）："
            f"{'、'.join(duplicated)}"
        )

    out: list[tuple[int, dict]] = []
    # 审计 Z-13：行级错误（错误值 / 必填列为空）逐行收集，最后一次性报出，而不是遇到第一处
    # 就中断 —— 否则十几行的表要「改一处、跑一次」来回十几轮。
    row_errors: list[str] = []
    for offset, raw in enumerate(table[header_index + 1:], start=header_index + 2):
        cells = [str(c or "").strip() for c in raw]
        if not any(cells):
            continue
        if is_comment_row(cells):
            continue
        # 审计 Z-12：Excel 错误值（#DIV/0! / #N/A / #REF! …）改前被当普通文本 —— 落在文本列上会
        # 原样写进比赛（库里出现一个叫「#DIV/0!」的原料/公司名）。这里显式拒绝，指出是哪一格，
        # 让用户去修公式；比静默丢弃（Z-01）或静默写脏数据都更安全。
        err = next(
            (i for i, c in enumerate(cells) if c in EXCEL_ERROR_VALUES),
            None,
        )
        if err is not None:
            if err < len(raw_headers) and raw_headers[err]:
                col = raw_headers[err]          # 用表格里的原始表头（中文），便于用户定位
            elif err < len(headers) and headers[err]:
                col = headers[err]
            else:
                col = f"第 {err + 1} 列"
            # 审计 Z-13：收集而不是立刻抛出（最后一次性报出，见函数末尾）
            row_errors.append(
                f"第 {offset} 行的「{col}」是 Excel 错误值 {cells[err]}"
                f"（公式算错或引用为空）——请先在表格里修正该公式，本工具不会把错误值写进比赛"
            )
            continue
        row = {
            headers[i]: cells[i]
            for i in range(min(len(headers), len(cells)))
            if headers[i] and cells[i] != ""
        }
        missing = [col for col in spec.columns if col.required and not row.get(col.key)]
        if missing:
            names = "、".join(header_for(spec.name, col.key) for col in missing)
            row_errors.append(f"[{spec.name}] 第 {offset} 行的必填列「{names}」为空")
            continue
        out.append((offset, row))
    if row_errors:
        head = row_errors[:20]
        more = f"\n…另有 {len(row_errors) - len(head)} 处未列出" if len(row_errors) > len(head) else ""
        raise SheetFormatError(
            f"表格里有 {len(row_errors)} 处错误，已全部列出（请一次改完再跑）：\n  - "
            + "\n  - ".join(head) + more
        )
    return out


# =============================================================================
# 展示与导入
# =============================================================================


def _empty_sheet_names(stats: dict[str, int]) -> list[str]:
    """只保留表头、没有数据行的工作表名（审计 Z-12 余项）。"""
    return [name for name, count in stats.items() if not count]


def _print_summary(archive: dict, *, empty_sheets: list[str] | None = None) -> None:
    """打印产出资源概览。

    审计 Z-12 余项：改前只列**非空**资源，用户看不出"我放了表却没产出"—— 空表（只有表头）
    的段既不出现也没有提示。现在把已知为空的工作表单独列出来并说明「归档里没有该段」。
    """
    resources = archive.get("resources") or {}
    print("产出资源：")
    total = 0
    for res in RESOURCE_ORDER:
        block = resources.get(res)
        if not block:
            continue
        total += block.get("count", 0)
        print(f"  - {block.get('label', res):<16} {block.get('count', 0):>5} 条  [{res}]")
    print(f"合计 {total} 条")
    if empty_sheets:
        print("以下工作表只有表头、没有任何数据行（归档里**没有**对应资源段）：")
        for name in sorted(empty_sheets):
            print(f"  - {name}")


def _try_resolve_card_fields(builder, competition_id: int, notes: list[str]) -> None:
    """回填「区域总览卡片」的产业字段主键 id（第二遍导入时生效）。

    产业字段是全局资源，首次导入某个库时还不存在，所以卡片第一遍拿不到 id
    （只是取不到值，不报错）。给定 `--competition` 时这里自动读一次目标库的
    「行业口径」归档并回填，配合 `--mode overwrite` 再导一次即可刷新卡片。
    """
    try:
        from apps.preparation import archive as archive_builder

        reference = archive_builder.build_export(competition_id, scope="industry")
        rows = ((reference.get("resources") or {}).get("industryFields") or {}).get("rows") or []
        if not rows:
            notes.append("目标库里还没有这些产业字段：总览卡片字段 id 保持占位 0，"
                         "先导入一次再带 --competition 跑第二遍（--mode overwrite）即可回填")
            return
        builder.resolve_field_ids(reference)
        notes.append(f"已按比赛 #{competition_id} 回填 {len(rows)} 条产业字段 id 到区域总览卡片")
    except BuilderError as exc:
        notes.append(f"卡片字段 id 回填跳过：{exc}")
    except Exception as exc:  # noqa: BLE001 - 回填失败不应阻断建包
        notes.append(f"卡片字段 id 回填跳过（{type(exc).__name__}: {exc}）")


def _import(archive: dict, competition_id: int, args) -> int:
    """复用既有导入引擎（与 manage.py build_competition 走同一条路径）。"""
    from apps.preparation import archive as archive_builder

    only_resources = None
    if args.scope and args.scope != archive_builder.SCOPE_ALL:
        if not archive_builder.is_valid_scope(args.scope):
            print(f"✗ 未知分组：{args.scope}", file=sys.stderr)
            return 2
        only_resources = set(archive_builder.resources_of_scope(args.scope))

    try:
        result = archive_builder.apply_import(
            archive, competition_id,
            dry_run=bool(args.dry_run),
            allow_non_empty=bool(args.allow_non_empty),
            mode=args.mode,
            only_resources=only_resources,
            user=None,
        )
    except archive_builder.ArchiveError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    label = "预演（未落库）" if result.get("dryRun") else "已导入"
    print(f"\n=== {label} · {result.get('modeLabel')} ===")
    for row in result.get("resources") or []:
        print(f"  - {row['label']:<16} 新建 {row['created']:>4} / 更新 {row['updated']:>4} / "
              f"保留 {row['kept']:>4} / 跳过 {row['skipped']:>4}  [{row['resource']}]")
    print(f"合计：新建 {result.get('created', 0)}，更新 {result.get('updated', 0)}，"
          f"保留 {result.get('kept', 0)}，跳过 {result.get('skipped', 0)}")
    for note in (result.get("notes") or [])[:10]:
        print(f"  · {note}")
    problems = result.get("problems") or []
    if problems:
        print(f"--- 问题（{len(problems)} 条）---", file=sys.stderr)
        for p in problems[:20]:
            print(f"  ! {p}", file=sys.stderr)
        return 1
    print("无 problem：所有行均已处理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
