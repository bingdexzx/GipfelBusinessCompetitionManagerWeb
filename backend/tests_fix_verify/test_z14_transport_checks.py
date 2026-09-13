# -*- coding: utf-8 -*-
"""Z-14 验证：运输合同模板的输入校验缺口（负车次可反向转账 / 超重分支不可复现）。

缺陷（改前，`backend/examples/contracts/auto_chain_contracts.py:226-245`）：
1. `trips`（车次）与 `carbon_tax_rate`（碳税税率）是 `number` 型输入但**没有任何下界检查**
   （同文件只校验了 `rate_per_km >= 0`、`cargo_weight >= 0`）。玩家把「车次」填成 `-100`：
   `freight = distance * rate_per_km * trips + fuel_cost` 变负 ⇒
   `ct.sub_number(client.cash, 负值)` 给委托方**加钱**、`ct.add_number(carrier.cash, 负值)`
   给承运方**扣钱**；`ct.check(client.field(cash) >= freight + carbon_tax)` 也拦不住
   （负数恒小于现金）。碳税税率填负数则把碳税变成"补贴"。
2. 文档 `docs/汽车产业链测试赛准备.md:55` 把「超重 +10%」列为该合同主要效果，但预置实例
   `cargo_weight: 20` + 冒烟补的 `{"重型卡车": 2}`（单车 `maxCargo=30` ⇒ 合计 60）永远
   不触发 `cargo_weight > capacity`；`:126` 的参考金额 6,858 也正是"未超重"的结果 ——
   即文档展示的效果在当前预置数据下无法观察到。

改后：
1. 新增 `ct.check(trips >= 0, …)` 与 `ct.check(carbon_tax_rate >= 0, …)`；
2. 冒烟脚本把货重默认值提到 70 吨（> 60 吨合计载重）以真正跑到超重分支，
   文档同步补一行该分支的期望金额。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests_fix_verify\\test_z14_transport_checks.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import django
from django.test import TestCase

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "examples"))
sys.path.insert(0, str(BACKEND / "examples" / "contracts"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from examples.contracts import auto_chain_contracts as acc  # noqa: E402


def _transport_type():
    return acc.transport_contract()


def _checks_by_label(ct) -> dict:
    """{检查项标签: 序列化后的检查 spec}。"""
    out = {}
    for chk in ct._checks:
        spec = chk.to_spec() if hasattr(chk, "to_spec") else (chk.spec or {})
        out[spec.get("label") or spec.get("errorMessage") or "?"] = spec
    return out


class Z14TransportCheckTests(TestCase):
    def test_trips_and_carbon_tax_have_lower_bounds(self):
        """`trips` / `carbon_tax_rate` 必须各有下界检查（改前完全没有）。"""
        checks = _checks_by_label(_transport_type())
        labels = " ".join(checks.keys())
        self.assertIn(
            "车次", labels,
            f"必须有「车次」下界检查（改前没有，负车次会把运费算成反向转账）；实际 {sorted(checks)}",
        )
        self.assertIn(
            "碳税税率", labels,
            f"必须有「碳税税率」下界检查（改前没有）；实际 {sorted(checks)}",
        )
        for label, key in (("车次校验", "trips"), ("碳税税率校验", "carbon_tax_rate")):
            spec = checks.get(label)
            self.assertIsNotNone(spec, f"缺少检查 {label}")
            self.assertEqual(spec["kind"], "VALUE_COMPARE")
            self.assertEqual(spec["op"], "GTE", f"{label} 必须是「>= 0」")
            self.assertEqual(spec["value1"], {"type": "INPUT", "key": key})
            self.assertEqual(spec["value2"]["value"], "0")

    def test_existing_bounds_are_kept(self):
        """回归：原有的运价/货重下界与运费校验不得丢失。"""
        labels = " ".join(_checks_by_label(_transport_type()).keys())
        for must in ("运价校验", "货重校验", "运费校验"):
            self.assertIn(must, labels, f"原有检查 {must} 不得丢失")

    def test_serialized_type_carries_the_checks(self):
        """端到端：序列化后的合同类型 `conditions` 里必须带上「车次」检查（引擎据此拦）。"""
        spec = _transport_type().build()
        trip_checks = [
            c for c in spec["conditions"]
            if c.get("value1", {}).get("key") == "trips"
        ]
        self.assertTrue(trip_checks, "序列化结果里必须有针对 trips 的前置检查")
        self.assertEqual(trip_checks[0]["op"], "GTE")
        self.assertIn("不能为负", trip_checks[0]["errorMessage"])


class Z14OverweightScenarioTests(TestCase):
    def test_smoke_raises_cargo_above_capacity(self):
        """冒烟必须把货重抬到「合计载重之上」，否则超重分支不可复现。"""
        from examples.competitions import auto_chain_smoke as smoke

        original_route = smoke._route_node_ids
        original_cap = smoke._vehicle_capacity
        smoke._route_node_ids = lambda cid, names: [1, 2, 3]
        smoke._vehicle_capacity = lambda cid, vehicles: 60.0   # 两辆重型卡车 × 30
        try:
            inputs = {"cargo_weight": 20, "vehicles": {"重型卡车": 2}}  # 预置实例的既有值
            smoke._fill_smoke_inputs(1, "auto-transport", inputs)
        finally:
            smoke._route_node_ids = original_route
            smoke._vehicle_capacity = original_cap

        self.assertEqual(
            inputs["cargo_weight"], 70,
            "冒烟货重必须被抬到合计载重 +10（> 60 吨）才能触发超重分支",
        )
        self.assertGreater(inputs["cargo_weight"], 60)

    def test_cargo_within_capacity_is_untouched(self):
        """货重已经超过载重时不得再改动（避免影响玩家自填的输入）。"""
        from examples.competitions import auto_chain_smoke as smoke

        original_route = smoke._route_node_ids
        original_cap = smoke._vehicle_capacity
        smoke._route_node_ids = lambda cid, names: [1, 2, 3]
        smoke._vehicle_capacity = lambda cid, vehicles: 60.0
        try:
            inputs = {"cargo_weight": 100, "vehicles": {"重型卡车": 2}}
            smoke._fill_smoke_inputs(1, "auto-transport", inputs)
        finally:
            smoke._route_node_ids = original_route
            smoke._vehicle_capacity = original_cap
        self.assertEqual(inputs["cargo_weight"], 100, "已超重的货重必须原样保留")

    def test_capacity_helper_sums_named_vehicles(self):
        """`_vehicle_capacity` 必须按「载具名 × 数量 × max_cargo」求和。"""
        from examples.competitions import auto_chain_smoke as smoke

        made: list[tuple] = []

        class _QS:
            def __init__(self, cargo):
                self.cargo = cargo

            def values_list(self, *_a, **_k):
                return self

            def first(self):
                return self.cargo

        class _Mgr:
            def filter(self, **kw):
                made.append(kw)
                return _QS(30.0 if kw.get("name") == "重型卡车" else None)

        import apps.vehicles.models as vm

        original = vm.Vehicle.objects
        vm.Vehicle.objects = _Mgr()
        try:
            cap = smoke._vehicle_capacity(7, {"重型卡车": 2})
        finally:
            vm.Vehicle.objects = original
        self.assertEqual(cap, 60.0)
        self.assertEqual(made[0].get("competition_id"), 7)

    def test_preset_instance_is_unchanged(self):
        """预置实例仍是 20 吨（> 60 为假）—— 这正是需要靠冒烟脚本才能复现的原因。"""
        text = (BACKEND / "examples" / "competitions" / "auto_chain_competition.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"cargo_weight": 20', text, "预置实例货重仍为 20 吨（不改变比赛经济模型）")

    def test_vehicle_capacity_matches_two_trucks(self):
        """核对载具载重：重型卡车单车 max_cargo=30（合计 60 吨是上述判断的前提）。"""
        text = (BACKEND / "examples" / "competitions" / "auto_chain_competition.py").read_text(
            encoding="utf-8"
        )
        idx = text.index('b.vehicle("重型卡车"')
        seg = text[idx: idx + 400]
        self.assertIn("max_cargo=30", seg, f"重型卡车应 max_cargo=30，实际片段 {seg[:200]!r}")
