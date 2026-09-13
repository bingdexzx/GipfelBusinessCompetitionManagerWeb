# -*- coding: utf-8 -*-
"""R-13 / R-14 验证：消费者需求去重键、`/preparations/plan` 的明细上限。

R-13（`archive.py::_imp_consumer_demands`）改前：自然键是「比赛 + 区域 + 产品类型 + **数量**」，
而模型对 (competition, region, product_type) 没有唯一约束。源比赛把某区域某产品的需求量从
100 改成 150 后重新导入，会**新建**一条而不是更新既有行 ⇒ 同区域同产品出现两条需求
（100 与 150），订单/需求总量被放大；overwrite 模式也一样（去重键不随 mode 变化）。

R-14（`plan.py::_detail`）改前：模块级 `_DETAIL_LIMIT = 200` 只有定义、**从未被引用** ——
`rows` 原样全量返回，`total == len(rows)` 恒成立，前端 `isTruncated()` 永远 false，
「仅显示前 N 条」分支是死代码；明细表按记录数增长，响应体无界，几千行的 el-table 会卡死。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r13_r14_demands_plan
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.competitions.models import Competition
from apps.consumer_demands.models import ConsumerDemand
from apps.preparation import archive, plan
from apps.users.models import User


def _admin(comp, username: str) -> User:
    user = User(
        username=username,
        role="SUPER_ADMIN",
        is_active=True,
        competition=comp,
        permissions=json.dumps([]),
    )
    user.set_password("R13Pw!123")
    user.save()
    return user


class R13ConsumerDemandTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R13-目标比赛")
        self.admin = _admin(self.comp, "r13-admin")

    def _import(self, rows: list[dict]):
        payload = {
            "schemaVersion": archive.SCHEMA_VERSION,
            "scope": archive.SCOPE_ALL,
            "resources": {"consumerDemands": {"count": len(rows), "rows": rows}},
        }
        return archive.apply_import(
            payload, self.comp.id, dry_run=False, allow_non_empty=True, user=self.admin
        )

    def test_changed_quantity_updates_instead_of_appending(self):
        """改前：数量从 100 改 150 会追加出第二条需求（100 与 150 并存）。"""
        self._import([{"_id": 1, "region": "北区", "productType": "整车", "quantity": 100}])
        self._import([{"_id": 1, "region": "北区", "productType": "整车", "quantity": 150}])

        rows = list(
            ConsumerDemand.objects.filter(competition=self.comp, region="北区")
            .values_list("product_type", "quantity")
        )
        self.assertEqual(
            rows, [("整车", 150)],
            f"同一 (区域, 产品类型) 只能有一条需求且数量被更新，实际 {rows}",
        )

    def test_same_quantity_is_skipped(self):
        """回归：数量一致时不重复追加、也不产生多余更新。"""
        self._import([{"_id": 1, "region": "南区", "productType": "零件", "quantity": 20}])
        result = self._import(
            [{"_id": 1, "region": "南区", "productType": "零件", "quantity": 20}]
        )
        self.assertEqual(ConsumerDemand.objects.filter(competition=self.comp).count(), 1)
        by_res = {r["resource"]: r for r in result["resources"]}
        self.assertEqual(by_res["consumerDemands"]["created"], 0, f"不应新增，实际 {by_res}")
        self.assertEqual(by_res["consumerDemands"]["skipped"], 1, f"应记为 skipped，实际 {by_res}")

    def test_note_update_is_applied(self):
        """去重命中时 note 也要按归档更新（改前只回填 product_id）。"""
        self._import(
            [{"_id": 1, "region": "东区", "productType": "整车", "quantity": 5, "note": "旧"}]
        )
        self._import(
            [{"_id": 1, "region": "东区", "productType": "整车", "quantity": 5, "note": "新"}]
        )
        obj = ConsumerDemand.objects.get(competition=self.comp, region="东区")
        self.assertEqual(obj.note, "新")

    def test_different_product_type_still_separate(self):
        """回归：不同产品类型仍是两条独立需求。"""
        self._import(
            [
                {"_id": 1, "region": "西区", "productType": "整车", "quantity": 1},
                {"_id": 2, "region": "西区", "productType": "零件", "quantity": 2},
            ]
        )
        self.assertEqual(ConsumerDemand.objects.filter(competition=self.comp).count(), 2)

    def test_existing_duplicates_are_collapsed_on_reimport(self):
        """历史脏数据（同键两条）在再次导入时收敛为一条（不新增第三条）。"""
        ConsumerDemand.objects.create(
            competition=self.comp, region="中区", product_type="整车", quantity=100
        )
        ConsumerDemand.objects.create(
            competition=self.comp, region="中区", product_type="整车", quantity=150
        )
        self._import([{"_id": 1, "region": "中区", "productType": "整车", "quantity": 200}])
        rows = list(
            ConsumerDemand.objects.filter(competition=self.comp, region="中区")
            .order_by("id")
            .values_list("quantity", flat=True)
        )
        self.assertEqual(rows[0], 200, "应更新最早那条")
        self.assertEqual(len(rows), 2, "既有重复行不会被自动删除（不越权清理），但不得再新增")


class R14PlanDetailLimitTests(TestCase):
    def test_detail_truncates_and_keeps_total(self):
        """`_detail()` 必须真正应用上限：rows 截断、total 记全量。"""
        rows = [[f"第{i}行"] for i in range(plan._DETAIL_LIMIT + 7)]
        block = plan._detail("测试表", ["列"], rows)
        self.assertEqual(
            len(block["rows"]), plan._DETAIL_LIMIT,
            f"rows 必须截断到 {plan._DETAIL_LIMIT} 条，实际 {len(block['rows'])}",
        )
        self.assertEqual(block["total"], plan._DETAIL_LIMIT + 7, "total 必须保留全量条数")

    def test_detail_within_limit_is_untouched(self):
        """回归：未超限的明细原样返回。"""
        rows = [["a"], ["b"]]
        block = plan._detail("测试表", ["列"], rows)
        self.assertEqual(block["rows"], rows)
        self.assertEqual(block["total"], 2)

    def test_plan_limit_constant_is_used(self):
        """`_DETAIL_LIMIT` 必须真的被引用（改前全仓 grep 只有定义）。"""
        import inspect

        source = inspect.getsource(plan._detail)
        self.assertIn("_DETAIL_LIMIT", source, "`_detail` 必须引用 `_DETAIL_LIMIT`")

    def test_markdown_export_mentions_remaining_rows(self):
        """Markdown 导出也要说明「还有 N 条」（否则用户以为明细就是全部）。"""
        import inspect

        source = inspect.getsource(plan)
        self.assertIn(
            "仅列出前", source,
            "Markdown 导出应对被截断的明细给出「仅列出前 N 条，共 M 条」提示",
        )
