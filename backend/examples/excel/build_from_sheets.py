# -*- coding: utf-8 -*-
"""用**表格文件**（Excel / CSV 目录）快速建一场比赛：读表 → 建包 → 导入。

一张工作表 = 一类内容，表与表之间相互隔离：只填你要建的那几张表即可，
没出现的表完全不参与产出。规范见 [`sheet_spec.py`](sheet_spec.py) 与
[`docs/比赛Excel建包规范.md`](../../../docs/比赛Excel建包规范.md)。

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

    # 4) 直接导入到某场比赛（预演 → 真导）
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 190 --dry-run
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 190

    # 5) 只建「参赛主体」分组；或只处理指定几张表
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 190 --scope company
    .\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 190 --sheets 公司,公司字段值

退出码：0 成功；1 表格格式错误或导入出现 problem；2 用法错误。
"""
from __future__ import annotations

import argparse
import json
import sys
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
    SHEET_BY_NAME,
    SHEETS,
    UNSUPPORTED_SHEETS,
    SheetContext,
    SheetFormatError,
    header_aliases,
    header_for,
    summarize_spec,
)
from xlsx_io import load_tables  # noqa: E402


class SheetBuildError(Exception):
    """整表读取/建包过程中的可读错误（带工作表与行号）。"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="用表格文件（Excel / CSV 目录）建比赛")
    parser.add_argument("source", nargs="?", help="表格文件（.xlsx）或存放 CSV 的目录")
    parser.add_argument("--inspect", action="store_true", help="只打印产出摘要，不导入")
    parser.add_argument("--out", default=None, help="把产出的归档 JSON 写到该路径")
    parser.add_argument("--competition", type=int, default=None, help="导入到该比赛 id")
    parser.add_argument("--dry-run", action="store_true", help="预演导入（事务回滚，不落库）")
    parser.add_argument("--mode", choices=["append", "overwrite"], default="append")
    parser.add_argument("--allow-non-empty", action="store_true", help="允许导入到已有数据的比赛")
    parser.add_argument("--scope", default=None, help="只处理/导入某个分组：competition/industry/company/supply/geo/tech/market/access")
    parser.add_argument("--sheets", default=None, help="只处理这些表（逗号分隔，如 公司,合同实例）")
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

    try:
        builder, stats, notes = build_from_tables(
            Path(args.source), only_sheets=args.sheets, fallback_name=args.name,
            name_override=args.name,
        )
        if args.competition is not None:
            _try_resolve_card_fields(builder, args.competition, notes)
        archive = builder.build()
    except (SheetFormatError, SheetBuildError, BuilderError, ValueError) as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"表格来源：{args.source}")
    print(f"比赛名：{archive['sourceCompetition']['name']}")

    competition_id = args.competition
    if args.create_competition and competition_id is None:
        competition_id = _create_competition(archive["sourceCompetition"]["name"],
                                             archive["resources"].get("competitionMeta", {}))
        args.competition = competition_id

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

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(archive, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"已写出归档：{out_path}")

    if args.inspect or (not args.out and args.competition is None):
        _print_summary(archive)
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
) -> tuple[CompetitionBuilder, dict[str, int], list[str]]:
    """读取表格并逐表交给建包库，返回 (构建器, 每表行数, 提示)。

    注意：**表格里出现的表都会被处理**（`only_sheets` 除外）。引用解析依赖它们
    （例如「公司」表引用「产业类型」，「零件」表引用「原料」），所以不要按分组去裁表；
    `--scope` 只用来限制**导入范围**。
    """
    if not source.exists():
        raise SheetBuildError(f"表格来源不存在：{source}")
    tables = load_tables(source)
    selected = {s.strip() for s in only_sheets.split(",") if s.strip()} if only_sheets else None

    notes: list[str] = []
    meta = _competition_meta(tables, fallback_name or source.stem, override_name=name_override)
    builder = CompetitionBuilder(meta["name"], status=meta["status"], map_background=meta["map_background"])

    ctx = SheetContext(builder=builder, base_dir=source.parent if source.is_file() else source)
    stats: dict[str, int] = {}

    for name in tables:
        if name in NOTES_SHEET_NAMES:
            continue
        if name in UNSUPPORTED_SHEETS:
            notes.append(f"工作表「{name}」未处理：{UNSUPPORTED_SHEETS[name]}")
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
        for row_no, row in rows:
            ctx.row_no = row_no
            try:
                spec.handler(ctx, row)
            except SheetFormatError as exc:
                raise SheetFormatError(f"[{spec.name}] 第 {row_no} 行：{exc}") from None
            except BuilderError as exc:
                raise SheetBuildError(
                    f"[{spec.name}] 第 {row_no} 行：{exc}{_reference_hint(str(exc), tables, selected)}"
                ) from None
        stats[spec.name] = len(rows)

    notes.extend(ctx.notes)
    notes.append(f"共处理 {len(stats)} 张表、{sum(stats.values())} 行数据"
                 "（只处理出现在表格里的表，其余表完全不参与产出）")
    return builder, stats, notes


def _create_competition(name: str, meta_block: dict) -> int:
    """按表格里的比赛名新建（或复用同名）比赛，返回比赛 id。

    只做一件事：写入 `Competition` 这一行（比赛名全局唯一，同名直接复用），
    其余内容仍由既有导入引擎落库。
    """
    from apps.competitions.models import Competition

    status = "ACTIVE"
    rows = meta_block.get("rows") or []
    if rows and isinstance(rows[0], dict):
        status = str(rows[0].get("status") or status).upper()
    competition = Competition.objects.filter(name=name).first()
    if competition is None:
        competition = Competition.objects.create(name=name, status=status)
        print(f"已新建比赛：#{competition.id}「{competition.name}」（状态 {competition.status}）")
    else:
        print(f"复用已有比赛：#{competition.id}「{competition.name}」（状态 {competition.status}）")
    return competition.id


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


def _table_rows(spec, table: list[list[str]]) -> list[tuple[int, dict]]:
    """把工作表切成 [(行号, {参数名: 单元格文本})]。

    - 表头可以是**中文**（推荐，见 `sheet_spec.HEADERS`）或英文参数名，两者等价；
    - 规范之外的列会报错（「公司」表例外：额外列当作该公司的产业字段初始值）；
    - 以 `#` / `//` 开头的行是注释行，整行空白跳过。
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
    for offset, raw in enumerate(table[header_index + 1:], start=header_index + 2):
        cells = [str(c or "").strip() for c in raw]
        if not any(cells):
            continue
        if cells[0].startswith("#") or cells[0].startswith("//"):
            continue
        row = {
            headers[i]: cells[i]
            for i in range(min(len(headers), len(cells)))
            if headers[i] and cells[i] != ""
        }
        for col in spec.columns:
            if col.required and not row.get(col.key):
                raise SheetFormatError(
                    f"[{spec.name}] 第 {offset} 行的必填列「{header_for(spec.name, col.key)}」为空"
                )
        out.append((offset, row))
    return out


# =============================================================================
# 展示与导入
# =============================================================================


def _print_summary(archive: dict) -> None:
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
