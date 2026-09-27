# -*- coding: utf-8 -*-
"""合同删除回滚端到端测试。运行：cd backend && python manage.py test tests.test_contract_revert -v2"""
from django.test import TransactionTestCase
from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.contracts.models import Contract, ContractFieldEffect, ContractType
from apps.contracts.engine import ContractEngine
from apps.industry_types.models import IndustryField, IndustryType


class ContractRevertTest(TransactionTestCase):

    def setUp(self):
        self.engine = ContractEngine()
        self.comp = Competition.objects.create(name="测试比赛")
        self.ind_type = IndustryType.objects.create(name="制造业", code=1)
        self.field_revenue = IndustryField.objects.create(
            industry_type=self.ind_type, name="营收", field_key="revenue",
            field_type="NUMBER", default_value="0",
        )
        self.field_inventory = IndustryField.objects.create(
            industry_type=self.ind_type, name="库存", field_key="inventory",
            field_type="DICTIONARY", config='{"entries":[],"valueType":"NUMBER"}',
            default_value="{}",
        )
        self.company = Company.objects.create(
            name="测试公司", industry_type=self.ind_type, competition=self.comp,
        )
        self.ct = ContractType.objects.create(
            key="test-contract", name="测试合同类型", effects="[]", conditions="[]",
        )

    def _make_contract(self, status="EXECUTED"):
        return Contract.objects.create(
            competition=self.comp, contract_type=self.ct, name="测试合同",
            status=status,
            parties='[{"role":"buyer","companyId":' + str(self.company.id) + '}]',
            inputs="{}",
        )

    def _set_field(self, value, field=None):
        f = field or self.field_revenue
        fv, created = CompanyFieldValue.objects.get_or_create(
            company=self.company, industry_field=f,
            defaults={"value": value, "version": 1},
        )
        if not created:
            fv.value = value
            fv.version = (fv.version or 0) + 1
            fv.save()

    def _get_field(self, field=None):
        fv = CompanyFieldValue.objects.filter(
            company=self.company, industry_field=field or self.field_revenue,
        ).first()
        return fv.value if fv else None

    def _create_effect(self, contract, field, op, value_raw, before_raw, after_raw):
        return ContractFieldEffect.objects.create(
            contract=contract, company_id=self.company.id,
            industry_field_id=field.id, field_key=field.field_key,
            field_name=field.name, op=op,
            value_raw=value_raw, before_raw=before_raw, after_raw=after_raw,
        )

    def _engine_dict(self, contract):
        return {
            "id": contract.id, "competition_id": self.comp.id,
            "parties": contract.parties, "inputs": contract.inputs,
            "executed_at": contract.executed_at, "created_at": contract.created_at,
            "contract_type": {"effects": "[]", "conditions": "[]", "inputSchema": "[]"},
        }

    def _revert_and_delete(self, contract):
        self.engine.revert_contract(self._engine_dict(contract))
        contract.delete()

    def test_basic_number_revert(self):
        """两合同叠加 → 删第一个 → 字段恢复。"""
        c1, c2 = self._make_contract(), self._make_contract()
        self._create_effect(c1, self.field_revenue, "ADD", "100", "0", "100")
        self._create_effect(c2, self.field_revenue, "ADD", "50", "100", "150")
        self._set_field("150")
        self._revert_and_delete(c1)
        self.assertEqual(self._get_field(), "50")

    def test_set_revert(self):
        """SET 覆盖 → 删 → 恢复原值。"""
        c1, c2 = self._make_contract(), self._make_contract()
        self._create_effect(c1, self.field_revenue, "SET", "100", "0", "100")
        self._create_effect(c2, self.field_revenue, "ADD", "50", "100", "150")
        self._set_field("150")
        self._revert_and_delete(c1)
        self.assertEqual(self._get_field(), "50")

    def test_dictionary_revert(self):
        """字典 ADD → 删 → 恢复。"""
        import json
        c1, c2 = self._make_contract(), self._make_contract()
        self._create_effect(c1, self.field_inventory, "ADD", '{"iron":100}', '{}', '{"iron":100}')
        self._create_effect(c2, self.field_inventory, "ADD", '{"copper":50}', '{"iron":100}', '{"iron":100,"copper":50}')
        CompanyFieldValue.objects.create(
            company=self.company, industry_field=self.field_inventory,
            value='{"iron":100,"copper":50}', version=2,
        )
        self._revert_and_delete(c1)
        self.assertEqual(json.loads(self._get_field(self.field_inventory)), {"copper": 50})

    def test_multi_field_revert(self):
        """一个合同改多个字段 → 删 → 全部恢复。"""
        import json
        c1 = self._make_contract()
        self._create_effect(c1, self.field_revenue, "ADD", "100", "0", "100")
        self._create_effect(c1, self.field_inventory, "ADD", '{"iron":50}', '{}', '{"iron":50}')
        self._set_field("100")
        CompanyFieldValue.objects.create(
            company=self.company, industry_field=self.field_inventory,
            value='{"iron":50}', version=1,
        )
        self._revert_and_delete(c1)
        self.assertEqual(self._get_field(), "0")
        self.assertEqual(json.loads(self._get_field(self.field_inventory)), {})

    def test_revert_to_default(self):
        """第一个合同 → 删 → 恢复 default_value。"""
        c1 = self._make_contract()
        self._create_effect(c1, self.field_revenue, "ADD", "100", "0", "100")
        self._set_field("100")
        self._revert_and_delete(c1)
        self.assertEqual(self._get_field(), "0")

    def test_terminate_then_delete_no_double_revert(self):
        """终止（回滚+清空 effects）→ 删除 → 不二次回滚。"""
        c1 = self._make_contract()
        self._create_effect(c1, self.field_revenue, "ADD", "100", "0", "100")
        self._set_field("100")
        self.engine.revert_contract(self._engine_dict(c1))
        ContractFieldEffect.objects.filter(contract=c1).delete()
        c1.status = "TERMINATED"
        c1.save(update_fields=["status"])
        self.assertEqual(self._get_field(), "0")
        self._set_field("200")
        c1.delete()
        self.assertEqual(self._get_field(), "200")

    def test_delete_no_effects(self):
        """DRAFT 合同删除 → 不影响字段值。"""
        self._set_field("500")
        self._make_contract(status="DRAFT").delete()
        self.assertEqual(self._get_field(), "500")

    def test_sub_revert(self):
        """SUB 操作回滚。"""
        self._set_field("100")
        c1 = self._make_contract()
        self._create_effect(c1, self.field_revenue, "SUB", "30", "100", "70")
        self._set_field("70")
        self._revert_and_delete(c1)
        self.assertEqual(self._get_field(), "100")

    def test_decimal_precision(self):
        """10^20 级别精度不丢失。"""
        big = "100000000000000000000"
        c1, c2 = self._make_contract(), self._make_contract()
        self._create_effect(c1, self.field_revenue, "ADD", big, "0", big)
        self._set_field(big)
        self._create_effect(c2, self.field_revenue, "ADD", "1", big, "100000000000000000001")
        self._set_field("100000000000000000001")
        self._revert_and_delete(c1)
        self.assertEqual(self._get_field(), "1")
