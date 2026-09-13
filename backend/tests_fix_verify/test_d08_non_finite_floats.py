# -*- coding: utf-8 -*-
"""D-08 验证：非有限浮点（inf/nan）不得入库，也不得让模块读接口持续 500。

缺陷（改前，实测）：
- maps / tech_tree 的 FloatField 无有限性校验，DRF 的 `float("inf")` 解析会把
  `"inf"`/`"nan"`/`"1e400"` 全部判为合法；
- 落库后出站渲染走 `apps/common/renderers.py`（float 分支无 is_finite 守卫），
  DRF JSONRenderer 以 allow_nan=False 渲染 → ValueError: Out of range float values
  are not JSON compliant → 该比赛的地图/科技树读接口（含 /api/maps/full）持续 500，
  写一行 `"x": "inf"` 即可持久打挂整个模块。

改后：
- 序列化层拒绝非有限值（400）；
- 渲染层把非有限浮点兜底为 null（历史脏数据不再打挂接口）。
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.common.renderers import _convert_big_numbers
from apps.common.response import JSONRenderer
from apps.competitions.models import Competition
from apps.maps.models import MapNode, MapNodeType, PathType
from apps.maps.serializers import MapEdgeSerializer, MapNodeSerializer
from apps.tech_tree.serializers import TechNodeSerializer


class NonFiniteFloatTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="D08 非有限浮点")
        self.node_type = MapNodeType.objects.create(competition=self.comp, name="城市")

    # ---------- 缺陷场景：序列化层必须拒绝 ----------
    def test_map_node_rejects_inf_nan_and_overflow(self):
        for raw in ("inf", "-inf", "nan", "Infinity", "1e400", float("inf"), float("nan")):
            with self.subTest(value=raw):
                s = MapNodeSerializer(
                    data={
                        "name": "节点",
                        "nodeTypeId": self.node_type.id,
                        "competitionId": self.comp.id,
                        "x": raw,
                        "y": 0,
                    }
                )
                self.assertFalse(s.is_valid(), f"{raw!r} 不应通过校验")
                self.assertIn("x", s.errors)

    def test_map_edge_rejects_nan_distance(self):
        s = MapEdgeSerializer(
            data={
                "fromNodeId": 1,
                "toNodeId": 2,
                "distance": "nan",
                "pathTypeId": 1,
                "competitionId": self.comp.id,
            }
        )
        self.assertFalse(s.is_valid())
        self.assertIn("distance", s.errors)

    def test_tech_node_rejects_non_finite(self):
        for field, raw in (("tier", "inf"), ("researchCost", "1e400"), ("researchCost", "nan")):
            with self.subTest(field=field, value=raw):
                payload = {"name": "科技", "competitionId": self.comp.id, "tier": 1, "researchCost": 1}
                payload[field] = raw
                s = TechNodeSerializer(data=payload)
                self.assertFalse(s.is_valid(), f"{field}={raw!r} 不应通过校验")
                self.assertIn(field, s.errors)

    # ---------- 缺陷场景：历史脏数据不得让接口 500 ----------
    def test_renderer_tolerates_non_finite_floats(self):
        self.assertIsNone(_convert_big_numbers(float("inf")))
        self.assertIsNone(_convert_big_numbers(float("-inf")))
        self.assertIsNone(_convert_big_numbers(float("nan")))
        out = JSONRenderer().render(
            {"code": 0, "message": "成功", "data": {"x": float("inf"), "ok": 1.5}}
        )
        payload = json.loads(out)
        self.assertIsNone(payload["data"]["x"])
        self.assertEqual(payload["data"]["ok"], 1.5)

    def test_legacy_inf_row_no_longer_500s(self):
        """直接写入 inf（绕过序列化层）后，列表接口的渲染不再抛 ValueError。

        注：NaN 在 SQLite 落库为 NULL（NOT NULL 约束会报错），故历史脏数据用 inf 复现；
        NaN 的渲染兜底由 test_renderer_tolerates_non_finite_floats 覆盖。
        """
        node = MapNode.objects.create(
            competition=self.comp, name="脏节点", node_type=self.node_type,
            region="", x=float("inf"), y=float("-inf"),
        )
        data = MapNodeSerializer(node).data
        rendered = JSONRenderer().render({"code": 0, "message": "成功", "data": [data]})
        payload = json.loads(rendered)
        self.assertIsNone(payload["data"][0]["x"])
        self.assertIsNone(payload["data"][0]["y"])

    # ---------- 功能不变 ----------
    def test_normal_map_node_values_unchanged(self):
        s = MapNodeSerializer(
            data={
                "name": "节点", "nodeTypeId": self.node_type.id,
                "competitionId": self.comp.id, "x": "12.5", "y": 3,
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["x"], 12.5)
        self.assertEqual(s.validated_data["y"], 3.0)

    def test_normal_map_edge_values_unchanged(self):
        for distance in (0, 100, "3.25", None):
            payload = {
                "fromNodeId": 1, "toNodeId": 2, "pathTypeId": 1,
                "competitionId": self.comp.id,
            }
            if distance is not None:
                payload["distance"] = distance
            s = MapEdgeSerializer(data=payload)
            self.assertTrue(s.is_valid(), s.errors)

    def test_normal_tech_node_values_unchanged(self):
        s = TechNodeSerializer(
            data={
                "name": "科技", "competitionId": self.comp.id,
                "tier": 2, "researchCost": "5000",
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["tier"], 2.0)
        self.assertEqual(s.validated_data["researchCost"], 5000.0)

    def test_renderer_keeps_normal_numbers(self):
        self.assertEqual(_convert_big_numbers(1.5), 1.5)
        self.assertEqual(_convert_big_numbers(7), 7)
        self.assertEqual(_convert_big_numbers(10**20), str(10**20))
        self.assertEqual(_convert_big_numbers([1, {"a": 2.5}]), [1, {"a": 2.5}])
