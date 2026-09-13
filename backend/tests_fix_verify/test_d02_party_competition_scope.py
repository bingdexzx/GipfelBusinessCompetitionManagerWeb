# -*- coding: utf-8 -*-
"""D-02 验证：合同参与方公司必须按比赛隔离。

缺陷（改前）：`ContractSerializer.validate_parties` 只校验「至少一个非主办方」，
不校验 `companyId` 是否存在、是否属于本合同所属比赛；引擎 `_resolve_industry_field`
/ `read_company_field_value` / `_preload_field_cache` 也都按主键直接取公司、不过滤
`competition_id`。于是持 `contract:manage`+`contract:audit/execute` 的账号可构造
`parties=[{companyId: 别的比赛的公司}]` 并执行，从而**跨比赛改写他人公司的产业字段**。

改后：创建/更新合同时按比赛校验参与方公司；引擎在执行期再校验一次（读写两条路径）。
"""
from __future__ import annotations

import json

from django.db import transaction
from django.test import TestCase

from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.contracts.engine import ContractEngine
from apps.contracts.models import ContractType
from apps.contracts.serializers import ContractSerializer
from apps.industry_types.models import IndustryField, IndustryType
from apps.regions.models import Region


class PartyCompetitionScopeTests(TestCase):
    """两个比赛：本地比赛 A 与外部比赛 B（受害公司在 B）。"""

    def setUp(self):
        self.comp_a = Competition.objects.create(name="D02-比赛A")
        self.comp_b = Competition.objects.create(name="D02-比赛B")
        self.region_a = Region.objects.create(competition=self.comp_a, name="A区")
        self.region_b = Region.objects.create(competition=self.comp_b, name="B区")
        self.industry = IndustryType.objects.create(code=9301, name="D02产业")
        self.field = IndustryField.objects.create(
            industry_type=self.industry, name="现金", field_key="cash", field_type="NUMBER"
        )

        # A 比赛的公司（本地参与方）
        self.company_a = Company.objects.create(
            competition=self.comp_a, name="A公司", industry_type=self.industry, region=self.region_a
        )
        CompanyFieldValue.objects.create(
            company=self.company_a, industry_field=self.field, value="1000"
        )
        # B 比赛的公司（跨比赛受害方）
        self.company_b = Company.objects.create(
            competition=self.comp_b, name="B公司", industry_type=self.industry, region=self.region_b
        )
        self.fv_b = CompanyFieldValue.objects.create(
            company=self.company_b, industry_field=self.field, value="5000"
        )

        self.ctype = ContractType.objects.create(
            key="d02-probe", name="D02 探测合同", party_count=1,
            party_roles=json.dumps([{"role": "counterparty", "label": "对手方"}]),
            input_schema="[]", effects="[]", conditions="[]",
        )

    # ---------- 辅助 ----------
    def _engine_dict(self, company_id: int) -> dict:
        """一份「给对手方现金 +777」的合同（角色指向传入的公司）。"""
        return {
            "id": None,
            "competition_id": self.comp_a.id,
            "parties": json.dumps(
                [{"role": "counterparty", "label": "对手方", "isHost": False, "companyId": company_id}],
                ensure_ascii=False,
            ),
            "inputs": "{}",
            "contract_type": {
                "id": None,
                "effects": json.dumps(
                    [
                        {
                            "kind": "FIELD",
                            "party": "counterparty",
                            "fieldKey": "cash",
                            "op": "ADD",
                            "value": {"type": "CONST", "value": 777},
                        }
                    ],
                    ensure_ascii=False,
                ),
                "conditions": "[]",
                "inputSchema": "[]",
            },
        }

    def _run_engine(self, company_id: int):
        """跑真实引擎并回滚；返回 (error, 落账后的字段值 dict)。"""
        with transaction.atomic():
            try:
                result = ContractEngine().execute(self._engine_dict(company_id), throw_on_fail=False)
                fields = (result.get("result") or {}).get("fields") or {}
                err = None
            except Exception as e:  # noqa: BLE001 - 测试要看到真实报错
                fields, err = {}, e
            transaction.set_rollback(True)
        return err, fields

    def _value_of(self, company: Company) -> str:
        return CompanyFieldValue.objects.get(company=company, industry_field=self.field).value

    # ---------- 缺陷场景 ----------
    def test_engine_rejects_cross_competition_party(self):
        """改前：B 比赛公司的字段被写成 5777；改后：报错且分文未动。"""
        before = self._value_of(self.company_b)
        err, fields = self._run_engine(self.company_b.id)
        self.assertIsNotNone(err, "跨比赛参与方必须被引擎拒绝")
        self.assertIn("比赛", str(err))
        self.assertEqual(self._value_of(self.company_b), before, "跨比赛公司字段不得被改写")
        self.assertEqual(fields, {})

    def test_serializer_rejects_cross_competition_party(self):
        """改前：valid=True；改后：校验失败。"""
        ser = ContractSerializer(
            data={
                "competitionId": self.comp_a.id,
                "contractTypeId": self.ctype.id,
                "parties": [
                    {"role": "counterparty", "label": "对手方", "isHost": False, "companyId": self.company_b.id}
                ],
                "inputs": {},
            }
        )
        self.assertFalse(ser.is_valid(), "跨比赛参与方必须被序列化层拒绝")
        self.assertIn("parties", ser.errors)

    def test_cross_competition_read_path_is_blocked(self):
        """读路径同样按比赛隔离：FIELD 值源不得读到别的比赛公司的字段值。"""
        engine_dict = {
            "id": None,
            "competition_id": self.comp_a.id,
            "parties": json.dumps(
                [
                    {"role": "victim", "label": "外部公司", "isHost": False, "companyId": self.company_b.id},
                    {"role": "local", "label": "本地公司", "isHost": False, "companyId": self.company_a.id},
                ],
                ensure_ascii=False,
            ),
            "inputs": "{}",
            "contract_type": {
                "id": None,
                "effects": json.dumps(
                    [
                        {
                            "kind": "FIELD",
                            "party": "local",
                            "fieldKey": "cash",
                            "op": "SET",
                            # 值来源：读「外部公司」的 cash（改前会读到 5000）
                            "value": {"type": "FIELD", "party": "victim", "fieldKey": "cash"},
                        }
                    ],
                    ensure_ascii=False,
                ),
                "conditions": "[]",
                "inputSchema": "[]",
            },
        }
        before_a = self._value_of(self.company_a)
        with transaction.atomic():
            try:
                err = None
                ContractEngine().execute(engine_dict, throw_on_fail=False)
            except Exception as e:  # noqa: BLE001
                err = e
            transaction.set_rollback(True)
        self.assertIsNotNone(err, "跨比赛字段读取必须被拒绝")
        self.assertIn("比赛", str(err))
        self.assertEqual(self._value_of(self.company_a), before_a)
        self.assertEqual(self._value_of(self.company_b), "5000")

    # ---------- 功能不变 ----------
    def test_same_competition_party_still_works(self):
        """同比赛参与方：序列化通过、引擎照常落账（行为与改前一致）。"""
        ser = ContractSerializer(
            data={
                "competitionId": self.comp_a.id,
                "contractTypeId": self.ctype.id,
                "parties": [
                    {"role": "counterparty", "label": "对手方", "isHost": False, "companyId": self.company_a.id}
                ],
                "inputs": {},
            }
        )
        self.assertTrue(ser.is_valid(), ser.errors)

        err, fields = self._run_engine(self.company_a.id)
        self.assertIsNone(err)
        self.assertEqual(fields.get(f"{self.company_a.id}:cash"), 1777)

    def test_host_party_without_company_is_still_allowed(self):
        """主办方（isHost，无公司）不参与公司校验：单方合同仍可创建。"""
        ser = ContractSerializer(
            data={
                "competitionId": self.comp_a.id,
                "contractTypeId": self.ctype.id,
                "parties": [
                    {"role": "host", "label": "主办", "isHost": True},
                    {"role": "counterparty", "label": "对手方", "isHost": False, "companyId": self.company_a.id},
                ],
                "inputs": {},
            }
        )
        self.assertTrue(ser.is_valid(), ser.errors)
