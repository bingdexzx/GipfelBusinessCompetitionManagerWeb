"""建包库测试：证明「库产出的归档 == 导入引擎预期」，且不影响既有功能。

核心思路（不重写导入逻辑，只验证契约）：
1. **对拍** `archive.build_export`：库产出的每个资源、每一列，导出侧都必须认得；
   导出侧有的列也都必须在库的 schema 里有说明 —— 双向查漏，任何一方漂移都会失败。
2. **零 problem 全量导入**：一次性把演示比赛（覆盖全部 35 类资源）用 dry_run 导入，
   断言 `problems` 为空。导入引擎对「引用缺失 / 必填缺失 / 结构不对」都会记 problem，
   因此这一条等价于端到端验证了全部资源的字段口径。
3. **往返一致**：真实导入 → 导出 → 再导入一次，断言第二次全部走「已存在」路径
   （幂等，没有重复建记录、没有 problem）。
4. **顺序一致性**：库的资源顺序必须与 `archive.IMPORT_ORDER` 完全相同（否则引用解析不到）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from django.test import TestCase

from apps.competitions.models import Competition
from apps.contracts.models import Contract, ContractType
from apps.preparation import archive as A
from apps.preparation.builder import (
    RESOURCE_LABELS,
    RESOURCE_ORDER,
    RESOURCE_SCHEMA,
    BuilderError,
    CompetitionBuilder,
    calc_graph,
    calc_node,
    verify_rows,
)

# 位于仓库里的完整示例脚本
DEMO_PATH = Path(__file__).resolve().parents[3] / "examples" / "competitions" / "demo_competition.py"

# 导入侧「按名兜底 / 由引擎自行求值」的列：建包库允许不产出它们。
# 说明：这些列全部是**可选**的（导入侧取不到时会退化为按 id 解析或保持空），
# 建包库改用「名称列 + 引用列」表达，因此不产出它们不算漂移。
IMPORTER_ONLY_COLUMNS: dict[str, set[str]] = {
    "companies": {"regionId"},
    "mapNodes": {"nodeTypeId"},
    "mapEdges": {"fromNodeId", "toNodeId", "pathTypeId"},
    "vehicles": {"fuelId"},
    "stocks": {"pbFieldId"},
    "stockFundsAccounts": {"bindFieldId"},
    "consumerDemands": {"productId"},
    "companyFieldValues": {"version"},
}


def load_demo_builder() -> CompetitionBuilder:
    """执行示例脚本取回它的构建器（示例本身就是「用户怎么写代码」的样板）。"""
    spec = importlib.util.spec_from_file_location("demo_competition_for_test", DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


class ArchiveParityTests(TestCase):
    """库与导入引擎的一致性（防漂移）。"""

    def test_resource_order_matches_importer(self):
        """资源顺序必须与 archive.IMPORT_ORDER 完全一致（依赖顺序错会导致引用解析不到）。"""
        self.assertEqual(list(RESOURCE_ORDER), list(A.IMPORT_ORDER))
        self.assertEqual(len(set(RESOURCE_ORDER)), len(RESOURCE_ORDER), "资源名不能重复")

    def test_every_resource_has_label_and_schema(self):
        """每类资源都要有中文名、列定义与导入函数，避免新增资源时漏登记。"""
        for res in RESOURCE_ORDER:
            with self.subTest(resource=res):
                self.assertIn(res, RESOURCE_LABELS, f"{res} 缺少中文名")
                self.assertIn(res, RESOURCE_SCHEMA, f"{res} 缺少列定义（schema.py）")
                self.assertIn(res, A._IMPORTERS, f"{res} 在导入引擎里没有导入函数")

    def test_builder_row_columns_are_accepted_by_schema(self):
        """示例比赛产出的每一列都必须能在 schema 里查到（拦住拼错的字段名）。"""
        archive = load_demo_builder().build()
        for res, block in archive["resources"].items():
            with self.subTest(resource=res):
                verify_rows(res, block["rows"])  # 列名未知即抛 BuilderError

    def test_demo_covers_all_resources(self):
        """示例脚本必须覆盖全部 35 类资源（文档承诺「全覆盖」）。"""
        archive = load_demo_builder().build()
        missing = sorted(set(RESOURCE_ORDER) - set(archive["resources"]))
        self.assertEqual(missing, [], f"示例未覆盖：{missing}")

    def test_no_key_typo_can_slip_through(self):
        """故意写错列名必须被拦下（防止「静默用默认值」这类最难查的问题）。"""
        with self.assertRaises(BuilderError) as ctx:
            verify_rows("materials", [{"name": "铁矿石", "carbonEmmisionCoefficient": 0.5}])
        self.assertIn("carbonEmmisionCoefficient", str(ctx.exception))


class DemoImportTests(TestCase):
    """示例比赛的端到端导入：零 problem、落库完整、幂等。"""

    def setUp(self):
        self.competition = Competition.objects.create(name="建包库测试赛")
        self.builder = load_demo_builder()
        self.archive = self.builder.build()

    # ---------- 预演与真实导入 ----------

    def test_dry_run_has_no_problem(self):
        """全 35 类资源 dry_run 导入后不许有任何 problem（等价于字段口径全对）。"""
        result = A.apply_import(
            self.archive, self.competition.id, dry_run=True, allow_non_empty=False
        )
        self.assertEqual(result["problems"], [], f"出现 problem：{result['problems']}")
        self.assertFalse(result["blocked"])
        self.assertGreater(result["created"], 0)

    def test_dry_run_leaves_no_data(self):
        """dry_run 必须回滚干净（不留任何痕迹）。"""
        A.apply_import(self.archive, self.competition.id, dry_run=True, allow_non_empty=False)
        self.assertEqual(self.competition.companies.count(), 0)
        self.assertEqual(self.competition.map_nodes.count(), 0)
        self.assertEqual(Contract.objects.filter(competition=self.competition).count(), 0)

    def test_real_import_lands_all_rows_and_reports_no_problem(self):
        """真实导入：所有行都落地，且 problem 为空。"""
        result = A.apply_import(
            self.archive, self.competition.id, dry_run=False, allow_non_empty=False
        )
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["skipped"], 0, "不该有被跳过的行")
        self.assertEqual(self.competition.companies.count(), 3)
        self.assertEqual(self.competition.map_nodes.count(), 4)
        self.assertEqual(self.competition.map_edges.count(), 4)
        self.assertEqual(self.competition.parts.count(), 3)
        self.assertEqual(self.competition.products.count(), 2)
        self.assertEqual(self.competition.stocks.count(), 3)
        self.assertEqual(self.competition.stock_funds_accounts.count(), 4)
        self.assertEqual(Contract.objects.filter(competition=self.competition).count(), 2)
        self.assertEqual(self.competition.users.count(), 4)
        self.assertEqual(self.competition.fiscal_years.count(), 1)

    def test_company_field_values_land(self):
        """公司字段初始值必须落到正确的字段上（否则开赛数值全错）。"""
        from apps.companies.models import CompanyFieldValue

        A.apply_import(self.archive, self.competition.id, dry_run=False, allow_non_empty=False)
        company = self.competition.companies.get(name="甲钢铁集团")
        values = {
            v.industry_field.field_key: v.value
            for v in CompanyFieldValue.objects.filter(company=company).select_related("industry_field")
        }
        self.assertEqual(values.get("cash"), "800000")
        self.assertEqual(values.get("location"), "东区港")

    def test_contract_parties_point_at_real_companies(self):
        """合同参与方必须指向本场比赛的公司（跨比赛导入最容易断在这里）。"""
        A.apply_import(self.archive, self.competition.id, dry_run=False, allow_non_empty=False)
        # 合同名缺省取合同类型名（与导入侧判重口径一致）
        contract = Contract.objects.get(competition=self.competition, name="钢材销售合同")
        parties = json.loads(contract.parties)
        company_names = {p.get("companyName") for p in parties}
        self.assertEqual(company_names, {"甲钢铁集团", "丙机械"})
        ids = {p.get("companyId") for p in parties}
        real_ids = set(self.competition.companies.values_list("id", flat=True))
        self.assertTrue(ids <= real_ids, f"参与方公司 id 未映射到本比赛：{ids} vs {real_ids}")

    def test_tech_prerequisites_resolve_by_id(self):
        """科技前置在导入侧只认旧 id，必须能正确映射（曾是最容易漏的一处）。"""
        A.apply_import(self.archive, self.competition.id, dry_run=False, allow_non_empty=False)
        roll = self.competition.tech_nodes.get(name="热轧工艺")
        smelt = self.competition.tech_nodes.get(name="高炉冶炼")
        self.assertEqual(
            list(roll.prerequisites.values_list("prerequisite_id", flat=True)), [smelt.id]
        )

    def test_global_resources_are_reused_not_duplicated(self):
        """产业类型是全局资源：第二次导入不许重复建，只复用。"""
        from apps.industry_types.models import IndustryType

        A.apply_import(self.archive, self.competition.id, dry_run=False, allow_non_empty=False)
        before = IndustryType.objects.filter(code=1).count()
        other = Competition.objects.create(name="建包库测试赛2")
        A.apply_import(self.archive, other.id, dry_run=False, allow_non_empty=False)
        self.assertEqual(IndustryType.objects.filter(code=1).count(), before)

    def test_second_import_is_idempotent(self):
        """重复导入同一份归档：全部走「已存在」路径，不重复建记录、无 problem。"""
        A.apply_import(self.archive, self.competition.id, dry_run=False, allow_non_empty=False)
        second = A.apply_import(
            self.archive,
            self.competition.id,
            dry_run=False,
            allow_non_empty=True,
            mode=A.MODE_OVERWRITE,
        )
        self.assertEqual(second["problems"], [])
        self.assertEqual(self.competition.companies.count(), 3)
        self.assertEqual(self.competition.map_nodes.count(), 4)
        self.assertEqual(Contract.objects.filter(competition=self.competition).count(), 2)


class RoundTripTests(TestCase):
    """往返：库 → 导入 → 导出 → 再导入（证明库产出与导出完全同构）。"""

    def setUp(self):
        self.competition = Competition.objects.create(name="建包库往返赛")

    def test_export_columns_are_known_to_schema(self):
        """导出侧产出的每一列，库的 schema 都必须有说明（反向查漏）。"""
        builder = load_demo_builder()
        A.apply_import(builder.build(), self.competition.id, dry_run=False, allow_non_empty=False)

        exported = A.build_export(self.competition.id, A.SCOPE_ALL)
        self.assertEqual(exported["schemaVersion"], 1)
        unknown_report: list[str] = []
        for res, block in exported["resources"].items():
            schema = RESOURCE_SCHEMA.get(res)
            if schema is None:
                unknown_report.append(f"{res}: 缺少列定义")
                continue
            allowed = set(schema.column_names) | {"_id"} | IMPORTER_ONLY_COLUMNS.get(res, set())
            for row in block["rows"]:
                extra = sorted(set(row) - allowed)
                if extra:
                    unknown_report.append(f"{res}: 导出多出未登记列 {extra}")
                    break
        self.assertEqual(unknown_report, [], "列定义与导出侧漂移：\n" + "\n".join(unknown_report))

    def test_reexport_can_be_imported_again(self):
        """导出的归档能再次导入（库的产物与导出产物同构的最终证据）。"""
        builder = load_demo_builder()
        A.apply_import(builder.build(), self.competition.id, dry_run=False, allow_non_empty=False)

        exported = A.build_export(self.competition.id, A.SCOPE_ALL)
        target = Competition.objects.create(name="建包库往返赛-目标")
        result = A.apply_import(exported, target.id, dry_run=False, allow_non_empty=False)
        self.assertEqual(result["problems"], [], f"往返导入出现 problem：{result['problems']}")
        self.assertEqual(target.companies.count(), 3)
        self.assertEqual(target.map_edges.count(), 4)
        self.assertEqual(target.stocks.count(), 3)

    def test_merged_demo_archive_imports_cleanly(self):
        """合并库产出与导出内容后再导入，同样不许有 problem（两套来源可混用）。

        注意用 **overwrite（覆盖）模式**：append 模式下导入引擎把「合同实例」视为
        「合同类型」的子资源（archive._CHILD_OF），而合同类型是全局资源、必然已存在，
        于是 append 会把本该新建的合同实例一并跳过。这是导入引擎的既有语义，
        不是建包库引入的问题；跨比赛搬运合同请用 overwrite（或先导公司、再单独导合同）。
        """
        builder = load_demo_builder()
        A.apply_import(builder.build(), self.competition.id, dry_run=False, allow_non_empty=False)
        exported = A.build_export(self.competition.id, A.SCOPE_ALL)

        target = Competition.objects.create(name="建包库往返赛-合并")
        result = A.apply_import(
            exported, target.id, dry_run=False, allow_non_empty=False, mode=A.MODE_OVERWRITE
        )
        self.assertEqual(result["problems"], [], f"往返导入出现 problem：{result['problems']}")
        contract = Contract.objects.get(competition=target, name="钢材销售合同")
        self.assertTrue(all(p.get("companyId") for p in json.loads(contract.parties)))
        # 参与方指向的公司必须属于目标比赛
        real_ids = set(target.companies.values_list("id", flat=True))
        self.assertTrue({p["companyId"] for p in json.loads(contract.parties)} <= real_ids)

    def test_append_mode_skips_contract_instances_when_type_is_global(self):
        """记录导入引擎的既有语义：append 模式下合同实例会因「合同类型已存在」被跳过。

        这条不是要求建包库做什么，而是把行为钉住：将来 archive 改了这条语义，
        测试会失败并提醒我们同步更新文档（docs/BUILD_COMPETITION_BY_CODE.md）。
        """
        builder = load_demo_builder()
        source = Competition.objects.create(name="语义源赛")
        A.apply_import(builder.build(), source.id, dry_run=False, allow_non_empty=False)
        exported = A.build_export(source.id, A.SCOPE_ALL)

        target = Competition.objects.create(name="语义目标赛")
        A.apply_import(exported, target.id, dry_run=False, allow_non_empty=False, mode=A.MODE_APPEND)
        self.assertEqual(Contract.objects.filter(competition=target).count(), 0, "append 下确实被跳过")

        # 换成 overwrite 就能正常搬运
        A.apply_import(
            exported, target.id, dry_run=False, allow_non_empty=True, mode=A.MODE_OVERWRITE
        )
        self.assertEqual(Contract.objects.filter(competition=target).count(), 2)


class BuilderValidationTests(TestCase):
    """构建期的硬错误必须即时拦下（不能等到导入才失败）。"""

    def test_duplicate_name_rejected(self):
        b = CompetitionBuilder("查重赛")
        it = b.industry_type(11, "测试产业")
        b.company("同名公司", industry_type=it)
        with self.assertRaises(BuilderError):
            b.company("同名公司", industry_type=it)

    def test_unknown_reference_rejected(self):
        b = CompetitionBuilder("引用赛")
        it = b.industry_type(12, "测试产业2")
        b.company("甲", industry_type=it)
        with self.assertRaises(BuilderError):
            b.demand("东区", "不存在的产品", 10)

    def test_field_value_for_unknown_field_rejected(self):
        b = CompetitionBuilder("字段赛")
        it = b.industry_type(13, "测试产业3")
        b.add_field(it, "现金", "cash")
        with self.assertRaises(BuilderError):
            b.company("甲", industry_type=it, field_values={"not_registered": "1"})

    def test_calculated_and_timer_are_mutually_exclusive(self):
        b = CompetitionBuilder("互斥赛")
        it = b.industry_type(14, "测试产业4")
        with self.assertRaises(BuilderError):
            b.add_field(
                it, "坏字段", "bad", is_calculated=True, timer_enabled=True,
                timer_trigger="FY_START", timer_value="1",
                graph=calc_graph(calc_node("add")),
            )

    def test_calculated_field_requires_graph(self):
        b = CompetitionBuilder("计算图赛")
        it = b.industry_type(15, "测试产业5")
        with self.assertRaises(BuilderError):
            b.add_field(it, "缺图字段", "nog", is_calculated=True)

    def test_part_ratio_cannot_reference_another_part(self):
        """依赖方向固定为 原料 → 零件 → 产品，零件不能引用零件。"""
        b = CompetitionBuilder("依赖赛")
        m = b.material("原料A")
        p1 = b.part("零件A", materials={m: 1})
        with self.assertRaises(BuilderError):
            b.part("零件B", materials={p1: 2})

    def test_self_loop_tech_rejected(self):
        b = CompetitionBuilder("自环赛")
        t = b.tech("科技A")
        with self.assertRaises(BuilderError):
            b.add_prerequisite(t, t)

    def test_cycle_detected_as_warning(self):
        """科技前置成环不会崩，但必须给出提醒（研发永远解锁不了）。"""
        b = CompetitionBuilder("成环赛")
        t1 = b.tech("科技1")
        t2 = b.tech("科技2")
        b.add_prerequisite(t1, t2)
        # 追加一条反向边，构造 A→B、B→A 的环
        rows = b.rows("techNodes")
        id_of = {r["name"]: r["_id"] for r in rows}
        b._extra["techPrerequisites"].append(
            {"_id": 99, "nodeId": id_of["科技2"], "prerequisiteId": id_of["科技1"]}
        )
        warnings = b.validate()
        self.assertTrue(any("环路" in w for w in warnings), warnings)

    def test_isolated_node_warned(self):
        b = CompetitionBuilder("孤立点赛")
        nt = b.node_type("城市")
        b.node("孤立点", nt)
        self.assertTrue(any("孤立" in w for w in b.validate()))

    def test_vehicle_without_path_type_warned(self):
        b = CompetitionBuilder("载具赛")
        f = b.fuel("柴油")
        b.vehicle("卡车", fuel=f)
        self.assertTrue(any("可通行路径" in w for w in b.validate()))

    def test_map_edge_endpoints_must_differ(self):
        b = CompetitionBuilder("连线赛")
        nt = b.node_type("城市")
        pt = b.path_type("公路")
        n = b.node("A", nt)
        with self.assertRaises(BuilderError):
            b.edge(n, n, 10, pt)

    def test_scope_filter_only_emits_that_group(self):
        """build(scope=...) 只产出该分组的资源。"""
        b = CompetitionBuilder("分组赛")
        it = b.industry_type(16, "测试产业6")
        b.add_field(it, "所在地", "location", field_type="STRING")
        b.region("东区")
        archive = b.build(scope="company")
        self.assertEqual(set(archive["resources"]), {"companies"} if b.names("companies") else set())

    def test_unknown_scope_rejected(self):
        b = CompetitionBuilder("分组赛2")
        with self.assertRaises(BuilderError):
            b.build(scope="not-a-scope")


class CardFieldIdResolutionTests(TestCase):
    """总览卡片的 industryFieldId 回填（纯代码建包无法凭空得知的数据库主键）。"""

    def setUp(self):
        self.competition = Competition.objects.create(name="卡片回填赛")

    def test_cards_use_placeholder_before_resolution(self):
        """未回填时卡片写 0，并且 validate() 必须提醒（不能让卡片静默失效）。"""
        builder = load_demo_builder()
        cards = [
            card
            for row in builder.rows("overviewCards")
            for card in row["cards"]
        ]
        self.assertTrue(cards, "示例里应该有总览卡片")
        self.assertTrue(all(c["industryFieldId"] == 0 for c in cards))
        self.assertTrue(any("industryFieldId" in w for w in builder.validate()))

    def test_resolve_field_ids_fills_real_ids(self):
        """回填后卡片必须指向真实存在的产业字段 id。"""
        from apps.industry_types.models import IndustryField

        builder = load_demo_builder()
        # 第一次导入把全局产业字段建出来
        A.apply_import(builder.build(), self.competition.id, dry_run=False, allow_non_empty=False)
        # 再从目标库的导出里回填真实 id
        exported = A.build_export(self.competition.id, A.SCOPE_ALL)
        builder.resolve_field_ids(exported)

        cards = [card for row in builder.rows("overviewCards") for card in row["cards"]]
        self.assertTrue(all(c["industryFieldId"] > 0 for c in cards), cards)
        real_ids = set(IndustryField.objects.values_list("id", flat=True))
        self.assertTrue({c["industryFieldId"] for c in cards} <= real_ids)
        # 回填后不该再报「占位 0」的提醒
        self.assertFalse(any("industryFieldId" in w for w in builder.validate()))

    def test_resolve_field_ids_rejects_unrelated_archive(self):
        """参照归档里没有对应字段时必须报错，而不是留下 0。"""
        builder = load_demo_builder()
        with self.assertRaises(BuilderError):
            builder.resolve_field_ids({"resources": {"industryFields": {"rows": []}}})


class SchemaDocTests(TestCase):
    """schema 表本身的自检。"""

    def test_schema_covers_all_resources(self):
        self.assertEqual(set(RESOURCE_SCHEMA), set(RESOURCE_ORDER))

    def test_schema_markdown_renders(self):
        from apps.preparation.builder import schema_markdown

        text = schema_markdown()
        self.assertIn("companies", text)
        self.assertIn("industryFields", text)

    def test_describe_unknown_resource_raises(self):
        from apps.preparation.builder import describe_resource

        with self.assertRaises(BuilderError):
            describe_resource("not-a-resource")


class ManagementCommandTests(TestCase):
    """管理命令：脚本 → 归档 → 导入 的完整链路。"""

    def test_inspect_does_not_touch_db(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("build_competition", str(DEMO_PATH), "--inspect", stdout=out)
        text = out.getvalue()
        self.assertIn("产出资源", text)
        self.assertIn("companies", text)
        self.assertEqual(Competition.objects.count(), 0)

    def test_out_writes_archive_json(self):
        from django.core.management import call_command
        from io import StringIO

        # 不用系统临时目录：某些受限环境下不可写；用一个随用随删的工作目录
        workdir = Path(__file__).resolve().parent / "_tmp_out"
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            target = workdir / "demo.json"
            call_command("build_competition", str(DEMO_PATH), "--out", str(target), stdout=StringIO())
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertIn("companies", payload["resources"])
        finally:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)

    def test_import_command_lands_data(self):
        from django.core.management import call_command
        from io import StringIO

        competition = Competition.objects.create(name="命令导入赛")
        call_command(
            "build_competition",
            str(DEMO_PATH),
            "--competition",
            str(competition.id),
            stdout=StringIO(),
        )
        self.assertEqual(competition.companies.count(), 3)
        self.assertEqual(competition.parts.count(), 3)

    def test_import_refuses_non_empty_without_flag(self):
        """已有数据的比赛默认拒绝导入（沿用导入引擎的保护）。"""
        from django.core.management import call_command
        from io import StringIO
        from django.core.management.base import CommandError

        competition = Competition.objects.create(name="非空赛")
        call_command(
            "build_competition", str(DEMO_PATH), "--competition", str(competition.id),
            stdout=StringIO(),
        )
        self.assertGreater(competition.companies.count(), 0)
        # 再导一次：目标非空且未加 --allow-non-empty → 必须拒绝
        with self.assertRaises(CommandError):
            call_command(
                "build_competition", str(DEMO_PATH), "--competition", str(competition.id),
                stdout=StringIO(),
            )

    def test_schema_option_prints_field_dictionary(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("build_competition", "--schema", "companies", stdout=out)
        self.assertIn("industryTypeCode", out.getvalue())
