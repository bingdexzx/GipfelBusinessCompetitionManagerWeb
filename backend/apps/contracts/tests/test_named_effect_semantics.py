"""逐条验证 11 种具名效果的**真实引擎语义**与其名字一致。

为什么单独写一组：本库的核心主张是「效果名就说明它做什么」。
只断言编译出的 JSON 形状是不够的——必须把 JSON 喂给真正的引擎，
看字段**实际变成什么**。这组测试就是这句话的证明。

对照表（左 = 本库的效果名，右 = 引擎的实际行为）：

    add_number      数值相加
    sub_number      数值相减
    set_number      数值覆盖
    append_items    列表追加（去重）
    remove_items    列表按元素移除
    set_items       列表整体覆盖（含清空）
    add_dict        字典逐键累加（保留独有键）
    sub_dict        字典逐键相减（保留键）
    remove_keys     字典删键（移除键本身）
    set_dict        字典整体覆盖
    set_value       任意类型覆盖（字符串/布尔）
"""

from __future__ import annotations

import json

from django.db import transaction
from django.test import TestCase

from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.contracts.builder import ContractType, number, text
from apps.contracts.engine import ContractEngine
from apps.industry_types.models import IndustryField, IndustryType


class NamedEffectSemanticsTests(TestCase):
    """每个具名效果都跑一遍真实引擎，断言字段落库结果。"""

    def setUp(self):
        self.comp = Competition.objects.create(name="具名效果语义测试")
        self.industry = IndustryType.objects.create(code=9101, name="语义产业")

        self.number_field = IndustryField.objects.create(
            industry_type=self.industry, name="数值", field_key="num", field_type="NUMBER"
        )
        self.list_field = IndustryField.objects.create(
            industry_type=self.industry, name="列表", field_key="items", field_type="LIST",
            config=json.dumps({"itemType": "STRING"}),
        )
        self.dict_field = IndustryField.objects.create(
            industry_type=self.industry, name="字典", field_key="bag", field_type="DICTIONARY",
            config=json.dumps({"valueType": "NUMBER"}),
        )
        self.string_field = IndustryField.objects.create(
            industry_type=self.industry, name="文本", field_key="label", field_type="STRING"
        )
        self.bool_field = IndustryField.objects.create(
            industry_type=self.industry, name="布尔", field_key="flag", field_type="BOOLEAN"
        )
        self.company = Company.objects.create(
            competition=self.comp, name="语义公司", industry_type=self.industry
        )

    # ---------- 夹具 ----------

    def _seed(self, **values) -> None:
        """给公司写入初始字段值。键是 field_key。"""
        by_key = {
            "num": self.number_field,
            "items": self.list_field,
            "bag": self.dict_field,
            "label": self.string_field,
            "flag": self.bool_field,
        }
        CompanyFieldValue.objects.filter(company=self.company).delete()
        for key, value in values.items():
            CompanyFieldValue.objects.create(
                company=self.company,
                industry_field=by_key[key],
                value=value if isinstance(value, str) else json.dumps(value),
            )

    def _run(self, ct: ContractType, *, inputs: dict | None = None) -> dict:
        """跑真实引擎（事务回滚），返回 `{fieldKey: after}`。"""
        payload = ct.build()
        parties = [
            {
                "role": p["role"],
                "label": p.get("label") or p["role"],
                "isHost": bool(p.get("isHost")),
                "companyId": None if p.get("isHost") else self.company.id,
            }
            for p in payload["partyRoles"]
        ]
        engine_dict = {
            "id": None,
            "competition_id": self.comp.id,
            "parties": json.dumps(parties, ensure_ascii=False),
            "inputs": json.dumps(inputs or {}, ensure_ascii=False),
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
        prefix = f"{self.company.id}:"
        return {k[len(prefix):]: v for k, v in fields.items() if k.startswith(prefix)}

    def _ct(self) -> tuple[ContractType, object]:
        ct = ContractType("sem", "语义", enabled=True)
        return ct, ct.party("p", "方")

    # ---------- 数值 ----------

    def test_add_number(self):
        self._seed(num="100")
        ct, p = self._ct()
        ct.add_number(p.field("num"), number("25"))
        self.assertEqual(self._run(ct)["num"], 125)

    def test_add_number_with_expression(self):
        """值层表达式（a + b）落到引擎后仍是正确的加法。"""
        self._seed(num="100")
        ct, p = self._ct()
        a = ct.input("a", "A", "number")
        b = ct.input("b", "B", "number")
        ct.add_number(p.field("num"), a + b)
        self.assertEqual(self._run(ct, inputs={"a": "7", "b": "5"})["num"], 112)

    def test_sub_number(self):
        self._seed(num="100")
        ct, p = self._ct()
        ct.sub_number(p.field("num"), number("30"))
        self.assertEqual(self._run(ct)["num"], 70)

    def test_set_number(self):
        self._seed(num="100")
        ct, p = self._ct()
        ct.set_number(p.field("num"), number("7"))
        self.assertEqual(self._run(ct)["num"], 7)

    # ---------- 列表 ----------

    def test_append_items_adds_and_dedupes(self):
        """追加：新元素进入、已存在的不重复（引擎的 ADD 去重语义）。"""
        self._seed(items=["A"])
        ct, p = self._ct()
        ct.append_items(p.field("items"), text("B"), text("A"))
        self.assertEqual(self._run(ct)["items"], ["A", "B"])

    def test_append_items_single(self):
        self._seed(items=[])
        ct, p = self._ct()
        ct.append_items(p.field("items"), text("X"))
        self.assertEqual(self._run(ct)["items"], ["X"])

    def test_remove_items_removes_by_element(self):
        """移除：按键元素删除，其余保留。"""
        self._seed(items=["A", "B", "C"])
        ct, p = self._ct()
        ct.remove_items(p.field("items"), text("B"))
        self.assertEqual(self._run(ct)["items"], ["A", "C"])

    def test_set_items_replaces_and_clears(self):
        self._seed(items=["A", "B"])
        ct, p = self._ct()
        ct.set_items(p.field("items"), [text("Z")])
        self.assertEqual(self._run(ct)["items"], ["Z"])

        ct2, p2 = self._ct2()
        ct2.set_items(p2.field("items"), [])
        self.assertEqual(self._run(ct2)["items"], [], "set_items([]) 应清空列表")

    def _ct2(self) -> tuple[ContractType, object]:
        ct = ContractType("sem2", "语义2")
        return ct, ct.party("p", "方")

    # ---------- 字典 ----------

    def test_add_dict_merges_and_keeps_others(self):
        """累加：共有键相加、独有键保留（引擎的逐键相加语义）。"""
        self._seed(bag={"钢坯": 10, "铁矿": 5})
        ct, p = self._ct()
        ct.add_dict(p.field("bag"), {"钢坯": 3, "焦煤": 2})
        self.assertEqual(self._run(ct)["bag"], {"钢坯": 13, "铁矿": 5, "焦煤": 2})

    def test_sub_dict_subtracts_and_keeps_keys(self):
        """减数：共有键相减、**键仍在**、独有键保留——与「删键」完全不同。"""
        self._seed(bag={"钢坯": 10, "铁矿": 5})
        ct, p = self._ct()
        ct.sub_dict(p.field("bag"), {"钢坯": 4})
        self.assertEqual(self._run(ct)["bag"], {"钢坯": 6, "铁矿": 5})

    def test_remove_keys_removes_key_itself(self):
        """删键：键被移除（不是减到 0）。"""
        self._seed(bag={"钢坯": 10, "铁矿": 5})
        ct, p = self._ct()
        ct.remove_keys(p.field("bag"), "钢坯")
        self.assertEqual(self._run(ct)["bag"], {"铁矿": 5})

    def test_remove_keys_multiple(self):
        self._seed(bag={"A": 1, "B": 2, "C": 3})
        ct, p = self._ct()
        ct.remove_keys(p.field("bag"), "A", "C")
        self.assertEqual(self._run(ct)["bag"], {"B": 2})

    def test_set_dict_replaces(self):
        self._seed(bag={"A": 1})
        ct, p = self._ct()
        ct.set_dict(p.field("bag"), {"Z": 9})
        self.assertEqual(self._run(ct)["bag"], {"Z": 9})

    # ---------- 任意类型 ----------

    def test_set_value_string(self):
        self._seed(label="旧")
        ct, p = self._ct()
        ct.set_value(p.field("label"), text("新"))
        self.assertEqual(self._run(ct)["label"], "新")

    def test_set_value_dynamic_input(self):
        """动态值（输入项）也能正确写入。"""
        self._seed(label="旧")
        ct, p = self._ct()
        v = ct.input("v", "值", "string")
        ct.set_value(p.field("label"), v)
        self.assertEqual(self._run(ct, inputs={"v": "来自输入"})["label"], "来自输入")

    # ---------- 组合：字典的三种语义互不串味 ----------

    def test_three_dict_semantics_do_not_bleed(self):
        """同一初始字典上分别跑三种语义，结果必须两两不同。"""
        self._seed(bag={"钢坯": 10})

        ct_add, p_add = self._ct()
        ct_add.add_dict(p_add.field("bag"), {"钢坯": 3})
        add_result = self._run(ct_add)["bag"]

        ct_sub, p_sub = self._ct2()
        ct_sub.sub_dict(p_sub.field("bag"), {"钢坯": 3})
        sub_result = self._run(ct_sub)["bag"]

        ct_rm, p_rm = self._ct3()
        ct_rm.remove_keys(p_rm.field("bag"), "钢坯")
        rm_result = self._run(ct_rm)["bag"]

        self.assertEqual(add_result, {"钢坯": 13})
        self.assertEqual(sub_result, {"钢坯": 7})
        self.assertEqual(rm_result, {})
        self.assertNotEqual(add_result, sub_result)
        self.assertNotEqual(sub_result, rm_result)

    def _ct3(self) -> tuple[ContractType, object]:
        ct = ContractType("sem3", "语义3")
        return ct, ct.party("p", "方")

    # ---------- 循环：字典清单要包 keys()，列表输入直接遍历 ----------

    def test_for_each_over_dict_shaped_list_input(self):
        """清单类输入（值是 {名称: 数量} 字典）→ 循环变量是名称，数量用 item() 取。

        引擎的 FOREACH 只遍历列表（`lst = arr if isinstance(arr, list) else []`），
        所以本库对这类输入自动包一层 `keys(...)`。
        """
        self._seed(num="0")
        ct, p = self._ct()
        mats = ct.input("mats", "原料清单", "materialList")
        with ct.for_each(mats, var="row"):
            ct.assign("q", ct.item("mats"))
            ct.add_number(p.field("num"), __import__("apps.contracts.builder", fromlist=["var"]).var("q"))

        result = self._run(ct, inputs={"mats": {"铁矿石": 3, "焦煤": 4}})
        self.assertEqual(result["num"], 7, "3 + 4")

    def test_for_each_over_plain_list_input(self):
        """`list` 型输入的值本身就是列表 → 直接遍历，元素就是值。

        注意：`list` 型输入不能用 `ct.item()`（那是给「名称→数量」字典用的）。
        """
        self._seed(num="0")
        ct, p = self._ct()
        nums = ct.input("nums", "数字列表", "list")
        with ct.for_each(nums, var="v"):
            ct.add_number(p.field("num"), __import__("apps.contracts.builder", fromlist=["var"]).var("v"))

        result = self._run(ct, inputs={"nums": [1, 2, 3]})
        self.assertEqual(result["num"], 6)
        eff = ct.build()["effects"][0]
        self.assertEqual(eff["items"], {"type": "INPUT", "key": "nums"}, "列表型输入不包 keys()")
