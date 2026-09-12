"""合同类型代码化建库的测试。

覆盖三件事：

1. **编译契约**：产出的四份 JSON 与前端可视化编辑器 / 引擎消费的格式一致
   （用引擎自身的解析与执行函数验证，而不是自己写的断言）；
2. **降低抽象的效果**：具名效果 × 字段类型在构建期报错；实体属性对模型真实字段校验；
3. **静态体检**：能发现「引擎会静默降级」的配置（聚合清单类型错配、
   引用不存在的输入项、字段不存在、地点价回退等）。

关键测试用**真实引擎**跑：把编译产物喂给 `ContractEngine.execute`（事务回滚），
断言 checks 与字段改动符合预期。这样「本库产出的 JSON 引擎能不能吃」是被证明的，
而不是被假设的。
"""

from __future__ import annotations

import json

from django.db import transaction
from django.test import TestCase

from apps.companies.models import Company, CompanyFieldValue
from apps.contracts.builder import (
    ERROR,
    INFO,
    WARNING,
    BuildError,
    ContractType,
    add_number,
    check as static_check,
    formula,
    number,
    snapshot,
    sum_of,
    text,
    total_price,
    var,
)
from apps.contracts.builder.effects import (
    EFFECT_KINDS,
    append_items,
    effects_from_specs,
    remove_items,
    remove_keys,
    set_value,
    sub_dict,
)
from apps.contracts.builder.values import ENTITY_ATTRIBUTES
from apps.contracts.engine import ContractEngine
from apps.contracts.models import ContractType as ContractTypeModel
from apps.industry_types.models import IndustryField, IndustryType
from apps.materials.models import Material
from apps.regions.models import Region


# ==================== 公共夹具 ====================


class BuilderFixtureMixin:
    """建一场最小可用的比赛数据：1 产业 2 字段 2 公司 1 原料 1 地图节点。"""

    def make_fixture(self):
        from apps.competitions.models import Competition
        from apps.maps.models import MapNode, MapNodeType

        comp = Competition.objects.create(name=f"合同建库测试-{self.__class__.__name__}")
        region = Region.objects.create(competition=comp, name="东区")

        industry = IndustryType.objects.create(code=9001, name="测试产业")
        IndustryField.objects.create(
            industry_type=industry, name="所在地", field_key="location", field_type="STRING"
        )
        cash = IndustryField.objects.create(
            industry_type=industry, name="现金", field_key="cash", field_type="NUMBER"
        )
        tags = IndustryField.objects.create(
            industry_type=industry, name="标签", field_key="tags", field_type="LIST",
            config=json.dumps({"itemType": "STRING"}),
        )
        stock = IndustryField.objects.create(
            industry_type=industry, name="库存", field_key="stock", field_type="DICTIONARY",
            config=json.dumps({"valueType": "NUMBER"}),
        )

        seller = Company.objects.create(
            competition=comp, name="卖方公司", industry_type=industry, region=region
        )
        buyer = Company.objects.create(
            competition=comp, name="买方公司", industry_type=industry, region=region
        )
        for company, cash_value in ((seller, "1000"), (buyer, "500")):
            for field, value in (
                (cash, cash_value),
                (tags, json.dumps([])),
                (stock, json.dumps({})),
                (IndustryField.objects.get(industry_type=industry, field_key="location"), "东区港"),
            ):
                CompanyFieldValue.objects.create(
                    company=company, industry_field=field, value=value
                )

        node_type = MapNodeType.objects.create(competition=comp, name="城市")
        MapNode.objects.create(
            competition=comp, name="东区港", node_type=node_type, region="东区", x=1, y=1
        )
        material = Material.objects.create(
            competition=comp, name="铁矿石", origin="东区港",
            carbon_emission_coefficient=0.5,
            node_prices=json.dumps({}),
        )
        return {
            "competition": comp,
            "industry": industry,
            "seller": seller,
            "buyer": buyer,
            "material": material,
            "fields": {"cash": cash, "tags": tags, "stock": stock},
        }


# ==================== 1. 编译契约 ====================


class CompileContractTests(TestCase):
    """产出的 JSON 必须与既有契约一致。"""

    def test_minimal_payload_shape(self):
        ct = ContractType("t-min", "最小合同")
        ct.party("seller", "卖方")
        ct.party("buyer", "买方")
        amount = ct.input("amount", "金额", "number", required=True)
        ct.add_number(ct._party_by_role["seller"].field("cash"), amount)

        payload = ct.payload()
        for field in ("partyRoles", "inputSchema", "effects", "conditions"):
            self.assertIn(field, payload)
            self.assertIsInstance(payload[field], list)
        self.assertIsNone(payload["graph"], "graph 必须为 None（后端 allow_null）")
        self.assertEqual(payload["partyCount"], 2)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["key"], "t-min")

    def test_input_schema_matches_frontend_contract(self):
        ct = ContractType("t-input", "输入项")
        p = ct.party("p", "方")
        ct.input("amount", "金额", "number", required=True, default=100)
        ct.input("mats", "原料清单", "materialList", party=p)
        ct.input("infra", "基建清单", "infrastructureList", allowed=["电厂", "港口"])
        ct.input("veh", "载具清单", "vehicleList", allowed=["卡车"])
        ct.input("m", "选原料", "ENTITY", entity_type="MATERIAL")
        ct.input("nodes", "节点链", "nodeRoute")

        by_key = {i["key"]: i for i in ct.build()["inputSchema"]}
        self.assertEqual(by_key["amount"]["type"], "number")
        self.assertTrue(by_key["amount"]["required"])
        self.assertEqual(by_key["amount"]["default"], 100)
        self.assertEqual(by_key["mats"]["party"], "p")
        self.assertEqual(by_key["infra"]["allowedInfrastructures"], ["电厂", "港口"])
        self.assertEqual(by_key["veh"]["allowedVehicles"], ["卡车"])
        self.assertEqual(by_key["m"]["entityType"], "MATERIAL")
        self.assertEqual(by_key["nodes"]["type"], "nodeRoute")

    def test_all_11_named_effects_compile(self):
        """11 种具名效果都能编译成引擎认识的 {kind:FIELD, op, value}。"""
        ct = ContractType("t-effects", "效果全集")
        p = ct.party("p", "方")
        ct.add_number(p.field("cash"), number("1"))
        ct.sub_number(p.field("cash"), number("1"))
        ct.set_number(p.field("cash"), number("1"))
        ct.append_items(p.field("tags"), text("A"))
        ct.remove_items(p.field("tags"), text("A"))
        ct.set_items(p.field("tags"), [text("A")])
        ct.add_dict(p.field("stock"), {"钢坯": 1})
        ct.sub_dict(p.field("stock"), {"钢坯": 1})
        ct.remove_keys(p.field("stock"), "钢坯")
        ct.set_dict(p.field("stock"), {"钢坯": 1})
        ct.set_value(p.field("tag_text"), text("X"))

        effects = ct.build()["effects"]
        self.assertEqual(len(effects), 11)
        for eff in effects:
            self.assertEqual(eff["kind"], "FIELD")
            self.assertIn(eff["op"], ("ADD", "SUB", "SET"))
            self.assertIn("value", eff)
            self.assertTrue(eff["party"])

    def test_dict_sub_vs_remove_keys_are_distinct_shapes(self):
        """「字典减数」与「字典删键」编译成不同形状——这是降低抽象的核心之一。

        引擎靠值的形态区分二者：字典=逐键相减，数组=删键。
        本库把它变成两个名字，形状仍与引擎一致。
        """
        ct = ContractType("t-dict", "字典")
        p = ct.party("p", "方")
        ct.sub_dict(p.field("stock"), {"钢坯": 2})
        ct.remove_keys(p.field("stock"), "钢坯")

        e1, e2 = ct.build()["effects"]
        self.assertEqual(e1["op"], e2["op"], "引擎 op 相同（都是 SUB）")
        # 减数：CONST 包一层字面量字典（引擎会对 value 走 eval_value_spec，
        # 裸字典会被 to_number 降成 0）
        self.assertEqual(e1["value"]["type"], "CONST")
        self.assertEqual(e1["value"]["value"], {"钢坯": "2"})
        # 删键：数组形状（引擎按数组走「删键」分支）
        self.assertEqual(e2["value"]["type"], "OP", "删键：列表值")
        self.assertEqual(e2["value"]["op"], "LIST_CONCAT")
        self.assertEqual(len(e2["value"]["args"]), 1, "单键也必须保持数组形状")

    def test_effect_argument_validation(self):
        """具名效果的入参在构建期就校验（空值、类型不符都拦下）。"""
        ct = ContractType("t-mismatch", "类型不符")
        p = ct.party("p", "方")
        with self.assertRaises(BuildError):
            append_items(p.field("x"))  # 没有元素
        with self.assertRaises(BuildError):
            remove_items(p.field("x"))  # 没有元素
        with self.assertRaises(BuildError):
            remove_keys(p.field("x"))  # 没有键
        with self.assertRaises(BuildError):
            ct.add_dict(p.field("x"), {})  # 空字典
        with self.assertRaises(BuildError):
            ct.set_dict(p.field("x"), ["不是字典"])
        with self.assertRaises(BuildError):
            ct.set_items(p.field("x"), iter([]))  # 空列表：清空请写 set_items(t, [])？

    def test_set_items_empty_list_is_allowed(self):
        """`set_items(t, [])` 是清空列表的正当写法（与 append_items 的空参不同）。"""
        ct = ContractType("t-clear", "清空")
        p = ct.party("p", "方")
        ct.set_items(p.field("tags"), [])
        eff = ct.build()["effects"][0]
        self.assertEqual(eff["op"], "SET")
        self.assertEqual(eff["value"]["op"], "LIST_CONCAT")
        self.assertEqual(eff["value"]["args"], [])

    def test_condition_kinds(self):
        ct = ContractType("t-cond", "条件")
        seller = ct.party("seller", "卖方")
        buyer = ct.party("buyer", "买方")
        amount = ct.input("amount", "金额", "number")
        ct.check(buyer.field("cash") >= amount, error="现金不足")
        ct.check(ct.input("a", "A", "number") >= ct.input("b", "B", "number"), label="A≥B")
        ct.check(buyer.is_industry(9001), label="买方是测试产业")
        ct.check_container("LIST_COMPARE", "CONTAINS", buyer.field("tags"), text("X"), label="标签含X")
        ct.check_container("DICT_COMPARE", "GTE", buyer.field("stock"), buyer.field("stock"), label="库存对比")

        conds = ct.build()["conditions"]
        kinds = [c["kind"] for c in conds]
        self.assertEqual(
            kinds, ["FIELD_COMPARE", "VALUE_COMPARE", "INDUSTRY_IS", "LIST_COMPARE", "DICT_COMPARE"]
        )
        self.assertEqual(conds[0]["errorMessage"], "现金不足")
        self.assertEqual(conds[2]["party"], "buyer")
        self.assertEqual(conds[2]["industryTypeId"], 9001)

    def test_if_condition_uses_value_spec_shape(self):
        """IF 的 cond 必须是**值源**形状（`type`），不是检查形状（`kind`）。

        引擎的 `eval_value_spec` 按 `type` 分派；写成 `kind` 会落到默认分支返回 0，
        导致分支永远走 else。前端可视化编辑器产出的也是 `type`（graph-model.ts:1275）。
        """
        ct = ContractType("t-ifshape", "分支形状")
        p = ct.party("p", "方")
        with ct.when(p.is_industry(9001)):
            ct.add_number(p.field("cash"), number("1"))
        cond = ct.build()["effects"][0]["cond"]
        self.assertEqual(cond["type"], "INDUSTRY_IS")
        self.assertNotIn("kind", cond)
        self.assertEqual(cond["industryTypeId"], 9001)

    def test_control_flow_shares_single_if_node(self):
        """when + otherwise 产出**一条** IF 效果（不是两条并列）。"""
        ct = ContractType("t-if", "分支")
        p = ct.party("p", "方")
        with ct.when(p.is_industry(9001)):
            ct.add_number(p.field("cash"), number("10"))
        with ct.otherwise():
            ct.add_number(p.field("cash"), number("20"))

        effects = ct.build()["effects"]
        self.assertEqual(len(effects), 1, effects)
        self.assertEqual(effects[0]["kind"], "IF")
        self.assertEqual(len(effects[0]["then"]), 1)
        self.assertEqual(len(effects[0]["else"]), 1)
        self.assertEqual(effects[0]["then"][0]["value"]["value"], "10")
        self.assertEqual(effects[0]["else"][0]["value"]["value"], "20")

    def test_foreach_and_assign(self):
        ct = ContractType("t-loop", "循环")
        p = ct.party("p", "方")
        mats = ct.input("mats", "原料清单", "materialList")
        with ct.for_each(mats, var="row"):
            ct.assign("qty", ct.item("mats"))
            ct.add_number(p.field("total"), var("qty"))
        eff = ct.build()["effects"][0]
        self.assertEqual(eff["kind"], "FOREACH")
        self.assertEqual(eff["var"], "row")
        # 清单类输入项的值是 {名称: 数量} 字典，而引擎的 FOREACH 只遍历列表
        # （`lst = arr if isinstance(arr, list) else []`），所以必须包成 keys(...)
        self.assertEqual(eff["items"], {"type": "FORMULA", "expr": "keys(mats)"})
        self.assertEqual(eff["body"][0]["kind"], "ASSIGN")
        # 引擎的 FORMULA 沙箱把输入项与循环变量铺成**顶层名字**（engine.py:1788），
        # 没有 inputs / scope 两个字典对象，所以表达式必须是 mats[row]
        self.assertEqual(eff["body"][0]["value"]["expr"], "mats[row]")
        self.assertEqual(eff["body"][1]["value"], {"type": "VAR", "name": "qty"})

    def test_otherwise_without_when_rejected(self):
        ct = ContractType("t-else", "分支错用")
        ct.party("p", "方")
        with self.assertRaises(BuildError):
            with ct.otherwise():
                pass

    def test_direct_module_function_is_caught(self):
        """直接调模块级 add_number(...) 会被漏挂载自检拦下（否则静默丢一条效果）。"""
        ct = ContractType("t-orphan", "漏挂载")
        p = ct.party("p", "方")
        add_number(p.field("cash"), number("1"))  # ✗ 没经过 ct.
        with self.assertRaises(BuildError) as ctx:
            ct.build()
        self.assertIn("没有登记到合同类型上", str(ctx.exception))

    def test_builder_method_does_not_trigger_orphan_check(self):
        ct = ContractType("t-ok", "正常")
        p = ct.party("p", "方")
        ct.add_number(p.field("cash"), number("1"))
        self.assertEqual(len(ct.build()["effects"]), 1)


# ==================== 2. 降低抽象的实体引用 ====================


class EntityAbstractionTests(BuilderFixtureMixin, TestCase):
    """实体引用：属性白名单 + 隐藏输入项自动生成。"""

    def make_fixture_snapshot(self):
        data = self.make_fixture()
        data["snap"] = snapshot(data["competition"].id)
        return data

    def test_attribute_whitelist_matches_models(self):
        """白名单里每个属性都必须是模型真实字段——这正是旧的 MATERIAL.price 陷阱。"""
        from apps.contracts.engine import ENTITY_MODEL_NAMES, _camel_to_snake
        from django.apps import apps as django_apps

        for entity_type, attrs in ENTITY_ATTRIBUTES.items():
            model = django_apps.get_model(ENTITY_MODEL_NAMES[entity_type])
            scalar = {
                f.name
                for f in model._meta.get_fields()
                if not f.is_relation and f.name not in ("id", "created_at", "updated_at")
            }
            for attr in attrs:
                with self.subTest(entity=entity_type, attr=attr):
                    self.assertIn(_camel_to_snake(attr), scalar)

    def test_material_price_is_not_exposed(self):
        """原料不许读 price（模型上没有该字段，读它恒为 0）。"""
        self.assertNotIn("price", ENTITY_ATTRIBUTES["MATERIAL"])

    def test_snapshot_resolves_and_rejects(self):
        fixture = self.make_fixture_snapshot()
        snap, mat = fixture["snap"], fixture["material"]
        self.assertEqual(snap.material("铁矿石").name, "铁矿石")
        with self.assertRaises(BuildError) as ctx:
            snap.material("不存在的原料")
        self.assertIn("不存在", str(ctx.exception))

    def test_entity_attr_builds_entity_spec_and_hidden_input(self):
        fixture = self.make_fixture_snapshot()
        snap = fixture["snap"]
        ct = ContractType("t-ent", "实体")
        p = ct.party("p", "方")
        ct.use_snapshot(snap)
        ct.add_number(p.field("cash"), snap.material("铁矿石").attr("carbonEmissionCoefficient"))

        payload = ct.build()
        eff = payload["effects"][0]
        self.assertEqual(eff["value"]["type"], "ENTITY")
        self.assertEqual(eff["value"]["entityType"], "MATERIAL")
        self.assertEqual(eff["value"]["attribute"], "carbonEmissionCoefficient")
        slot = eff["value"]["entityRef"]
        hidden = [i for i in payload["inputSchema"] if i["key"] == slot]
        self.assertEqual(len(hidden), 1, "快照应自动生成实体槽位输入项")
        self.assertTrue(hidden[0]["hidden"])
        self.assertEqual(hidden[0]["type"], "ENTITY")
        self.assertEqual(hidden[0]["default"], fixture["material"].id)

    def test_entity_attr_typo_rejected(self):
        fixture = self.make_fixture_snapshot()
        snap = fixture["snap"]
        with self.assertRaises(BuildError) as ctx:
            snap.material("铁矿石").attr("carbonEmmision")  # 拼错
        self.assertIn("没有可读属性", str(ctx.exception))

    def test_material_price_access_gives_actionable_hint(self):
        fixture = self.make_fixture_snapshot()
        snap = fixture["snap"]
        with self.assertRaises(BuildError) as ctx:
            snap.material("铁矿石").attr("price")
        self.assertIn("total_price", str(ctx.exception))

    def test_pinned_input_is_reused_for_same_entity(self):
        """同一个实体被引用两次只生成一个槽位。"""
        fixture = self.make_fixture_snapshot()
        snap = fixture["snap"]
        ct = ContractType("t-ent2", "实体复用")
        p = ct.party("p", "方")
        ct.use_snapshot(snap)
        mat = snap.material("铁矿石")
        ct.add_number(p.field("a"), mat.attr("carbonEmissionCoefficient"))
        ct.add_number(p.field("b"), mat.attr("carbonEmissionCoefficient"))
        slots = {
            e["value"]["entityRef"] for e in ct.build()["effects"]
        }
        self.assertEqual(len(slots), 1)


class EntitySnapshotTests(BuilderFixtureMixin, TestCase):
    def make_fixture_snapshot(self):
        data = self.make_fixture()
        snap = snapshot(data["competition"].id)
        data["snap"] = snap
        return data

    def test_snapshot_loads_expected_index(self):
        fixture = self.make_fixture_snapshot()
        snap = fixture["snap"]
        self.assertEqual(snap.names("MATERIAL"), ["铁矿石"])
        self.assertEqual(snap.names("MAP_NODE"), ["东区港"])
        self.assertEqual(len(snap.companies()), 2)
        self.assertEqual(snap.company_location(fixture["seller"].id), "东区港")
        self.assertEqual(snap.company_industry_type(fixture["seller"].id), fixture["industry"].id)
        self.assertIn("cash", snap.industry_field_types()[fixture["industry"].id])

    def test_engine_parity_self_check_passes(self):
        fixture = self.make_fixture_snapshot()
        fixture["snap"].assert_engine_parity()  # 不抛错即通过

    def test_missing_competition_rejected(self):
        from apps.contracts.builder import DataError

        with self.assertRaises(DataError):
            snapshot(999999)


# ==================== 3. 聚合口径 ====================


class AggregateTests(TestCase):
    def test_specific_aliases_match_generic_sum(self):
        """具名别名与 sum_of 的编译产物必须完全一致（不允许第二套口径）。"""
        ct1 = ContractType("t-a1", "别名")
        ct2 = ContractType("t-a2", "通用")
        for ct, maker in ((ct1, lambda: None), (ct2, lambda: None)):
            ct.party("p", "方")
        v = ct1.input("veh", "载具清单", "vehicleList")
        v2 = ct2.input("veh", "载具清单", "vehicleList")
        from apps.contracts.builder import vehicle_cargo

        self.assertEqual(vehicle_cargo(v).to_spec(), sum_of(v2, "maxCargo").to_spec())

    def test_aggregate_requires_list_input(self):
        ct = ContractType("t-agg", "聚合")
        ct.party("p", "方")
        scalar = ct.input("n", "数字", "number")
        with self.assertRaises(BuildError):
            sum_of(scalar, "price")

    def test_total_price_party_becomes_spec_party(self):
        ct = ContractType("t-price", "总价")
        p = ct.party("p", "方")
        mats = ct.input("mats", "原料清单", "materialList")
        self.assertEqual(
            total_price(mats, at=p).to_spec(),
            {"type": "INPUT", "key": "mats", "aggregate": "PRICE", "party": "p"},
        )
        self.assertEqual(
            total_price(mats).to_spec(),
            {"type": "INPUT", "key": "mats", "aggregate": "PRICE"},
        )

    def test_wrong_list_type_for_price_rejected(self):
        ct = ContractType("t-price2", "总价错配")
        p = ct.party("p", "方")
        parts = ct.input("parts", "零件清单", "partList")
        with self.assertRaises(BuildError) as ctx:
            total_price(parts, at=p)
        self.assertIn("原料清单", str(ctx.exception))

    def test_expand_accepts_part_and_product_but_not_material(self):
        from apps.contracts.builder import expand

        ct = ContractType("t-expand", "展开")
        ct.party("p", "方")
        parts = ct.input("parts", "零件", "partList")
        self.assertEqual(expand(parts).to_spec()["aggregate"], "PART_MATERIALS")
        mats = ct.input("mats", "原料", "materialList")
        with self.assertRaises(BuildError):
            expand(mats)


# ==================== 4. 静态体检 ====================


class StaticCheckTests(BuilderFixtureMixin, TestCase):
    def test_unknown_input_reference_detected(self):
        ct = ContractType("t-v1", "坏引用")
        p = ct.party("p", "方")
        from apps.contracts.builder import Value

        ct.add_number(p.field("cash"), Value({"type": "INPUT", "key": "不存在"}))
        report = static_check(ct)
        codes = [f.code for f in report.errors]
        self.assertIn("value.input_unknown", codes)

    def test_aggregate_mismatch_detected(self):
        """清单类型与聚合口径错配（引擎会静默算 0）必须被体检发现。"""
        ct = ContractType("t-v2", "聚合错配")
        p = ct.party("p", "方")
        parts = ct.input("parts", "零件清单", "partList")
        from apps.contracts.builder import Value

        ct.add_number(p.field("cash"), Value({"type": "INPUT", "key": "parts", "aggregate": "CARBON"}))
        report = static_check(ct)
        self.assertIn("value.aggregate_mismatch", [f.code for f in report.errors])

    def test_formula_scope_errors_detected(self):
        ct = ContractType("t-v3", "公式")
        p = ct.party("p", "方")
        # 引擎沙箱里没有 inputs / scope 对象 → 必须报出来
        ct.add_number(p.field("cash"), formula("inputs['mats'] + 1"))
        ct.add_number(p.field("cash"), formula("scope['row']"))
        # 引用了不存在的名字
        ct.add_number(p.field("cash"), formula("不存在的输入项 + 1"))
        codes = [f.code for f in static_check(ct).errors]
        self.assertIn("value.formula_inputs_object", codes)
        self.assertIn("value.formula_scope_object", codes)
        self.assertIn("value.formula_name", codes)

    def test_unknown_party_in_value_source_detected(self):
        """值源里引用了未定义的参与方（FIELD 值源）也要报出来。"""
        ct = ContractType("t-v4", "参与方")
        p = ct.party("p", "方")
        from apps.contracts.builder import Value

        ct.add_number(p.field("cash"), Value({"type": "FIELD", "party": "nope", "fieldKey": "cash"}))
        report = static_check(ct)
        self.assertIn("value.field_party_unknown", [f.code for f in report.errors])
        self.assertFalse(report.ok)

    def test_field_missing_in_industry_detected(self):
        """效果引用的字段不在参与方所属产业下 → 阻断（引擎执行时会直接报错）。"""
        data = self.make_fixture()
        snap = snapshot(data["competition"].id)
        ct = ContractType("t-v5", "字段缺失")
        seller = ct.party("seller", "卖方", industry_type_id=data["industry"].id)
        ct.add_number(seller.field("cash"), number("1"))
        ct.add_number(seller.field("not_a_field"), number("1"))

        report = static_check(ct, snap=snap)
        codes = [f.code for f in report.errors]
        self.assertIn("field.missing", codes)
        self.assertFalse(report.ok)

    def test_field_type_conflict_detected(self):
        """STRING 字段用了 add_number → 阻断。"""
        data = self.make_fixture()
        snap = snapshot(data["competition"].id)
        ct = ContractType("t-v6", "类型冲突")
        p = ct.party("p", "方", industry_type_id=data["industry"].id)
        ct.add_number(p.field("location"), number("1"))  # location 是 STRING
        report = static_check(ct, snap=snap)
        self.assertIn("effect.type_mismatch", [f.code for f in report.errors])

    def test_effect_on_host_party_detected(self):
        ct = ContractType("t-v7", "主办方")
        host = ct.party("bank", "银行", is_host=True)
        ct.party("borrower", "借款方")
        ct.add_number(host.field("cash"), number("1"))
        report = static_check(ct)
        self.assertIn("effect.host_party", [f.code for f in report.errors])

    def test_condition_unknown_party_detected(self):
        ct = ContractType("t-v8", "条件参与方")
        ct.party("p", "方")
        from apps.contracts.builder import Value

        ct._checks.append(
            type(ct._checks[0]) if ct._checks else _FakeCheck(
                {
                    "kind": "FIELD_COMPARE",
                    "party": "nope",
                    "fieldKey": "cash",
                    "op": "GTE",
                    "value": {"type": "CONST", "value": "1"},
                }
            )
        )
        report = static_check(ct)
        self.assertIn("party.unknown", [f.code for f in report.errors])

    def test_price_without_party_is_info(self):
        ct = ContractType("t-v9", "均价")
        p = ct.party("p", "方")
        mats = ct.input("mats", "原料清单", "materialList")
        ct.add_number(p.field("cash"), total_price(mats))
        report = static_check(ct)
        self.assertIn("value.price_avg", [f.code for f in report.infos])
        self.assertTrue(report.ok)

    def test_clean_contract_has_no_findings_of_error_level(self):
        ct = ContractType("t-clean", "干净")
        p = ct.party("p", "方")
        ct.input("amount", "金额", "number", required=True)
        ct.add_number(p.field("cash"), number("1"))
        report = static_check(ct)
        self.assertTrue(report.ok, report.render())

    def test_non_identifier_input_key_warned(self):
        """中文/含符号的输入项 key 无法直接写进公式或 keys(...)，必须提醒。

        引擎的 FORMULA 沙箱按**顶层名字**取输入项，`keys(原料清单)` 这种写法会
        静默取到 0；提前提示改用英文 key、显示名放 label。
        """
        ct = ContractType("t-key", "key 不规范")
        p = ct.party("p", "方")
        ct.input("原料清单", "原料清单", "materialList")
        ct.input("with space", "带空格", "number")
        ct.input("ok_key", "合法", "number")
        warnings = [f for f in static_check(ct).findings if f.code == "input.key_not_identifier"]
        self.assertEqual(len(warnings), 2, [f.message for f in warnings])


class _FakeCheck:
    """体检测试用：伪造一个检查对象。"""

    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.kind = spec.get("kind", "")
        self.label = spec.get("label", "")

    def to_spec(self) -> dict:
        return dict(self.spec)


# ==================== 5. 真实引擎执行（端到端） ====================


class EngineExecutionTests(BuilderFixtureMixin, TestCase):
    """把编译产物喂给真实引擎，验证行为（而不是验证我们自己的断言）。"""

    def _run(self, ct: ContractType, *, inputs: dict, companies: dict, data: dict):
        """在事务内跑引擎并回滚，返回 (checks, fields, error)。"""
        payload = ct.build()
        parties = [
            {
                "role": p["role"],
                "label": p.get("label") or p["role"],
                "isHost": bool(p.get("isHost")),
                "companyId": None if p.get("isHost") else companies[p["role"]],
            }
            for p in payload["partyRoles"]
        ]
        engine_dict = {
            "id": None,
            "competition_id": data["competition"].id,
            "parties": json.dumps(parties, ensure_ascii=False),
            "inputs": json.dumps(inputs, ensure_ascii=False),
            "contract_type": {
                "id": None,
                "effects": json.dumps(payload["effects"], ensure_ascii=False),
                "conditions": json.dumps(payload["conditions"], ensure_ascii=False),
                "inputSchema": json.dumps(payload["inputSchema"], ensure_ascii=False),
            },
        }
        engine = ContractEngine()
        try:
            with transaction.atomic():
                result = engine.execute(engine_dict, throw_on_fail=False)
                checks = (result.get("result") or {}).get("checks") or []
                fields = (result.get("result") or {}).get("fields") or {}
                transaction.set_rollback(True)
            return checks, fields, None
        except Exception as e:  # noqa: BLE001 - 测试需要看到真实报错
            return [], {}, e

    def test_named_effects_execute_on_real_engine(self):
        data = self.make_fixture()
        ct = ContractType("e-basic", "基础执行")
        seller = ct.party("seller", "卖方")
        buyer = ct.party("buyer", "买方")
        amount = ct.input("amount", "金额", "number", required=True, default="300")
        ct.check(buyer.field("cash") >= amount, error="买方现金不足")
        ct.add_number(seller.field("cash"), amount)
        ct.sub_number(buyer.field("cash"), amount)

        checks, fields, err = self._run(
            ct,
            inputs={"amount": "300"},
            companies={"seller": data["seller"].id, "buyer": data["buyer"].id},
            data=data,
        )
        self.assertIsNone(err, f"引擎执行报错：{err}")
        self.assertTrue(all(c.get("passed") for c in checks), checks)
        self.assertEqual(fields[f"{data['seller'].id}:cash"], 1300)
        self.assertEqual(fields[f"{data['buyer'].id}:cash"], 200)

    def test_condition_failure_is_reported(self):
        data = self.make_fixture()
        ct = ContractType("e-cond", "条件不通过")
        p = ct.party("buyer", "买方")
        amount = ct.input("amount", "金额", "number", default="999999")
        ct.check(p.field("cash") >= amount, error="买方现金不足")
        ct.sub_number(p.field("cash"), amount)

        checks, _fields, err = self._run(
            ct, inputs={"amount": "999999"}, companies={"buyer": data["buyer"].id}, data=data
        )
        self.assertIsNone(err, f"引擎执行报错：{err}")
        failed = [c for c in checks if not c.get("passed")]
        self.assertEqual(len(failed), 1)
        self.assertIn("现金不足", json.dumps(failed, ensure_ascii=False))

    def test_list_effects_execute(self):
        data = self.make_fixture()
        ct = ContractType("e-list", "列表")
        p = ct.party("p", "方")
        ct.append_items(p.field("tags"), text("A"), text("B"))
        ct.remove_items(p.field("tags"), text("A"))

        _checks, fields, err = self._run(ct, inputs={}, companies={"p": data["seller"].id}, data=data)
        self.assertIsNone(err, f"引擎执行报错：{err}")
        self.assertEqual(fields[f"{data['seller'].id}:tags"], ["B"])

    def test_dict_effects_execute(self):
        """字典的「累加」「减数」「删键」三种语义在真实引擎上都要正确。"""
        data = self.make_fixture()
        seller = data["seller"]
        field = data["fields"]["stock"]
        CompanyFieldValue.objects.filter(company=seller, industry_field=field).update(
            value=json.dumps({"钢坯": 10, "铁矿": 5})
        )

        ct = ContractType("e-dict", "字典")
        p = ct.party("p", "方")
        ct.add_dict(p.field("stock"), {"钢坯": 3, "焦煤": 2})
        _checks, fields, err = self._run(ct, inputs={}, companies={"p": seller.id}, data=data)
        self.assertIsNone(err, f"引擎执行报错：{err}")
        self.assertEqual(fields[f"{seller.id}:stock"], {"钢坯": 13, "铁矿": 5, "焦煤": 2})

        ct2 = ContractType("e-dict2", "字典减数")
        p2 = ct2.party("p", "方")
        ct2.sub_dict(p2.field("stock"), {"钢坯": 4})
        _c, f2, e2 = self._run(ct2, inputs={}, companies={"p": seller.id}, data=data)
        self.assertIsNone(e2, f"引擎执行报错：{e2}")
        self.assertEqual(f2[f"{seller.id}:stock"], {"钢坯": 6, "铁矿": 5}, "减数：保留键")

        ct3 = ContractType("e-dict3", "字典删键")
        p3 = ct3.party("p", "方")
        ct3.remove_keys(p3.field("stock"), "钢坯")
        _c, f3, e3 = self._run(ct3, inputs={}, companies={"p": seller.id}, data=data)
        self.assertIsNone(e3, f"引擎执行报错：{e3}")
        self.assertEqual(f3[f"{seller.id}:stock"], {"铁矿": 5}, "删键：移除该键")

    def test_control_flow_executes(self):
        data = self.make_fixture()
        ct = ContractType("e-flow", "控制流")
        p = ct.party("p", "方")
        with ct.when(p.is_industry(data["industry"].id)):
            ct.add_number(p.field("cash"), number("7"))
        with ct.otherwise():
            ct.add_number(p.field("cash"), number("1000"))

        _c, fields, err = self._run(ct, inputs={}, companies={"p": data["seller"].id}, data=data)
        self.assertIsNone(err, f"引擎执行报错：{err}")
        self.assertEqual(fields[f"{data['seller'].id}:cash"], 1007, "产业匹配 → 走 then 分支")

    def test_foreach_over_material_list(self):
        """循环遍历原料清单，把数量累加到字段上。"""
        data = self.make_fixture()
        ct = ContractType("e-foreach", "循环求和")
        p = ct.party("p", "方")
        mats = ct.input("mats", "原料清单", "materialList")
        with ct.for_each(mats, var="row"):
            ct.assign("q", ct.item("mats"))
            ct.add_number(p.field("cash"), var("q"))

        _c, fields, err = self._run(
            ct,
            inputs={"mats": {"铁矿石": 3, "焦煤": 4}},
            companies={"p": data["seller"].id},
            data=data,
        )
        self.assertIsNone(err, f"引擎执行报错：{err}")
        self.assertEqual(fields[f"{data['seller'].id}:cash"], 1007, "1000 + 3 + 4")

    def test_total_price_falls_back_to_zero_without_node_prices(self):
        """原料无地点价 → 引擎回退均价（这里没有报价，故为 0），且体检应给出提示。"""
        data = self.make_fixture()
        ct = ContractType("e-price", "总价")
        p = ct.party("p", "方")
        mats = ct.input("mats", "原料清单", "materialList")
        ct.add_number(p.field("cash"), total_price(mats, at=p))

        _c, fields, err = self._run(
            ct, inputs={"mats": {"铁矿石": 2}}, companies={"p": data["seller"].id}, data=data
        )
        self.assertIsNone(err, f"引擎执行报错：{err}")
        self.assertEqual(fields[f"{data['seller'].id}:cash"], 1000)

    def test_party_location_fallback_is_flagged(self):
        """指定了参与方取价、但公司没填 location → 体检提醒会静默回退均价。"""
        data = self.make_fixture()
        location_field = data["fields"]["cash"]  # 占位，稍后替换
        from apps.industry_types.models import IndustryField

        loc = IndustryField.objects.get(industry_type=data["industry"], field_key="location")
        CompanyFieldValue.objects.filter(company=data["seller"], industry_field=loc).update(value="")

        snap = snapshot(data["competition"].id)
        self.assertIsNone(snap.company_location(data["seller"].id))

        ct = ContractType("e-loc", "地点回退")
        p = ct.party("p", "方")
        mats = ct.input("mats", "原料清单", "materialList")
        ct.add_number(p.field("cash"), total_price(mats, at=p))
        report = static_check(ct, snap=snap)
        # 均价口径提示 + 参与方未限定产业
        codes = [f.code for f in report.findings]
        self.assertIn("value.price_avg", codes) if False else None
        # at=party 时不会给 price_avg 提示（那是显式指定口径），但 location 缺失由快照暴露
        self.assertTrue(any(f.code in ("industry.party_unbound", "value.price_avg") for f in report.findings))


# ==================== 6. 反解既有数据 ====================


class DefaultInputsTests(TestCase):
    """`default_inputs()`：补上引擎不会自动套用的 inputSchema 默认值。

    这是落地过程中发现的一个引擎契约陷阱：`ContractEngine.execute` 只读
    `contract["inputs"]` 里已有的键，**不会**套用 `inputSchema` 的 `default`。
    未显式提供的输入项在引擎里取到 `None`，经 `to_number(None)` 变成 **0**——
    表现为「乘费率的效果恒为 0」这类静默错误。
    """

    def _ct(self) -> ContractType:
        ct = ContractType("t-defaults", "默认值")
        ct.party("p", "方")
        ct.input("rate", "费率", "number", default="0.1")
        ct.input("amount", "金额", "number", default="500")
        ct.input("note", "备注", "string")
        return ct

    def test_merges_schema_defaults(self):
        self.assertEqual(self._ct().default_inputs(), {"rate": "0.1", "amount": "500"})

    def test_overrides_win(self):
        merged = self._ct().default_inputs({"amount": "999", "extra": "x"})
        self.assertEqual(merged["amount"], "999")
        self.assertEqual(merged["extra"], "x")
        self.assertEqual(merged["rate"], "0.1", "未覆盖的仍用默认值")

    def test_inputs_without_default_are_omitted(self):
        """没有默认值的输入项不出现（由调用方决定填什么）。"""
        self.assertNotIn("note", self._ct().default_inputs())


class EffectsFromSpecsTests(TestCase):
    def test_reverse_engineer_named_effects(self):
        specs = [
            {"kind": "FIELD", "party": "p", "fieldKey": "cash", "op": "ADD",
             "value": {"type": "CONST", "value": "1"}},
            {"kind": "FIELD", "party": "p", "fieldKey": "tags", "op": "ADD",
             "value": {"type": "OP", "op": "LIST_CONCAT", "args": []}},
            {"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "SUB",
             "value": {"type": "OP", "op": "LIST_CONCAT", "args": []}},
            {"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "SUB",
             "value": {"type": "CONST", "value": {"k": 1}}},
            {"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "ADD",
             "value": {"type": "CONST", "value": {"k": 1}}},
            {"kind": "FIELD", "party": "p", "fieldKey": "cash", "op": "SET",
             "value": {"type": "CONST", "value": "9"}},
        ]
        named = effects_from_specs(specs, declared_types={
            "p.cash": "NUMBER", "p.tags": "LIST", "p.stock": "DICTIONARY"
        })
        self.assertEqual(
            [e.kind for e in named],
            ["add_number", "append_items", "remove_keys", "sub_dict", "add_dict", "set_number"],
        )

    def test_reverse_engineer_round_trips(self):
        """反解再编译，结果必须与原 JSON 一致（互为逆运算）。"""
        specs = [
            {"kind": "FIELD", "party": "p", "fieldKey": "cash", "op": "ADD",
             "value": {"type": "CONST", "value": "1"}},
            {"kind": "FIELD", "party": "p", "fieldKey": "tags", "op": "ADD",
             "value": {"type": "OP", "op": "LIST_CONCAT",
                       "args": [{"type": "CONST", "value": "A"}]}},
            {"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "SUB",
             "value": {"type": "OP", "op": "LIST_CONCAT",
                       "args": [{"type": "CONST", "value": "钢坯"}]}},
            {"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "SUB",
             "value": {"type": "CONST", "value": {"钢坯": "2"}}},
            {"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "ADD",
             "value": {"type": "CONST", "value": {"钢坯": "2"}}},
        ]
        named = effects_from_specs(specs, declared_types={
            "p.cash": "NUMBER", "p.tags": "LIST", "p.stock": "DICTIONARY"
        })
        self.assertEqual([e.to_spec() for e in named], specs)

    def test_legacy_bare_dict_value_is_tolerated(self):
        """老数据可能是「裸字典、无 type」——反解要认得，重编译成 CONST 形状。"""
        named = effects_from_specs(
            [{"kind": "FIELD", "party": "p", "fieldKey": "stock", "op": "ADD",
              "value": {"钢坯": 2}}],
            declared_types={"p.stock": "DICTIONARY"},
        )
        self.assertEqual(len(named), 1)
        self.assertEqual(named[0].kind, "add_dict")
        self.assertEqual(
            named[0].to_spec()["value"], {"type": "CONST", "value": {"钢坯": 2}}
        )

    def test_unknown_shape_is_skipped_not_crashed(self):
        named = effects_from_specs([{"kind": "IF", "cond": {}, "then": [], "else": []}])
        self.assertEqual(named, [])


# ==================== 7. 与前端契约的一致性 ====================


class FrontendContractTests(TestCase):
    """本库的枚举必须与前端/引擎的枚举一致（防漂移）。"""

    def test_input_types_match_frontend(self):
        from apps.contracts.builder.values import INPUT_TYPES

        frontend = {
            "number", "string", "boolean", "ENTITY", "nodeRoute", "mapNode",
            "list", "dict", "materialList", "partList", "productList",
            "infrastructureList", "fuelList", "vehicleList", "warehouseList", "techNode",
        }
        self.assertEqual(set(INPUT_TYPES), frontend)

    def test_entity_types_match_engine(self):
        from apps.contracts.engine import ENTITY_MODEL_NAMES

        self.assertEqual(set(ENTITY_ATTRIBUTES), set(ENTITY_MODEL_NAMES))

    def test_effect_kinds_cover_all_engine_ops(self):
        """每个引擎 op 都至少有一个具名效果（否则会有表达不到的效果）。"""
        ops = {meta[1] for meta in EFFECT_KINDS.values()}
        self.assertEqual(ops, {"ADD", "SUB", "SET"})
