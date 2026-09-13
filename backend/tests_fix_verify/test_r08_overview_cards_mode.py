# -*- coding: utf-8 -*-
"""R-08 验证：追加模式不得覆盖既有区域的概览卡片配置。

缺陷（改前）：`_imp_overview_cards` 对已存在的区域**无条件**回写 `overview_cards`：
  - 追加模式（默认）下，目标比赛里已经人工配好的概览卡片被归档内容整份替换（卡片里的
    companyId 还会按本次导入重新映射，映射不到的直接丢弃）；
  - 而 `_CHILD_OF["overviewCards"] = (("regions", "regionId"),)` 这条「父被保留就跳过」的
    保护规则永远不会生效 —— 导出侧的行里根本没有 `regionId` 字段（用的是 `regionName`），
    所以它是一条死规则。

改后：追加模式下已存在的区域保留原卡片并记 note；覆盖模式才按归档写回。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r08_overview_cards_mode -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.competitions.models import Competition
from apps.preparation import archive
from apps.regions.models import Region
from apps.users.models import User


class OverviewCardsModeTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R08-目标比赛")
        self.admin = User(
            username="r08-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R08Pw!123")
        self.admin.save()
        self.region = Region.objects.create(
            competition=self.comp,
            name="R08区",
            overview_cards=json.dumps([{"id": "card-1", "displayName": "人工配置的卡片"}]),
        )

    def _payload(self):
        return {
            "resources": {
                "overviewCards": {
                    "rows": [
                        {
                            "_id": 1,
                            "regionName": "R08区",
                            "cards": [{"id": "card-2", "displayName": "归档里的卡片"}],
                        }
                    ]
                }
            }
        }

    def _import(self, mode):
        return archive.apply_import(
            self._payload(),
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode=mode,
            user=self.admin,
        )

    def test_append_mode_keeps_existing_cards(self):
        result = self._import("append")
        self.region.refresh_from_db()
        cards = json.loads(self.region.overview_cards)

        self.assertEqual(
            [c["displayName"] for c in cards], ["人工配置的卡片"],
            "追加模式不得替换既有区域的概览卡片（改前会被归档内容覆盖）",
        )
        rows = {r["resource"]: r for r in result["resources"]}
        self.assertEqual(rows.get("overviewCards", {}).get("kept"), 1)
        self.assertTrue(
            any("保留原有配置" in n for n in (result.get("notes") or [])),
            f"应给出保留提示：{result.get('notes')}",
        )

    def test_overwrite_mode_replaces_cards(self):
        self._import("overwrite")
        self.region.refresh_from_db()
        cards = json.loads(self.region.overview_cards)
        self.assertEqual(
            [c["displayName"] for c in cards], ["归档里的卡片"],
            "覆盖模式应按归档写回卡片",
        )

    def test_new_region_gets_cards_in_both_modes(self):
        payload = self._payload()
        payload["resources"]["overviewCards"]["rows"][0]["regionName"] = "R08新区"
        archive.apply_import(
            payload,
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode="append",
            user=self.admin,
        )
        region = Region.objects.get(competition=self.comp, name="R08新区")
        self.assertEqual(
            [c["displayName"] for c in json.loads(region.overview_cards)], ["归档里的卡片"],
            "新区域在追加模式下也应写入卡片",
        )
