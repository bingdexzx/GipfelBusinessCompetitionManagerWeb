# -*- coding: utf-8 -*-
"""D-07 验证：参与方 `companyId` 类型非法时，不得让合同列表/详情永久 500。

缺陷（改前）：
- `contracts/views.py::_enrich_party_companies()` 对参与方的 `companyId` 直接
  `int(p["companyId"])`，无类型校验；只要库里有一条 `"companyId": "abc"` 的合同
  （创建时 `validate_parties` 不校验类型，客户端可写入），该比赛的
  `GET /api/contracts` 与 `GET /api/contracts/:id` 就恒 500，
  contract_watcher 的合同轮询也随之失效。
- 序列化层同样不校验类型（`"companyId": "abc"` / `true` / `1.5` 均通过）。

改后：
- 序列化层强制 `companyId` 为整数（拒绝 bool/str/float，允许 null=未分配）；
- 读取路径用容错解析（非法值视为「未关联公司」），历史脏数据不再打挂接口。
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.companies.models import Company
from apps.competitions.models import Competition
from apps.contracts.models import ContractType
from apps.contracts.serializers import ContractSerializer
from apps.contracts.views import _enrich_party_companies, _get_party_company_ids
from apps.regions.models import Region


class PartyCompanyIdTypeTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="D07 脏数据比赛")
        self.region = Region.objects.create(competition=self.comp, name="D区")
        self.company = Company.objects.create(
            competition=self.comp, name="正常公司", region=self.region
        )
        self.ctype = ContractType.objects.create(
            key="d07-probe", name="D07 探测合同", party_count=1,
            party_roles=json.dumps([{"role": "counterparty", "label": "对手方"}]),
            input_schema="[]", effects="[]", conditions="[]",
        )

    # ---------- 缺陷场景：读取路径不得抛异常 ----------
    def test_enrich_tolerates_dirty_company_id_string(self):
        """改前：ValueError: invalid literal for int() with base 10: 'abc'。"""
        items = [
            {"id": 1, "parties": [{"role": "counterparty", "isHost": False, "companyId": "abc"}]}
        ]
        out = _enrich_party_companies(items)
        self.assertIsNone(out[0]["parties"][0]["companyName"])

    def test_enrich_tolerates_bool_and_float_and_null(self):
        items = [
            {
                "id": 1,
                "parties": [
                    {"role": "a", "isHost": False, "companyId": True},
                    {"role": "b", "isHost": False, "companyId": 1.5},
                    {"role": "c", "isHost": False, "companyId": None},
                    {"role": "d", "isHost": False, "companyId": [1]},
                    {"role": "e", "isHost": False, "companyId": {"id": 1}},
                ],
            }
        ]
        out = _enrich_party_companies(items)
        for p in out[0]["parties"]:
            self.assertIsNone(p["companyName"], p)

    def test_get_party_company_ids_tolerates_dirty_values(self):
        raw = json.dumps(
            [
                {"role": "a", "isHost": False, "companyId": "abc"},
                {"role": "b", "isHost": False, "companyId": "12"},
                {"role": "c", "isHost": True, "companyId": 99},
                {"role": "d", "isHost": False, "companyId": None},
            ]
        )
        self.assertEqual(_get_party_company_ids(raw), [12])

    # ---------- 缺陷场景：序列化层必须拒绝非法类型 ----------
    def _ser(self, company_id):
        return ContractSerializer(
            data={
                "competitionId": self.comp.id,
                "contractTypeId": self.ctype.id,
                "parties": [
                    {"role": "counterparty", "label": "对手方", "isHost": False, "companyId": company_id}
                ],
                "inputs": {},
            }
        )

    def test_serializer_rejects_string_company_id(self):
        s = self._ser("abc")
        self.assertFalse(s.is_valid(), "字符串 companyId 必须被拒绝")
        self.assertIn("parties", s.errors)

    def test_serializer_rejects_bool_company_id(self):
        self.assertFalse(self._ser(True).is_valid())

    def test_serializer_rejects_float_company_id(self):
        self.assertFalse(self._ser(1.5).is_valid())

    # ---------- 功能不变 ----------
    def test_valid_int_company_id_still_resolves_name(self):
        items = [
            {
                "id": 1,
                "parties": [{"role": "counterparty", "isHost": False, "companyId": self.company.id}],
            }
        ]
        out = _enrich_party_companies(items)
        self.assertEqual(out[0]["parties"][0]["companyName"], "正常公司")

    def test_serializer_accepts_int_and_null(self):
        self.assertTrue(self._ser(self.company.id).is_valid())
        self.assertTrue(self._ser(None).is_valid())

    def test_host_party_unaffected(self):
        items = [{"id": 1, "parties": [{"role": "host", "isHost": True, "companyId": "abc"}]}]
        out = _enrich_party_companies(items)
        self.assertIsNone(out[0]["parties"][0]["companyName"])
