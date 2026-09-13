# -*- coding: utf-8 -*-
"""R-11 / R-12 验证：归档截断必须可见，「非空比赛」判定探针必须补全。

R-11（`archive.py`）改前：导出把明细静默截断到 `_DETAIL_LIMIT`（2000）行，`count` 却是全量；
导入侧 `validate_archive` 不校验 `count` 与 `rows` 是否一致，直接按 rows 导入，既不报 problem
也不提示被截断。前端归档条数列显示 count（3000），实际只导入 2000 —— 用户以为全量搬运完成。

R-12（`archive.py`）改前：`_NON_EMPTY_PROBES` 漏了「比赛内消息、财年、节点类型、路径类型、
地图连线」等比赛级模型 —— 一个只含这些数据的比赛会被判为「空比赛」，导入时**跳过
allowNonEmpty 保护**直接写入（dryRun 预览还显示 blocked=false，前端不会提示风险）。

改后：
- 导出侧超限时写 `truncated: true` / `dropped: n`；新增 `truncated_resources()`；
  导入接口在结果里插入 problem 与 `truncatedResources`；
- 探针补全上述模型，并为没有 competition 外键的 `TechPrerequisite` 增加按科技节点过滤的间接探针。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r11_r12_archive_limits
"""
from __future__ import annotations

import json
from unittest import mock

from django.test import TestCase

from apps.competitions.models import Competition, FiscalYear
from apps.maps.models import MapEdge, MapNode, MapNodeType, PathType
from apps.messages.models import Message  # app label 为 gipfel_messages，模块路径仍是 apps.messages
from apps.preparation import archive
from apps.users.models import User


def _admin(comp, username: str) -> User:
    user = User(
        username=username,
        role="SUPER_ADMIN",
        is_active=True,
        competition=comp,
        permissions=json.dumps([]),
    )
    user.set_password("R11Pw!123")
    user.save()
    return user


class R11TruncationTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R11-源比赛")

    def test_export_marks_truncated_resource(self):
        """导出侧：超过上限时必须写 truncated/dropped（改前静默截断）。"""
        rows = [{"_id": i, "name": f"R11-{i}"} for i in range(archive._DETAIL_LIMIT + 5)]

        # mock 让「区域」资源返回超额行，走同一段导出逻辑（其余资源不受影响）
        with mock.patch.dict(
            archive._EXPORTERS, {"regions": lambda _cid: rows}, clear=False
        ):
            payload = archive.build_export(self.comp.id, scope=archive.SCOPE_ALL)
        block = payload["resources"]["regions"]
        self.assertEqual(block["count"], archive._DETAIL_LIMIT + 5)
        self.assertEqual(len(block["rows"]), archive._DETAIL_LIMIT)
        self.assertTrue(block.get("truncated"), f"必须标记截断，实际 {block.keys()}")
        self.assertEqual(block.get("dropped"), 5)

    def test_small_resource_is_not_marked(self):
        """回归：未超限的资源不得出现 truncated 字段。"""
        with mock.patch.dict(
            archive._EXPORTERS, {"regions": lambda _cid: [{"_id": 1, "name": "R11-小区"}]},
            clear=False,
        ):
            payload = archive.build_export(self.comp.id, scope=archive.SCOPE_ALL)
        block = payload["resources"]["regions"]
        self.assertNotIn("truncated", block)
        self.assertNotIn("dropped", block)
        self.assertEqual(block["count"], 1)

    def test_truncated_resources_helper(self):
        payload = {
            "resources": {
                "regions": {"count": 3000, "rows": [1, 2], "truncated": True, "dropped": 2998},
                "fuels": {"count": 1, "rows": [1]},
                "parts": {"count": 2500, "rows": [1, 2], "truncated": True},
            }
        }
        got = archive.truncated_resources(payload)
        self.assertEqual(
            [(name, total, dropped) for name, total, dropped in got],
            [("regions", 3000, 2998), ("parts", 2500, 2498)],
            "应列出被截断资源；未写 dropped 时按 count - len(rows) 推算",
        )
        self.assertEqual(archive.truncated_resources({}), [])
        self.assertEqual(archive.truncated_resources(None), [])

    def test_import_reports_truncation(self):
        """导入侧：归档被截断时必须给出 problem（改前静默按残缺 rows 导入）。"""
        target = Competition.objects.create(name="R11-目标比赛")
        admin = _admin(target, "r11-admin")
        payload = {
            "schemaVersion": archive.SCHEMA_VERSION,
            "scope": archive.SCOPE_ALL,
            "resources": {
                "regions": {
                    "count": 10, "rows": [{"_id": 1, "name": "R11-截断区"}],
                    "truncated": True, "dropped": 9,
                },
            },
        }
        result = archive.apply_import(
            payload, target.id, dry_run=True, allow_non_empty=True, user=admin
        )
        joined = " ".join(result.get("problems") or [])
        self.assertIn("截断", joined, f"必须提示归档不完整，实际 problems={result.get('problems')}")
        self.assertIn("2000", joined, "提示里应说明截断上限")
        self.assertEqual(
            result.get("truncatedResources"),
            [{"resource": "regions", "count": 10, "dropped": 9}],
        )

    def test_import_without_truncation_has_no_notice(self):
        """回归：未截断的归档不得出现该提示。"""
        target = Competition.objects.create(name="R11-目标比赛2")
        admin = _admin(target, "r11-admin2")
        payload = {
            "schemaVersion": archive.SCHEMA_VERSION,
            "scope": archive.SCOPE_ALL,
            "resources": {"regions": {"count": 1, "rows": [{"_id": 1, "name": "R11-正常区"}]}},
        }
        result = archive.apply_import(
            payload, target.id, dry_run=True, allow_non_empty=True, user=admin
        )
        self.assertFalse(result.get("truncatedResources"))
        self.assertNotIn("截断", " ".join(result.get("problems") or []))


class R12NonEmptyProbeTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R12-目标比赛")

    def _labels(self) -> set[str]:
        return {label for label, _n in archive.competition_occupancy(self.comp.id)}

    def test_only_message_data_is_detected(self):
        """只有「比赛内消息」的比赛必须被判为非空（改前漏检 ⇒ 绕过 allowNonEmpty 保护）。"""
        sender = _admin(self.comp, "r12-msg-sender")
        Message.objects.create(
            competition=self.comp, sender=sender, title="R12-通知", content="内容"
        )
        self.assertIn(
            "比赛内消息", self._labels(),
            f"比赛内消息必须被计入占用，实际 {self._labels()}",
        )

    def test_only_fiscal_year_is_detected(self):
        FiscalYear.objects.create(competition=self.comp, year=2026)
        self.assertIn("财年", self._labels(), f"财年必须被计入占用，实际 {self._labels()}")

    def test_only_node_type_and_path_type_are_detected(self):
        MapNodeType.objects.create(competition=self.comp, name="R12-节点类型")
        self.assertIn("地图节点类型", self._labels(), f"实际 {self._labels()}")
        PathType.objects.create(competition=self.comp, name="R12-路径类型")
        self.assertIn("路径类型", self._labels(), f"实际 {self._labels()}")

    def test_only_map_edge_is_detected(self):
        nt = MapNodeType.objects.create(competition=self.comp, name="R12-类型")
        pt = PathType.objects.create(competition=self.comp, name="R12-路径")
        a = MapNode.objects.create(competition=self.comp, name="R12-A", node_type=nt)
        b = MapNode.objects.create(competition=self.comp, name="R12-B", node_type=nt)
        MapEdge.objects.create(competition=self.comp, from_node=a, to_node=b, path_type=pt)
        labels = self._labels()
        self.assertIn("地图连线", labels, f"地图连线必须被计入占用，实际 {labels}")

    def test_empty_competition_still_empty(self):
        """回归：真正空的比赛必须仍被判为空（否则导入会被无谓拦住）。"""
        self.assertEqual(self._labels(), set())

    def test_import_blocked_for_message_only_competition(self):
        """端到端：只有消息的比赛 + 未开 allowNonEmpty ⇒ 必须 blocked。"""
        admin = _admin(self.comp, "r12-admin")
        Message.objects.create(
            competition=self.comp, sender=admin, title="R12-通知2", content="内容"
        )
        payload = {
            "schemaVersion": archive.SCHEMA_VERSION,
            "scope": archive.SCOPE_ALL,
            "resources": {"regions": {"count": 1, "rows": [{"_id": 1, "name": "R12-区"}]}},
        }
        result = archive.apply_import(
            payload, self.comp.id, dry_run=True, allow_non_empty=False, user=admin
        )
        self.assertTrue(
            result.get("blocked"),
            f"只有消息的比赛也必须被拦住（改前判为空 ⇒ blocked=false），实际 {result}",
        )
