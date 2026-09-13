# -*- coding: utf-8 -*-
"""C-04 验证：合同执行（核心动账）必须有审计留痕。

缺陷（改前）：写操作审计只挂在 `post_save` / `post_delete` 信号上，而
`ContractExecuteAPIView.post` 用 `Contract.objects.filter(pk=pk).update(status="EXECUTED", ...)`
抢占状态（有意为之：原子抢占 + 只落一次副作用）—— `QuerySet.update()` **不触发
post_save**，于是「谁在什么时候把哪份合同执行了、落了哪些字段」在审计表里
一条都查不到（U01 C-04）。同类的 `.update()` 动账还包括股票推进轮次等。

改后：执行成功后显式补一条 `contracts:executed` 审计（含状态、输入、落账字段摘要），
与信号审计的 `{action: {...}}` 结构保持一致。
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.test import Client, TestCase

from apps.audit.models import AuditLog
from apps.auth.authentication import create_jwt
from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.contracts.models import Contract, ContractFieldEffect, ContractType
from apps.industry_types.models import IndustryField, IndustryType
from apps.regions.models import Region
from apps.users.models import User


class ContractExecuteAuditTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="C04 执行审计")
        self.region = Region.objects.create(competition=self.comp, name="C区")
        self.industry = IndustryType.objects.create(code=9701, name="C04产业")
        self.field = IndustryField.objects.create(
            industry_type=self.industry, name="现金", field_key="cash", field_type="NUMBER"
        )
        self.company = Company.objects.create(
            competition=self.comp, name="C04公司", industry_type=self.industry, region=self.region
        )
        CompanyFieldValue.objects.create(
            company=self.company, industry_field=self.field, value="1000"
        )

        self.ctype = ContractType.objects.create(
            key="c04-probe", name="C04 合同",
            party_count=1,
            party_roles=json.dumps([{"role": "counterparty", "label": "对手方"}]),
            input_schema="[]",
            effects=json.dumps([
                {
                    "kind": "FIELD",
                    "party": "counterparty",
                    "fieldKey": "cash",
                    "op": "ADD",
                    "value": {"type": "CONST", "value": 777},
                }
            ]),
            conditions="[]",
        )
        self.contract = Contract.objects.create(
            competition=self.comp, contract_type=self.ctype, name="C04 合同",
            status="PENDING_EXEC",
            parties=json.dumps([
                {
                    "role": "counterparty", "label": "对手方", "isHost": False,
                    "companyId": self.company.id, "contractNumber": "C04-001",
                }
            ], ensure_ascii=False),
            inputs="{}",
        )

        self.admin = User(username="c04-admin", role="SUPER_ADMIN", is_active=True)
        self.admin.set_password("AdminPw!123")
        self.admin.save()
        self.client = Client()
        self.token = create_jwt(self.admin)

    def _execute(self):
        return self.client.post(
            f"/api/contracts/{self.contract.pk}/execute",
            data={},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def _exec_logs(self):
        return AuditLog.objects.filter(action="contracts:executed", record_id=str(self.contract.pk))

    # ---------- 缺陷场景 ----------
    def test_execute_writes_audit_row(self):
        resp = self._execute()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, "EXECUTED")
        logs = self._exec_logs()
        self.assertEqual(logs.count(), 1, "合同执行必须留一条审计（QuerySet.update 不触发信号）")
        payload = json.loads(logs.first().changes)
        detail = payload["executed"]
        self.assertEqual(detail["status"], "EXECUTED")
        self.assertEqual(detail["fieldCount"], 1)
        self.assertEqual(detail["fields"][f"{self.company.id}:cash"], 1777)
        self.assertEqual(logs.first().competition_id, self.comp.id)
        self.assertEqual(logs.first().operator_name, "c04-admin")

    def test_audit_records_inputs_override(self):
        resp = self.client.post(
            f"/api/contracts/{self.contract.pk}/execute",
            data={"inputs": {"amount": 5}},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        detail = json.loads(self._exec_logs().first().changes)["executed"]
        self.assertIn("amount", detail["inputs"])

    # ---------- 功能不变 ----------
    def test_execution_effect_unchanged(self):
        """落账结果不变：字段 1000 → 1777，并写入契约效果行。"""
        self._execute()
        fv = CompanyFieldValue.objects.get(company=self.company, industry_field=self.field)
        self.assertEqual(Decimal(str(fv.value)), Decimal("1777"))
        self.assertEqual(ContractFieldEffect.objects.filter(contract_id=self.contract.pk).count(), 1)

    def test_signal_audit_still_works_for_create_and_terminate(self):
        """既有信号审计不受影响：合同创建/状态变更仍留痕。"""
        self.assertTrue(
            AuditLog.objects.filter(action="contracts:created", record_id=str(self.contract.pk)).exists(),
            "创建合同应仍由 post_save 信号审计",
        )
        self.contract.status = "TERMINATED"
        self.contract.save(update_fields=["status", "updated_at"])
        self.assertTrue(
            AuditLog.objects.filter(action="contracts:updated", record_id=str(self.contract.pk)).exists()
        )

    def test_double_execute_still_rejected_and_single_audit_row(self):
        self.assertEqual(self._execute().status_code, 200)
        resp = self._execute()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._exec_logs().count(), 1, "重复执行不得再写审计")
