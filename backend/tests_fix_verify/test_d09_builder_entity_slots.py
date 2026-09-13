# -*- coding: utf-8 -*-
"""D-09 验证：合同类型建库器重复 `build()` 不得丢实体槽位。

缺陷（改前）：快照的实体槽位由一次性队列承载 —— `pin()` 把槽位登记进
`_pinned_inputs`，`drain_pinned_inputs()` 取一次就清空，而 `_pinned`（entity_id → 槽位名）
仍保留。于是同一个构建器实例第二次 `build()` 时 `pin()` 命中缓存直接返回旧槽位名、
不再登记输入项 → 产物 `inputSchema` 缺少 `__ref_*`，而 effects 仍引用它 →
引擎执行时实体引用取不到 id，**所有实体引用静默按 0 计算**。

CLI 路径 100% 命中：`builder/__init__.py:261` 的 `check()` 内部先 `ct.build()`，
`build_contract_types --import` 再 `ct.build()` 一次。
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.common.exceptions import BusinessError
from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.contracts.builder import ContractType, check as static_check, number, snapshot
from apps.industry_types.models import IndustryField, IndustryType
from apps.materials.models import Material
from apps.regions.models import Region


def _collect_entity_refs(node, out: list[str]) -> list[str]:
    """递归收集产物里出现的 entityRef（effects/conditions 任意嵌套）。"""
    if isinstance(node, dict):
        if node.get("type") == "ENTITY" and node.get("entityRef"):
            out.append(str(node["entityRef"]))
        for v in node.values():
            _collect_entity_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_entity_refs(v, out)
    return out


class EntitySlotPersistenceTests(TestCase):
    def setUp(self):
        from apps.maps.models import MapNode, MapNodeType

        self.comp = Competition.objects.create(name="D09 实体槽位")
        self.region = Region.objects.create(competition=self.comp, name="东区")
        self.industry = IndustryType.objects.create(code=9401, name="D09产业")
        self.cash_field = IndustryField.objects.create(
            industry_type=self.industry, name="现金", field_key="cash", field_type="NUMBER"
        )
        self.seller = Company.objects.create(
            competition=self.comp, name="卖方公司", industry_type=self.industry, region=self.region
        )
        CompanyFieldValue.objects.create(
            company=self.seller, industry_field=self.cash_field, value="1000"
        )
        self.material = Material.objects.create(
            competition=self.comp, name="铁矿石", origin="东区",
            carbon_emission_coefficient=0.5, node_prices=json.dumps({}),
        )
        node_type = MapNodeType.objects.create(competition=self.comp, name="城市")
        MapNode.objects.create(
            competition=self.comp, region="东区", name="东区港", node_type=node_type, x=1, y=1
        )
        self.snap = snapshot(self.comp.id)

    def _make_entity_type(self) -> ContractType:
        ct = ContractType("d09-entity", "D09 实体引用合同")
        seller = ct.party("seller", "卖方")
        ct.use_snapshot(self.snap)
        mat = self.snap.material("铁矿石")
        ct.add_number(seller.field("cash"), mat.attr("carbonEmissionCoefficient"))
        return ct

    # ---------- 缺陷场景 ----------
    def test_entity_slots_survive_repeated_build(self):
        ct = self._make_entity_type()
        p1 = ct.build()
        p2 = ct.build()

        refs = _collect_entity_refs(p1["effects"], [])
        self.assertTrue(refs, "本用例必须产出至少一个实体引用槽位")
        keys1 = {i["key"] for i in p1["inputSchema"]}
        keys2 = {i["key"] for i in p2["inputSchema"]}
        for ref in refs:
            self.assertIn(ref, keys1, "第一次 build 的 inputSchema 必须包含实体槽位")
            self.assertIn(ref, keys2, "第二次 build 的 inputSchema 必须包含实体槽位（改前会丢）")
        self.assertEqual(p1, p2, "同一构建器重复 build 的产物必须一致")

    def test_static_check_then_build_keeps_entity_slots(self):
        """CLI 路径：check() 内部先 build 一次，随后 build 的产物仍须带槽位。"""
        ct = self._make_entity_type()
        static_check(ct, snap=self.snap)
        payload = ct.build()
        refs = _collect_entity_refs(payload["effects"], [])
        keys = {i["key"] for i in payload["inputSchema"]}
        for ref in refs:
            self.assertIn(ref, keys, "check() 之后 build 的产物缺少实体槽位（改前会丢）")

    def test_payload_after_two_builds_is_importable_shape(self):
        """两次 build 后槽位仍在，且槽位形态仍是引擎可消费的隐藏 ENTITY 输入项。"""
        ct = self._make_entity_type()
        ct.build()
        payload = ct.payload()
        slot = next(
            (i for i in payload["inputSchema"] if str(i["key"]).startswith("__ref_")), None
        )
        self.assertIsNotNone(slot, "隐藏实体槽位必须存在")
        self.assertEqual(slot["type"], "ENTITY")
        self.assertTrue(slot.get("hidden"))
        self.assertEqual(slot["default"], self.material.id)

    # ---------- 功能不变 ----------
    def test_type_without_entity_refs_unaffected(self):
        ct = ContractType("d09-plain", "无实体引用合同")
        p = ct.party("seller", "卖方")
        ct.add_number(p.field("cash"), number("7"))
        p1 = ct.build()
        p2 = ct.build()
        self.assertEqual(p1, p2)
        self.assertFalse([i for i in p1["inputSchema"] if str(i["key"]).startswith("__ref_")])

    def test_multiple_builds_do_not_duplicate_slots(self):
        ct = self._make_entity_type()
        for _ in range(3):
            payload = ct.build()
        refs = [i["key"] for i in payload["inputSchema"] if str(i["key"]).startswith("__ref_")]
        self.assertEqual(len(refs), len(set(refs)), "槽位不得重复登记")

    def test_same_entity_pinned_twice_yields_single_slot(self):
        ct = ContractType("d09-twice", "同实体两次引用")
        seller = ct.party("seller", "卖方")
        ct.use_snapshot(self.snap)
        mat = self.snap.material("铁矿石")
        ct.add_number(seller.field("cash"), mat.attr("carbonEmissionCoefficient"))
        ct.add_number(seller.field("cash"), mat.attr("carbonEmissionCoefficient"))
        payload = ct.build()
        ct.build()
        payload2 = ct.build()
        keys = [i["key"] for i in payload2["inputSchema"] if str(i["key"]).startswith("__ref_")]
        self.assertEqual(len(keys), 1, "同一实体的槽位只应有一个")
        self.assertEqual(payload["inputSchema"], payload2["inputSchema"])
