"""`manage.py build_competition` —— 用建包脚本（或归档 JSON）创建一场比赛的内容。

本命令是**建包库的唯一落库入口**，内部完全复用已有的导入引擎
（`apps.preparation.archive.apply_import`）：外键映射、跨分组按名兜底、
追加/覆盖策略、空比赛保护、dry-run 回滚全部沿用既有实现，不新增任何写库逻辑。

用法
----
    # 1) 只看脚本会建出什么（不连数据库，纯打印归档摘要）
    python manage.py build_competition examples/competitions/demo_competition.py --inspect

    # 2) 导出归档 JSON 供前端「导入归档」上传
    python manage.py build_competition examples/competitions/demo_competition.py --out demo.json

    # 3) 预演导入（事务回滚，不留痕）
    python manage.py build_competition examples/competitions/demo_competition.py --competition 7 --dry-run

    # 4) 真正导入
    python manage.py build_competition examples/competitions/demo_competition.py --competition 7

    # 5) 导入已有归档 JSON
    python manage.py build_competition demo.json --competition 7 --dry-run

    # 6) 打印某类资源的字段字典
    python manage.py build_competition --schema companies

脚本约定
--------
脚本是一个普通 Python 文件，里面只要有下列任意一种即可（按顺序查找）：

    def build() -> CompetitionBuilder            # 推荐：函数返回构建器
    BUILDER = CompetitionBuilder("比赛名")        # 模块级构建器
    ARCHIVE = {...}                              # 已构造好的归档 dict（直接导入）
    from ... import CompetitionBuilder; CompetitionBuilder("比赛名")...  # 兜底：执行脚本，取最后一个表达式

脚本里用绝对导入即可：`from apps.preparation.builder import CompetitionBuilder`
（本命令已把项目根目录加入 sys.path，且 Django 已初始化）。

退出码：0 成功；1 脚本/构建错误；2 导入被拒绝（如目标比赛非空且未加 --allow-non-empty）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.preparation import archive as archive_builder
from apps.preparation.builder import RESOURCE_ORDER, CompetitionBuilder, describe_resource


class Command(BaseCommand):
    help = "用 Python 建包脚本（或归档 JSON）创建一场比赛的内容（复用归档导入引擎）"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "source",
            nargs="?",
            help="建包脚本（.py）或归档文件（.json）路径",
        )
        parser.add_argument(
            "--competition",
            type=int,
            default=None,
            help="目标比赛 id（导入必需；--inspect / --out 不需要）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只预演不落库（事务回滚，返回与真实导入一致的结果）",
        )
        parser.add_argument(
            "--allow-non-empty",
            action="store_true",
            help="允许导入到已有业务数据的比赛（默认拒绝，避免污染既有数据）",
        )
        parser.add_argument(
            "--mode",
            choices=list(archive_builder.IMPORT_MODES),
            default=archive_builder.MODE_APPEND,
            help=(
                f"导入方式：{archive_builder.MODE_LABELS[archive_builder.MODE_APPEND]} / "
                f"{archive_builder.MODE_LABELS[archive_builder.MODE_OVERWRITE]}（默认 append）"
            ),
        )
        parser.add_argument(
            "--resources",
            default=None,
            help="只导入这些资源（逗号分隔，如 companies,companyFieldValues）；缺省=全部",
        )
        parser.add_argument(
            "--scope",
            default=None,
            help=(
                "只产出/导入某个分组："
                + " / ".join(archive_builder.SCOPES)
                + "（缺省=全部）"
            ),
        )
        parser.add_argument("--out", default=None, help="把脚本产出的归档 JSON 写到该路径（不连数据库）")
        parser.add_argument(
            "--inspect",
            action="store_true",
            help="只打印脚本产出的资源摘要与体检提醒，不做任何导入",
        )
        parser.add_argument(
            "--schema",
            nargs="?",
            const="",
            default=None,
            metavar="RESOURCE",
            help="打印资源字段字典（不给资源名则打印全部）",
        )

    # ---------------- 入口 ----------------

    def handle(self, *args, **options) -> None:
        if options["schema"] is not None:
            self._print_schema(options["schema"])
            return

        source = options["source"]
        if not source:
            raise CommandError("请给出建包脚本（.py）或归档文件（.json）；或使用 --schema 查看字段字典")

        path = Path(source).expanduser()
        if not path.exists():
            raise CommandError(f"文件不存在：{path}")

        archive = self._load_archive(path, options.get("scope"))

        if options["out"]:
            out = Path(options["out"]).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(archive, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            self.stdout.write(self.style.SUCCESS(f"已写出归档：{out}"))

        if options["inspect"]:
            self._print_summary(archive)
            if not options["out"]:
                return

        competition_id = options["competition"]
        if competition_id is None:
            if options["inspect"] or options["out"]:
                return  # 只产出不导入
            raise CommandError("导入需要 --competition <比赛 id>（或改用 --inspect / --out 只产出）")

        self._import(archive, competition_id, options)

    # ---------------- 读取来源 ----------------

    def _load_archive(self, path: Path, scope: str | None) -> dict:
        """按扩展名分流：.json 直接读归档；其它当作 Python 建包脚本执行。"""
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise CommandError(f"归档文件读取失败：{e}")
            try:
                return archive_builder.validate_archive(payload)
            except archive_builder.ArchiveError as e:
                raise CommandError(f"归档文件结构非法：{e}")
        return self._run_script(path, scope)

    def _run_script(self, path: Path, scope: str | None) -> dict:
        """执行建包脚本，取出归档 dict。"""
        module = self._exec_module(path)
        builder = getattr(module, "BUILDER", None)
        archive = getattr(module, "ARCHIVE", None)
        build_fn = getattr(module, "build", None)

        if callable(build_fn):
            produced = build_fn()
        elif isinstance(builder, CompetitionBuilder):
            produced = builder
        elif isinstance(archive, dict):
            try:
                return archive_builder.validate_archive(archive)
            except archive_builder.ArchiveError as e:
                raise CommandError(f"脚本里的 ARCHIVE 结构非法：{e}")
        elif hasattr(module, "LAST_BUILDER"):
            produced = getattr(module, "LAST_BUILDER")
        else:
            raise CommandError(
                f"脚本 {path} 里没有可用的产出：请定义 build() 函数（返回 CompetitionBuilder）、"
                "模块级 BUILDER，或模块级 ARCHIVE 字典"
            )

        if isinstance(produced, CompetitionBuilder):
            return produced.build(scope=scope)
        if isinstance(produced, dict):
            try:
                return archive_builder.validate_archive(produced)
            except archive_builder.ArchiveError as e:
                raise CommandError(f"脚本 build() 返回的结构非法：{e}")
        raise CommandError(
            f"脚本 {path} 的 build() 必须返回 CompetitionBuilder 或归档 dict，"
            f"实际返回 {type(produced).__name__}"
        )

    def _exec_module(self, path: Path):
        """把脚本当模块执行（注入 LAST_BUILDER 兜底，便于「最后一行是构建器」的写法）。"""
        import apps.preparation.builder as builder_pkg

        spec = importlib.util.spec_from_file_location(f"_build_competition_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise CommandError(f"无法加载脚本：{path}")
        module = importlib.util.module_from_spec(spec)
        # 兜底：脚本最后一行若只写了构建器表达式，这里能拿到该实例
        original_init = builder_pkg.CompetitionBuilder.__init__

        def patched_init(self, *a, **kw):  # type: ignore[no-untyped-def]
            original_init(self, *a, **kw)
            module.__dict__["LAST_BUILDER"] = self

        builder_pkg.CompetitionBuilder.__init__ = patched_init  # type: ignore[assignment]
        try:
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        except Exception as e:  # noqa: BLE001 - 脚本错误直接暴露给使用者
            import traceback

            self.stderr.write(traceback.format_exc())
            raise CommandError(f"建包脚本执行失败：{type(e).__name__}: {e}")
        finally:
            builder_pkg.CompetitionBuilder.__init__ = original_init  # type: ignore[assignment]
        return module

    # ---------------- 展示 ----------------

    def _print_summary(self, archive: dict) -> None:
        resources = archive.get("resources") or {}
        self.stdout.write(f"比赛名：{(archive.get('sourceCompetition') or {}).get('name')}")
        self.stdout.write(f"分组：{archive.get('scopeLabel')}（{archive.get('scope')}）")
        self.stdout.write("产出资源：" + (f"{len(resources)} 类" if resources else "（空）"))
        total = 0
        for res in RESOURCE_ORDER:
            block = resources.get(res)
            if not block:
                continue
            total += block.get("count", 0)
            self.stdout.write(f"  - {block.get('label', res):<16} {block.get('count', 0):>5} 条  [{res}]")
        self.stdout.write(f"合计 {total} 条")

    def _print_schema(self, resource: str) -> None:
        from apps.preparation.builder import RESOURCE_ORDER as order
        from apps.preparation.builder import schema_markdown

        if not resource:
            self.stdout.write(schema_markdown())
            return
        if resource not in order:
            raise CommandError(
                f"未知资源名：{resource}；可选 {', '.join(order)}"
            )
        describe_resource(resource)  # 触发未知资源名校验
        self.stdout.write(schema_markdown(resource))

    # ---------------- 导入 ----------------

    def _import(self, archive: dict, competition_id: int, options: dict) -> None:
        only_resources = self._parse_resources(options.get("resources"))
        # 未显式给出 --resources 时，若给了 --scope 则按该分组的资源集合导入，
        # 避免「脚本按分组产出、却把整包都导进去」的意外。
        if only_resources is None and options.get("scope") and options["scope"] != archive_builder.SCOPE_ALL:
            scope = options["scope"]
            if not archive_builder.is_valid_scope(scope):
                raise CommandError(f"未知分组：{scope}")
            only_resources = set(archive_builder.resources_of_scope(scope))

        try:
            result = archive_builder.apply_import(
                archive,
                competition_id,
                dry_run=bool(options["dry_run"]),
                allow_non_empty=bool(options["allow_non_empty"]),
                mode=options["mode"],
                only_resources=only_resources,
                user=None,
            )
        except archive_builder.ArchiveError as e:
            raise CommandError(str(e))

        if not options["dry_run"]:
            self._print_summary(archive)
        self._print_result(result)

        problems = result.get("problems") or []
        if problems:
            # 有问题意味着部分数据没落地，用非零退出码让脚本/CI 能发现
            sys.exit(1)

    def _parse_resources(self, raw) -> set[str] | None:
        if not raw:
            return None
        items = {x.strip() for x in str(raw).split(",") if x.strip()}
        unknown = sorted(r for r in items if r not in archive_builder.IMPORT_ORDER)
        if unknown:
            raise CommandError(f"未知资源名：{', '.join(unknown)}")
        return items or None

    def _print_result(self, result: dict) -> None:
        mode_label = "预演（未落库）" if result.get("dryRun") else "已导入"
        self.stdout.write("")
        self.stdout.write(f"=== {mode_label} · {result.get('modeLabel')} ===")
        if result.get("blocked"):
            self.stdout.write(self.style.WARNING("目标比赛已有业务数据，默认拒绝导入（见下方问题）"))
        for row in result.get("resources") or []:
            self.stdout.write(
                f"  - {row['label']:<16} 新建 {row['created']:>4} / 更新 {row['updated']:>4} / "
                f"保留 {row['kept']:>4} / 跳过 {row['skipped']:>4}  [{row['resource']}]"
            )
        self.stdout.write(
            f"合计：新建 {result.get('created', 0)}，更新 {result.get('updated', 0)}，"
            f"保留 {result.get('kept', 0)}，跳过 {result.get('skipped', 0)}"
        )
        occupancy = result.get("occupancy") or []
        if occupancy and not result.get("dryRun"):
            detail = "、".join(f"{o['label']} {o['count']} 条" for o in occupancy[:8])
            self.stdout.write(f"目标比赛当前数据：{detail}")

        notes = result.get("notes") or []
        if notes:
            self.stdout.write("")
            self.stdout.write(f"--- 提示（{len(notes)} 条，节选）---")
            for n in notes[:15]:
                self.stdout.write(f"  · {n}")
            if len(notes) > 15:
                self.stdout.write(f"  · …还有 {len(notes) - 15} 条")

        problems = result.get("problems") or []
        if problems:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"--- 问题（{len(problems)} 条，需处理）---"))
            for p in problems[:25]:
                self.stdout.write(self.style.ERROR(f"  ! {p}"))
            if len(problems) > 25:
                self.stdout.write(self.style.ERROR(f"  ! …还有 {len(problems) - 25} 条"))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("无 problem：所有行均已处理"))
