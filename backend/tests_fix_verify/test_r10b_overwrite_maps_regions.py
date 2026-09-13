# -*- coding: utf-8 -*-
"""R-10（余项）验证：覆盖模式必须更新地图节点与区域说明。

缺陷（改前）：与股票/资金账户同类 —— `_imp_map_nodes` 与 `_imp_regions` 在「已存在」时永远走
skipped：
  - 地图节点：坐标 x/y、所属区域、节点类型不会被刷新（用户选「覆盖」是期待把源比赛的地图布局
    刷过来，实际坐标保持旧值）；
  - 区域：`regions.description` 永远不更新。

改后：覆盖模式下按归档更新这些字段并记 `updated`；追加模式仍整条保留（行为不变）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r10b_overwrite_maps_regions -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.competitions.models import Competition
from apps.maps.models import MapNode, MapNodeType
from apps.preparation import archive
from apps.regions.models import Region
from apps.users.models import User


class OverwriteMapRegionTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R10b-目标比赛")
        self.admin = User(
            username="r10b-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R10bPw!123")
        self.admin.save()

        self.node_type = MapNodeType.objects.create(competition=self.comp, name="R10b类型")
        self.node = MapNode.objects.create(
            competition=self.comp, name="R10b节点", node_type=self.node_type,
            region="旧区域", x=1, y=2,
        )
        self.region = Region.objects.create(
            competition=self.comp, name="R10b区", description="旧说明"
        )

    def _payload(self):
        return {
            "resources": {
                "regions": {
                    "rows": [{"_id": 1, "name": "R10b区", "description": "归档里的新说明"}]
                },
                "mapNodes": {
                    "rows": [
                        {
                            "_id": 1,
                            "name": "R10b节点",
                            "nodeTypeName": "R10b类型",
                            "region": "新区域",
                            "x": "120",
                            "y": "80",
                        }
                    ]
                },
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

    def test_overwrite_updates_node_and_region(self):
        result = self._import("overwrite")
        self.node.refresh_from_db()
        self.region.refresh_from_db()

        self.assertEqual((self.node.x, self.node.y), (120, 80), "覆盖模式应更新节点坐标")
        self.assertEqual(self.node.region, "新区域", "覆盖模式应更新节点所属区域")
        self.assertEqual(self.region.description, "归档里的新说明", "覆盖模式应更新区域说明")

        rows = {r["resource"]: r for r in result["resources"]}
        self.assertEqual(rows.get("mapNodes", {}).get("updated"), 1, f"{rows.get('mapNodes')}")
        self.assertEqual(rows.get("regions", {}).get("updated"), 1, f"{rows.get('regions')}")

    def test_append_mode_keeps_existing_values(self):
        """回归：追加模式不得改动节点坐标与区域说明。"""
        self._import("append")
        self.node.refresh_from_db()
        self.region.refresh_from_db()
        self.assertEqual((self.node.x, self.node.y), (1, 2))
        self.assertEqual(self.node.region, "旧区域")
        self.assertEqual(self.region.description, "旧说明")
