# -*- coding: utf-8 -*-
"""复杂合同案例集的验收测试。

对 `examples/contracts/complex_contracts.py` 里的 6 个案例做两层验证：

1. **构建 + 体检**：全部编译成功，且静态体检零阻断；
2. **真实引擎执行**：搭一套完整比赛数据（产业字段 / 公司 / 原料地点价 / 地图 /
   载具 / 基建 / 科技），逐条断言**前置检查结果**与**各参与方的字段落账值**。

断言的是「金额算对了、落到正确的那家公司」，不是「JSON 长什么样」——这才说明案例真能跑。
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

from django.db import transaction
from django.test import TestCase

from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.contracts.builder import check as static_check
from apps.contracts.builder import snapshot
from apps.contracts.engine import ContractEngine
from apps.fuels.models import Fuel
from apps.industry_types.models import IndustryField, IndustryType
from apps.infrastructures.models import Infrastructure
from apps.maps.models import MapEdge, MapNode, MapNodeType, PathType
from apps.materials.models import Material
from apps.regions.models import Region
from apps.tech_tree.models import TechNode, TechPrerequisite
from apps.vehicles.models import Vehicle

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "contracts" / "complex_contracts.py"

#: 六个案例的 key
CONTRACT_KEYS = (
    "raw-material-procurement",
    "steel-sales-tiered",
    "technology-license",
    "syndicated-loan",
    "infrastructure-investment",
    "logistics-transport",
)

START_CASH = 10_000_000


def _load_example(competition_id: int, preferred_industry_id: int | None = None):
    """加载案例脚本，并把它的 COMPETITION_ID / PREFERRED_INDUSTRY_ID 指向测试数据。"""
    spec = importlib.util.spec_from_file_location("complex_contracts_for_test", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.COMPETITION_ID = competition_id
    if preferred_industry_id is not None:
        module.PREFERRED_INDUSTRY_ID = preferred_industry_id
    return module


#: 案例用到的全部产业字段：key → (类型, 配置)
FIELD_SPECS: dict[str, tuple[str, dict | None]] = {
    "cash": ("NUMBER", None),
    "revenue": ("NUMBER", None),
    "procurement_cost": ("NUMBER", None),
    "debt": ("NUMBER", None),
    "stock": ("DICTIONARY", {"valueType": "NUMBER"}),
    "inventory_value": ("NUMBER", None),
    "deposit": ("NUMBER", None),
    "carbon_fee": ("NUMBER", None),
    "carbon_total": ("NUMBER", None),
    "penalty": ("NUMBER", None),
    "tech_list": ("LIST", {"itemType": "STRING"}),
    "tech_level": ("NUMBER", None),
    "license_fee": ("NUMBER", None),
    "interest": ("NUMBER", None),
    "repay_terms": ("DICTIONARY", {"valueType": "NUMBER"}),
    "credit_line": ("NUMBER", None),
    "project_value": ("NUMBER", None),
    "project_progress": ("NUMBER", None),
    "bonus_population": ("NUMBER", None),
    "bonus_employment": ("NUMBER", None),
    "bonus_happiness": ("NUMBER", None),
    "route_log": ("STRING", None),
    "fleet_used": ("DICTIONARY", {"valueType": "NUMBER"}),
    "freight_income": ("NUMBER", None),
}


class ComplexContractFixture(TestCase):
    """六个案例公用的比赛数据。"""

    def setUp(self):
        self.comp = Competition.objects.create(name="复杂合同案例测试")
        self.region = Region.objects.create(competition=self.comp, name="东区")
        self.industry = IndustryType.objects.create(code=9201, name="综合产业")

        self.fields = self._make_fields()

        self.seller = self._make_company("卖方公司")
        self.buyer = self._make_company("买方公司")
        self.carrier = self._make_company("承运公司")
        self.client = self._make_company("委托公司")
        self.builder_co = self._make_company("建设公司")

        # 地图：A—B 100km、B—C 200km → A→C 最短路径 300km
        node_type = MapNodeType.objects.create(competition=self.comp, name="城市")
        path_type = PathType.objects.create(competition=self.comp, name="公路")
        self.node_a = MapNode.objects.create(
            competition=self.comp, name="A城", node_type=node_type, region="东区", x=0, y=0
        )
        self.node_b = MapNode.objects.create(
            competition=self.comp, name="B城", node_type=node_type, region="东区", x=1, y=0
        )
        self.node_c = MapNode.objects.create(
            competition=self.comp, name="C城", node_type=node_type, region="东区", x=2, y=0
        )
        MapEdge.objects.create(
            competition=self.comp, from_node=self.node_a, to_node=self.node_b,
            distance=100, path_type=path_type,
        )
        MapEdge.objects.create(
            competition=self.comp, from_node=self.node_b, to_node=self.node_c,
            distance=200, path_type=path_type,
        )

        # 原料「铁矿石」：A城 100 / B城 150（均价 125）→ 验证地点价口径
        self.material = Material.objects.create(
            competition=self.comp, name="铁矿石", origin="A城",
            carbon_emission_coefficient=0.5,
            node_prices=json.dumps({self.node_a.id: 100, self.node_b.id: 150}),
        )

        # 载具：载重 30、油耗 0.3、碳排 0.8、单价 300000
        fuel = Fuel.objects.create(competition=self.comp, name="柴油", price_per_liter="7.5")
        self.vehicle = Vehicle.objects.create(
            competition=self.comp, name="重型卡车", fuel=fuel,
            fuel_consumption_per_km=0.3, max_cargo=30, price="300000", carbon_emission=0.8,
        )

        # 基建：单价 1000000、占地 100、就业 0.02、人口 0.01、幸福 0.03
        self.infra = Infrastructure.objects.create(
            competition=self.comp, name="自备电厂", footprint=100, price="1000000",
            activation_price="50000", employment_rate_bonus=0.02, population_bonus=0.01,
            happiness_index_bonus=0.03,
        )

        # 科技：热轧工艺 ← 高炉冶炼
        self.tech_base = TechNode.objects.create(
            competition=self.comp, name="高炉冶炼", tier=1, research_cost="5000"
        )
        self.tech_advanced = TechNode.objects.create(
            competition=self.comp, name="热轧工艺", tier=2, research_cost="12000"
        )
        TechPrerequisite.objects.create(node=self.tech_advanced, prerequisite=self.tech_base)

        self.module = _load_example(self.comp.id, preferred_industry_id=self.industry.id)
        self.snap = snapshot(self.comp.id)

    # ---------- 夹具构造 ----------

    def _make_fields(self) -> dict[str, IndustryField]:
        out: dict[str, IndustryField] = {}
        out["location"] = IndustryField.objects.create(
            industry_type=self.industry, name="所在地", field_key="location", field_type="STRING"
        )
        for key, (ftype, config) in FIELD_SPECS.items():
            out[key] = IndustryField.objects.create(
                industry_type=self.industry,
                name=key,
                field_key=key,
                field_type=ftype,
                config=json.dumps(config) if config else "{}",
            )
        return out

    def _make_company(self, name: str) -> Company:
        company = Company.objects.create(
            competition=self.comp, name=name, industry_type=self.industry, region=self.region
        )
        for key, (ftype, _config) in FIELD_SPECS.items():
            if key == "cash":
                value = str(START_CASH)
            elif ftype == "LIST":
                value = "[]"
            elif ftype == "DICTIONARY":
                value = "{}"
            else:
                value = "0"
            CompanyFieldValue.objects.create(
                company=company, industry_field=self.fields[key], value=value
            )
        CompanyFieldValue.objects.create(
            company=company, industry_field=self.fields["location"], value="A城"
        )
        return company

    # ---------- 执行辅助 ----------

    def _run(self, contract, *, parties: dict[str, Company], inputs: dict | None = None):
        """跑真实引擎（事务回滚），返回 `(checks, fields_by_role, err)`。

        `fields_by_role` 是 `{角色: {字段key: 落账后的值}}`。

        **必须按角色分组**：引擎返回的 `fields` 键是 `"{companyId}:{fieldKey}"`；
        若只按 fieldKey 汇总，多公司参与时（运输合同的承运方 + 委托方）后写的会覆盖
        前一家，断言就会拿到错公司的值。
        """
        payload = contract.build()
        party_rows = [
            {
                "role": p["role"],
                "label": p.get("label") or p["role"],
                "isHost": bool(p.get("isHost")),
                "companyId": None if p.get("isHost") else parties[p["role"]].id,
            }
            for p in payload["partyRoles"]
        ]
        engine_dict = {
            "id": None,
            "competition_id": self.comp.id,
            "parties": json.dumps(party_rows, ensure_ascii=False),
            # 引擎不会套用 inputSchema 的 default（那是调用方的责任），
            # 这里用 default_inputs() 补齐，否则未提供的输入项会被 to_number(None) 变成 0，
            # 表现为「乘费率的效果恒为 0」这类静默错误。
            "inputs": json.dumps(contract.default_inputs(inputs), ensure_ascii=False),
            "contract_type": {
                "id": None,
                "effects": json.dumps(payload["effects"], ensure_ascii=False),
                "conditions": json.dumps(payload["conditions"], ensure_ascii=False),
                "inputSchema": json.dumps(payload["inputSchema"], ensure_ascii=False),
            },
        }
        role_of_company = {
            int(row["companyId"]): row["role"]
            for row in party_rows
            if row["companyId"] is not None
        }
        try:
            with transaction.atomic():
                result = ContractEngine().execute(engine_dict, throw_on_fail=False)
                checks = (result.get("result") or {}).get("checks") or []
                raw_fields = (result.get("result") or {}).get("fields") or {}
                transaction.set_rollback(True)
        except Exception as e:  # noqa: BLE001 - 测试要看到真实报错
            return [], {}, e

        by_role: dict[str, dict] = {}
        for key, value in raw_fields.items():
            company_id, _, field_key = str(key).partition(":")
            role = role_of_company.get(int(company_id)) if company_id.isdigit() else None
            if role is None:
                continue
            by_role.setdefault(role, {})[field_key] = value
        return checks, by_role, None

    def _contract(self, key: str):
        return {c.key: c for c in self.module.build()}[key]

    def _money(self, fields: dict, role: str, field: str = "cash") -> float:
        """取金额并转 float（引擎存 Decimal，直接与 int 相减会 TypeError）。"""
        return float(fields[role][field])


# =============================================================================
# 一、构建 + 体检
# =============================================================================


class ComplexContractBuildTests(ComplexContractFixture):
    def test_all_six_compile(self):
        contracts = {c.key: c for c in self.module.build()}
        self.assertEqual(sorted(contracts), sorted(CONTRACT_KEYS))
        for key, ct in contracts.items():
            with self.subTest(contract=key):
                payload = ct.build()
                self.assertTrue(payload["partyRoles"], "必须有参与方")
                self.assertTrue(payload["effects"], "必须有效果")
                for eff in payload["effects"]:
                    self.assertIn(eff["kind"], ("FIELD", "IF", "FOREACH", "ASSIGN"))

    def test_all_pass_static_check(self):
        """六个案例在完整夹具下必须零阻断（字段都在、口径都对）。"""
        bad = []
        for key in CONTRACT_KEYS:
            report = static_check(self._contract(key), snap=self.snap)
            if not report.ok:
                bad.append(f"{key}: " + "；".join(f.message for f in report.errors))
        self.assertEqual(bad, [], "\n".join(bad))

    def test_static_check_reports_no_field_errors(self):
        """不该出现「字段不存在」这类问题（夹具把案例需要的字段都建了）。"""
        for key in CONTRACT_KEYS:
            report = static_check(self._contract(key), snap=self.snap)
            codes = [f.code for f in report.findings]
            self.assertNotIn("field.missing", codes, key)
            self.assertNotIn("field.not_anywhere", codes, key)


# =============================================================================
# 二、① 原料采购：地点价口径
# =============================================================================


class RawMaterialProcurementTests(ComplexContractFixture):
    def _run_buy(self, **inputs):
        return self._run(
            self._contract("raw-material-procurement"),
            parties={"supplier": self.seller, "buyer": self.buyer},
            inputs=inputs,
        )

    def test_location_price_uses_buyer_location(self):
        """采购方所在地 A城，铁矿石在 A城报价 100 → 买 10 单位 = 1000。

        同一种原料在 B城是 150；若「按哪一方取价」漏连或连错，这里会变成均价 125
        （=1250）——本测试正是钉住这个隐式依赖。
        """
        checks, fields, err = self._run_buy(materials={"铁矿石": 10}, transport="0")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue(all(c.get("passed") for c in checks), checks)
        self.assertEqual(self._money(fields, "buyer"), START_CASH - 1000)
        self.assertEqual(self._money(fields, "supplier"), START_CASH + 1000)

    def test_carbon_fee_and_totals(self):
        """碳排 = 0.5 × 10 = 5；环保费 = 5 × 0.8 = 4；库存价值 += 货款。"""
        _checks, fields, err = self._run_buy(materials={"铁矿石": 10}, carbon_fee_rate="0.8")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(float(fields["buyer"]["carbon_total"]), 5)
        self.assertEqual(float(fields["buyer"]["carbon_fee"]), 4)
        self.assertEqual(float(fields["buyer"]["inventory_value"]), 1000)
        self.assertEqual(float(fields["buyer"]["procurement_cost"]), 1000)

    def test_transport_is_added_to_payable(self):
        _checks, fields, err = self._run_buy(materials={"铁矿石": 10}, transport="250")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(self._money(fields, "buyer"), START_CASH - 1000 - 250)
        self.assertEqual(self._money(fields, "supplier"), START_CASH + 1000)

    def test_insufficient_cash_is_blocked(self):
        """买方现金只剩 10 → 前置检查必须不通过。"""
        CompanyFieldValue.objects.filter(
            company=self.buyer, industry_field=self.fields["cash"]
        ).update(value="10")
        checks, _fields, err = self._run_buy(materials={"铁矿石": 10})
        self.assertIsNone(err, f"引擎报错：{err}")
        failed = [c for c in checks if not c.get("passed")]
        self.assertTrue(failed, "现金不足必须被检查拦下")
        self.assertIn("货币资金不足", json.dumps(failed, ensure_ascii=False))

    def test_empty_list_is_blocked(self):
        checks, _fields, err = self._run_buy(materials={})
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue([c for c in checks if not c.get("passed")])

    def test_inventory_loop_records_each_item(self):
        """入库循环：清单里 2 种原料 → 字典里登记 2 次「待入库」。"""
        _checks, fields, err = self._run_buy(materials={"铁矿石": 3, "焦煤": 4})
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(fields["buyer"]["stock"], {"待入库": 2})


# =============================================================================
# 三、② 钢材销售：阶梯定价
# =============================================================================


class SteelSalesTieredTests(ComplexContractFixture):
    def _paid(self, tons: str, *, member: bool = False, rate: str = "0.05") -> float:
        """返回买方被扣的金额（= 应付货款）。"""
        _checks, fields, err = self._run(
            self._contract("steel-sales-tiered"),
            parties={"seller": self.seller, "buyer": self.buyer},
            inputs={"tons": tons, "is_member": member, "member_rate": rate},
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        return START_CASH - self._money(fields, "buyer")

    def test_three_price_tiers(self):
        """三档单价：≥1000→3800，≥500→4000，<500→4200。"""
        self.assertEqual(self._paid("1000"), 1000 * 3800)
        self.assertEqual(self._paid("500"), 500 * 4000)
        self.assertEqual(self._paid("499"), 499 * 4200)

    def test_member_discount(self):
        """会员 5% 折扣：1000 吨 × 3800 × 0.95。"""
        self.assertEqual(self._paid("1000", member=True, rate="0.05"), 1000 * 3800 * 0.95)

    def test_non_member_pays_full(self):
        self.assertEqual(self._paid("1000", member=False), 1000 * 3800)

    def test_revenue_and_deposit_recorded(self):
        """营业收入记成交额（折扣前），定金按 30% 留痕。"""
        _checks, fields, err = self._run(
            self._contract("steel-sales-tiered"),
            parties={"seller": self.seller, "buyer": self.buyer},
            inputs={"tons": "1000", "is_member": True, "member_rate": "0.05"},
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(float(fields["seller"]["revenue"]), 1000 * 3800)
        self.assertEqual(float(fields["buyer"]["deposit"]), 1000 * 3800 * 0.3)

    def test_zero_tons_blocked(self):
        checks, _fields, err = self._run(
            self._contract("steel-sales-tiered"),
            parties={"seller": self.seller, "buyer": self.buyer},
            inputs={"tons": "0"},
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue([c for c in checks if not c.get("passed")])


# =============================================================================
# 四、③ 技术引进：前置校验
# =============================================================================


class TechnologyLicenseTests(ComplexContractFixture):
    def _run_license(self, **inputs):
        return self._run(
            self._contract("technology-license"),
            parties={"licensor": self.seller, "licensee": self.buyer},
            inputs=inputs,
        )

    def test_prerequisites_present_allows_license(self):
        """引进「热轧工艺」且已解锁「高炉冶炼」→ 通过，等级 +1，清单追加。"""
        checks, fields, err = self._run_license(
            tech="热轧工艺", owned=["高炉冶炼"], license_fee="200000"
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue(all(c.get("passed") for c in checks), checks)
        self.assertEqual(self._money(fields, "licensee"), START_CASH - 200_000)
        self.assertEqual(float(fields["licensee"]["tech_level"]), 1)
        self.assertIn("热轧工艺", fields["licensee"]["tech_list"])

    def test_missing_prerequisite_is_blocked(self):
        """已解锁清单为空 → 列表包含比较不通过，签约被拦。"""
        checks, _fields, err = self._run_license(
            tech="热轧工艺", owned=[], license_fee="200000"
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        failed = [c for c in checks if not c.get("passed")]
        self.assertTrue(failed, "前置未解锁必须被拦下")
        self.assertIn("前置", json.dumps(failed, ensure_ascii=False))

    def test_no_prerequisite_tech_always_passes(self):
        """「高炉冶炼」没有前置 → 空前置集合 ⊆ 任何已解锁集合。"""
        checks, fields, err = self._run_license(tech="高炉冶炼", owned=[], license_fee="5000")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue(all(c.get("passed") for c in checks), checks)
        self.assertEqual(self._money(fields, "licensee"), START_CASH - 5000)

    def test_discount_applies(self):
        _checks, fields, err = self._run_license(
            tech="高炉冶炼", owned=[], license_fee="100000", discount="0.2"
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(self._money(fields, "licensee"), START_CASH - 80_000)


# =============================================================================
# 五、④ 银团贷款：复利与分档
# =============================================================================


class SyndicatedLoanTests(ComplexContractFixture):
    @staticmethod
    def _base_interest(months: str = "12", rate: str = "0.06") -> float:
        return 1_000_000 * (math.exp(float(rate) * int(months) / 12) - 1)

    def _run_loan(self, **inputs):
        return self._run(
            self._contract("syndicated-loan"),
            parties={"borrower": self.buyer},
            inputs=inputs,
        )

    def test_compound_interest_with_discount_branch(self):
        """借款方产业 = 案例声明的优惠产业 → 走 9 折分支；不贴息。"""
        _checks, fields, err = self._run_loan(
            principal="1000000", months="12", rate="0.06", subsidized=False
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        expected = round(self._base_interest() * 0.9)
        self.assertEqual(self._money(fields, "borrower"), START_CASH + 1_000_000)
        self.assertAlmostEqual(float(fields["borrower"]["interest"]), expected, delta=1)

    def test_subsidy_halves_interest(self):
        _checks, fields, err = self._run_loan(
            principal="1000000", months="12", rate="0.06", subsidized=True
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        expected = round(self._base_interest() * 0.9 * 0.5)
        self.assertAlmostEqual(float(fields["borrower"]["interest"]), expected, delta=1)

    def test_no_discount_when_industry_differs(self):
        """把案例声明的优惠产业 id 改成**确定不等于**公司产业的值 → 走 else 分支。

        测试库每次新建、产业 id 从 1 开始自增，所以不能假设「公司产业 id ≠ 1」；
        这里取一个远超现有 id 的值来保证条件不成立。
        """
        other_id = (
            IndustryType.objects.order_by("-id").values_list("id", flat=True).first() or 0
        ) + 1000
        self.assertNotEqual(other_id, self.buyer.industry_type_id, "前提：优惠产业须不同于公司产业")
        module = _load_example(self.comp.id, preferred_industry_id=other_id)
        ct = {c.key: c for c in module.build()}["syndicated-loan"]
        _checks, fields, err = self._run(
            ct,
            parties={"borrower": self.buyer},
            inputs={"principal": "1000000", "months": "12", "rate": "0.06",
                    "subsidized": False},
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertAlmostEqual(
            float(fields["borrower"]["interest"]), round(self._base_interest()), delta=1
        )

    def test_term_schedule_is_generated_per_period(self):
        """期数 6 → 还款计划字典里登记 6 次（动态键循环）。"""
        _checks, fields, err = self._run_loan(principal="100000", months="6", rate="0.06")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(fields["borrower"]["repay_terms"], {"待还期数": 6})

    def test_zero_principal_blocked(self):
        checks, _fields, err = self._run_loan(principal="0", months="12")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue([c for c in checks if not c.get("passed")])


# =============================================================================
# 六、⑤ 基建投资：达标与未达标
# =============================================================================


class InfrastructureInvestmentTests(ComplexContractFixture):
    def _run_projects(self, *, progress: str, projects: dict | None = None):
        return self._run(
            self._contract("infrastructure-investment"),
            parties={"builder": self.builder_co},
            inputs={"projects": projects or {"自备电厂": 1}, "progress": progress},
        )

    def test_target_reached_pays_rest_and_bonuses(self):
        """进度 1.0 ≥ 0.8 → 首期 30 万 + 追加 70 万 = +100 万；并计提三项效益。"""
        _checks, fields, err = self._run_projects(progress="1")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(self._money(fields, "builder"), START_CASH + 1_000_000)
        self.assertEqual(float(fields["builder"]["project_value"]), 1_000_000)
        self.assertAlmostEqual(float(fields["builder"]["bonus_population"]), 0.01, places=6)
        self.assertAlmostEqual(float(fields["builder"]["bonus_employment"]), 0.02, places=6)
        self.assertAlmostEqual(float(fields["builder"]["bonus_happiness"]), 0.03, places=6)
        self.assertIsNone(fields["builder"].get("penalty"))

    def test_target_missed_deducts_penalty(self):
        """进度 0.5 < 0.8 → 扣 10% 违约金 10 万、再给首期 30 万。

        代码里 `when(...)/otherwise()` 位于首期款之后，故净变化 = +300000 - 100000。
        """
        _checks, fields, err = self._run_projects(progress="0.5")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(self._money(fields, "builder"), START_CASH + 300_000 - 100_000)
        self.assertEqual(float(fields["builder"]["penalty"]), 100_000)
        self.assertEqual(fields["builder"].get("bonus_population", 0), 0)

    def test_boundary_progress_is_inclusive(self):
        """边界 0.8 应当算达标（条件 >=）。"""
        _checks, fields, err = self._run_projects(progress="0.8")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(self._money(fields, "builder"), START_CASH + 1_000_000)

    def test_loop_registers_each_project(self):
        """两种基建 → 在建清单登记 2 次。"""
        _checks, fields, err = self._run_projects(
            progress="1", projects={"自备电厂": 1, "港口": 2}
        )
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(fields["builder"]["stock"], {"在建项目": 2})


class StaticCheckIntegrationTests(ComplexContractFixture):
    """体检链路自身的两个易错点（都是落地时踩出来的）。"""

    def test_math_functions_are_recognized_in_formulas(self):
        """公式里的数学函数（`exp`/`log`/`pow`…）必须被认作可用名字。

        这些名字是从引擎**动态派生**的。若在模块导入时就求值，而导入发生在
        `django.setup()` 之前（示例脚本支持 `python xxx.py` 直接运行，必然如此），
        那时引擎不可导入、集合会退化成最小集，`exp` 就会被误判为「未知名字」。
        所以派生必须惰性化——本测试钉住这一点。
        """
        report = static_check(self._contract("syndicated-loan"), snap=self.snap)
        codes = [f.code for f in report.findings]
        self.assertNotIn("value.formula_name", codes, [f.message for f in report.findings])
        self.assertNotIn("value.formula_inputs_object", codes)
        self.assertNotIn("value.formula_scope_object", codes)

    def test_default_inputs_fills_schema_defaults(self):
        """`default_inputs()` 补齐默认值——引擎自己不会做这件事。"""
        ct = self._contract("infrastructure-investment")
        merged = ct.default_inputs({"progress": "0.5"})
        self.assertEqual(merged["progress"], "0.5", "显式传的优先")
        self.assertEqual(merged["penalty_rate"], "0.1", "未传的用 schema 默认值")


class DefaultInputsRegressionTests(ComplexContractFixture):
    """回归：不补默认值会让「乘费率的效果」静默变成 0。"""

    def test_without_defaults_penalty_becomes_zero(self):
        """故意不补 `penalty_rate` 默认值 → 引擎取到 None → to_number → 0。"""
        payload = self._contract("infrastructure-investment").build()
        party_rows = [
            {"role": "builder", "label": "建设方", "isHost": False,
             "companyId": self.builder_co.id},
        ]
        engine_dict = {
            "id": None,
            "competition_id": self.comp.id,
            "parties": json.dumps(party_rows, ensure_ascii=False),
            # 只给 progress，不给 penalty_rate —— 模拟「忘了补默认值」
            "inputs": json.dumps(
                {"projects": {"自备电厂": 1}, "progress": "0.5"}, ensure_ascii=False
            ),
            "contract_type": {
                "id": None,
                "effects": json.dumps(payload["effects"], ensure_ascii=False),
                "conditions": json.dumps(payload["conditions"], ensure_ascii=False),
                "inputSchema": json.dumps(payload["inputSchema"], ensure_ascii=False),
            },
        }
        with transaction.atomic():
            result = ContractEngine().execute(engine_dict, throw_on_fail=False)
            fields = (result.get("result") or {}).get("fields") or {}
            transaction.set_rollback(True)
        self.assertEqual(
            float(fields[f"{self.builder_co.id}:penalty"]), 0,
            "不补默认值时违约金为 0——这正是 default_inputs() 要防的静默错误",
        )


# =============================================================================
# 七、⑥ 物流运输：路程与超重
# =============================================================================


class LogisticsTransportTests(ComplexContractFixture):
    #: A→B→C = 300km；运费 = 300×12 + 0.3×300 = 3600 + 90
    FREIGHT = 3600 + 90
    #: 碳税 = 碳排(0.8 × 300 = 240) × 0.05
    CARBON_TAX = 12

    def _run_route(self, *, weight: str, trips: str = "1"):
        return self._run(
            self._contract("logistics-transport"),
            parties={"carrier": self.carrier, "client": self.client},
            inputs={
                "route": [self.node_a.id, self.node_b.id, self.node_c.id],
                "vehicles": {"重型卡车": 1},
                "cargo_weight": weight,
                "rate_per_km": "12",
                "trips": trips,
                "carbon_tax_rate": "0.05",
            },
        )

    def test_distance_uses_shortest_path(self):
        """沿相邻节点求最短路径距离之和（Dijkstra），不是把距离简单相加。

        委托方现金 = 起始 − 运费 − 碳税；承运方记营业收入。
        """
        checks, fields, err = self._run_route(weight="10")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertTrue(all(c.get("passed") for c in checks), checks)
        self.assertEqual(
            self._money(fields, "client"), START_CASH - self.FREIGHT - self.CARBON_TAX
        )
        self.assertEqual(float(fields["carrier"]["freight_income"]), self.FREIGHT)

    def test_overweight_surcharge(self):
        """载重 30、货重 40 → 运费 ×1.1，违约金 = 加价额的 10%。"""
        _checks, fields, err = self._run_route(weight="40")
        self.assertIsNone(err, f"引擎报错：{err}")
        surcharged = self.FREIGHT * 1.1
        self.assertAlmostEqual(float(fields["carrier"]["freight_income"]), surcharged, places=4)
        self.assertEqual(
            self._money(fields, "client"), START_CASH - surcharged - self.CARBON_TAX
        )
        self.assertAlmostEqual(float(fields["carrier"]["penalty"]), surcharged * 0.1, places=4)

    def test_within_capacity_no_surcharge(self):
        _checks, fields, err = self._run_route(weight="30")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(float(fields["carrier"]["freight_income"]), self.FREIGHT)
        # 未超重 → 违约金分支不执行，字段根本不会被写入
        self.assertEqual(fields["carrier"].get("penalty", 0), 0)

    def test_carbon_tax_deducted_from_carrier(self):
        """碳税从承运方环保费里扣（SUB 12 → -12）。"""
        _checks, fields, err = self._run_route(weight="10")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(float(fields["carrier"]["carbon_fee"]), -self.CARBON_TAX)

    def test_route_log_records_start_node(self):
        """台账写入路程起点名（同一份 nodeRoute 输入的第三种聚合口径）。"""
        _checks, fields, err = self._run_route(weight="10")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(fields["carrier"]["route_log"], "A城")

    def test_fleet_usage_loop(self):
        _checks, fields, err = self._run_route(weight="10")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(fields["carrier"]["fleet_used"], {"出车次": 1})

    def test_multi_trip_freight(self):
        """2 车次 → 路程费 ×2，油耗仍按一趟（油耗项不含车次）。"""
        _checks, fields, err = self._run_route(weight="10", trips="2")
        self.assertIsNone(err, f"引擎报错：{err}")
        self.assertEqual(float(fields["carrier"]["freight_income"]), 300 * 12 * 2 + 90)
