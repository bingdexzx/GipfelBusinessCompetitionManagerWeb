# -*- coding: utf-8 -*-
"""R-03 验证：同一合同类型下的多份合同不得被合并成一条并改名。

缺陷：`_imp_contract_instances` 的判重键用了**合同类型的名字** `ct.name`，而不是行里的
`row["name"]`（实例名）。于是归档里同一 `contractTypeKey` 下的多份合同（这是常态：一个类型可预置
多份不同参与方/编号的合同）：
  - 第 1 份被创建成 `name = 合同类型名`（原实例名丢失）；
  - 第 2..N 份被 `filter(...).first()` 命中同一对象 → 全部 `skipped`，并把不同 `_id` 映射到同一个
    新合同；参与方映射结果算完直接丢弃（旧代码注释声称「只补参与方公司引用」，实际没有任何回写）。
结果：N 份合同变 1 份、名称被改写，比赛开局缺少可履约合同。

改后：判重键与实例名都用 `row["name"]`（类型名仅兜底）；覆盖模式下按归档更新
参与方/输入/状态，追加模式下同名同类型保留原数据。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r03_contract_instances_natural_key -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.companies.models import Company
from apps.competitions.models import Competition
from apps.contracts.models import Contract, ContractType
from apps.industry_types.models import IndustryType
from apps.preparation import archive
from apps.regions.models import Region
from apps.users.models import User


class ContractInstanceNaturalKeyTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R03-目标比赛")
        self.admin = User(
            username="r03-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R03Pw!123")
        self.admin.save()

        industry = IndustryType.objects.create(code=9402, name="R03产业")
        region = Region.objects.create(competition=self.comp, name="R03区")
        self.company = Company.objects.create(
            competition=self.comp, name="R03公司", industry_type=industry, region=region
        )
        self.ct = ContractType.objects.create(key="r03-type", name="R03-类型", party_count=1)

    def _payload(self, instances):
        return {
            "resources": {
                "contractTypes": {"rows": [{"_id": 1, "key": "r03-type", "name": "R03-类型"}]},
                "companies": {"rows": [{"_id": 1, "name": "R03公司", "industryTypeCode": 9402}]},
                "contractInstances": {"rows": instances},
            }
        }

    def _instance(self, old_id: int, name: str):
        return {
            "_id": old_id,
            "name": name,
            "contractTypeId": 1,
            "contractTypeKey": "r03-type",
            "status": "DRAFT",
            "parties": [{"companyId": 1, "companyName": "R03公司"}],
            "inputs": {"amount": old_id},
        }

    def _apply(self, payload, mode="append"):
        return archive.apply_import(
            payload,
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode=mode,
            user=self.admin,
        )

    def test_multiple_instances_of_same_type_are_all_created(self):
        """同类型 3 份合同必须建 3 条、名称各自保留（改前合并成 1 条且被改名）。"""
        payload = self._payload(
            [
                self._instance(1, "R03-合同甲"),
                self._instance(2, "R03-合同乙"),
                self._instance(3, "R03-合同丙"),
            ]
        )
        result = self._apply(payload)

        names = sorted(Contract.objects.filter(competition=self.comp).values_list("name", flat=True))
        self.assertEqual(
            names, sorted(["R03-合同甲", "R03-合同乙", "R03-合同丙"]),
            f"三份合同必须各自保留实例名，实际 {names}（改前只有 1 条且名为「R03-类型」）",
        )
        rows = {r["resource"]: r for r in result["resources"]}
        self.assertEqual(rows.get("contractInstances", {}).get("created"), 3)
        self.assertEqual(rows.get("contractInstances", {}).get("skipped", 0), 0)

        # 参与方公司引用必须映射到目标比赛里的公司（不得因合并而丢弃）
        for c in Contract.objects.filter(competition=self.comp):
            parties = json.loads(c.parties)
            self.assertEqual(parties[0]["companyId"], self.company.id, f"{c.name} 的参与方未映射")

    def test_same_name_instance_is_idempotent_in_append(self):
        """回归：同名同类型的实例在 append 模式下不重复建（自然键去重）。"""
        payload = self._payload([self._instance(1, "R03-幂等合同")])
        self._apply(payload)
        self._apply(payload)
        self.assertEqual(
            Contract.objects.filter(competition=self.comp, name="R03-幂等合同").count(), 1
        )

    def test_overwrite_updates_existing_instance(self):
        """覆盖模式：同名实例按归档更新参与方/输入/状态（改前只 bump skipped，什么都不写）。"""
        self._apply(self._payload([self._instance(1, "R03-覆盖合同")]))
        contract = Contract.objects.get(competition=self.comp, name="R03-覆盖合同")
        Contract.objects.filter(pk=contract.pk).update(inputs=json.dumps({"amount": 999}))

        payload = self._payload([self._instance(1, "R03-覆盖合同")])
        payload["resources"]["contractInstances"]["rows"][0]["status"] = "PENDING_EXEC"
        self._apply(payload, mode="overwrite")

        contract.refresh_from_db()
        self.assertEqual(json.loads(contract.inputs), {"amount": 1}, "覆盖模式应按归档写回 inputs")
        self.assertEqual(contract.status, "PENDING_EXEC", "覆盖模式应按归档更新状态")
