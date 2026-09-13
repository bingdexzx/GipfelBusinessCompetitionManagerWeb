# -*- coding: utf-8 -*-
"""R-01 验证：归档导入的单资源失败必须只回滚该资源，不得「整批静默回滚却报成功」。

缺陷（改前）：`apply_import` 把全部资源放进一个 `transaction.atomic()`，逐个资源
`try: fn(rows, ctx) except Exception: 记 problem`。一旦某个资源抛的是**数据库**错误
（IntegrityError / 约束冲突），整个外层事务被标记为「需回滚」：
  - 之后每个资源的 ORM 查询都会抛 TransactionManagementError（也被逐条吞掉）；
  - 退出 atomic 时 Django 按 needs_rollback 回滚**整批**数据；
  - 而返回结果里计数器早已加过 → 接口仍报告「新增 N」，实际一行都没落库。

改后：每个资源包一层 savepoint（`with transaction.atomic()`），失败只回滚该资源，
其余资源照常提交，失败以 problem + skipped 形式如实报告。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r01_archive_import_savepoint -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.competitions.models import Competition
from apps.fuels.models import Fuel
from apps.preparation import archive
from apps.regions.models import Region
from apps.users.models import User


def _failing_importer(rows, ctx):
    """模拟「导入过程中撞上数据库约束」：第二次插入同名区域必然 IntegrityError。"""
    Region.objects.create(competition_id=ctx.competition_id, name="R01-重复区")
    Region.objects.create(competition_id=ctx.competition_id, name="R01-重复区")


class ArchiveImportSavepointTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R01-目标比赛")
        self.user = User(
            username="r01-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.user.set_password("R01Pw!123")
        self.user.save()

        self.payload = {
            "resources": {
                "regions": {"rows": [{"_id": 1, "name": "R01-重复区"}]},
                "fuels": {"rows": [{"_id": 1, "name": "R01-柴油", "pricePerLiter": "7.5000"}]},
            }
        }

    def _apply(self):
        original = archive._IMPORTERS.get("regions")
        archive._IMPORTERS["regions"] = _failing_importer
        try:
            return archive.apply_import(
                self.payload,
                self.comp.id,
                dry_run=False,
                allow_non_empty=True,
                mode="overwrite",
                user=self.user,
            )
        finally:
            if original is not None:
                archive._IMPORTERS["regions"] = original

    def test_successful_resource_is_committed_despite_other_failure(self):
        """失败的资源被回滚，但后面成功的资源必须真的落库（改前整批静默回滚）。"""
        result = self._apply()

        self.assertEqual(
            Region.objects.filter(competition=self.comp).count(), 0,
            "失败资源的写入必须回滚（savepoint）",
        )
        self.assertEqual(
            Fuel.objects.filter(competition=self.comp).count(), 1,
            f"其余资源必须照常提交，实际燃料 {Fuel.objects.filter(competition=self.comp).count()} 条"
            "（改前为 0：整批被静默回滚）",
        )

        rows = {r["resource"]: r for r in result.get("resources", [])}
        self.assertEqual(rows.get("fuels", {}).get("created"), 1, "统计应与落库结果一致")

    def test_failure_is_reported_in_problems(self):
        """失败必须出现在 problems 里（不能只体现在「新增 N」的成功统计中）。"""
        result = self._apply()
        problems = result.get("problems") or []
        self.assertTrue(
            any("区域" in p and "导入失败" in p for p in problems),
            f"problems 应包含区域导入失败，实际 {problems}",
        )
        rows = {r["resource"]: r for r in result.get("resources", [])}
        self.assertGreaterEqual(rows.get("regions", {}).get("skipped", 0), 1)

    def test_dry_run_still_rolls_back_everything(self):
        """回归：dry_run 仍必须一行都不落库。"""
        original = archive._IMPORTERS.get("regions")

        def ok_importer(rows, ctx):
            Region.objects.create(competition_id=ctx.competition_id, name="R01-预演区")

        archive._IMPORTERS["regions"] = ok_importer
        try:
            result = archive.apply_import(
                self.payload,
                self.comp.id,
                dry_run=True,
                allow_non_empty=True,
                mode="overwrite",
                user=self.user,
            )
        finally:
            if original is not None:
                archive._IMPORTERS["regions"] = original

        self.assertTrue(result.get("dryRun"))
        self.assertEqual(Region.objects.filter(competition=self.comp).count(), 0)
        self.assertEqual(Fuel.objects.filter(competition=self.comp).count(), 0)
