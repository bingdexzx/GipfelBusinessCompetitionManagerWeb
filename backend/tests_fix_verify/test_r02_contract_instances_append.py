# -*- coding: utf-8 -*-
"""R-02 验证：全局合同类型已存在时，追加模式不得把预设合同实例整类丢掉。

缺陷：`_CHILD_OF["contractInstances"] = (("contractTypes", "contractTypeId"),)` —— contractTypes 是
**全局资源**（跨比赛共享）。同一套部署里第二个比赛导入时 `_imp_contract_types` 必然命中已存在的
类型并登记 kept → 本次导入的所有预设合同实例被整类丢弃（created=0、kept=N + 一条中性 note），
用户以为导入成功，实际比赛开局没有任何可履约合同。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r02_contract_instances_append -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.competitions.models import Competition
from apps.contracts.models import Contract, ContractType
from apps.preparation import archive
from apps.users.models import User


class ContractInstanceAppendTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R02-目标比赛")
        self.admin = User(
            username="r02-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R02Pw!123")
        self.admin.save()

    def _import(self, payload):
        return archive.apply_import(
            payload,
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode="append",
            user=self.admin,
        )

    def _payload(self, key: str, name: str):
        return {
            "resources": {
                "contractTypes": {"rows": [{"_id": 1, "key": key, "name": name}]},
                "contractInstances": {
                    "rows": [
                        {
                            "_id": 1,
                            # 导出侧同时带 contractTypeId 与 contractTypeKey（见 _exp_contract_instances）；
                            # 改前的「整类跳过」正是按 contractTypeId 命中「类型已被 kept」触发的
                            "contractTypeId": 1,
                            "name": "R02-预设合同",
                            "contractTypeKey": key,
                            "status": "DRAFT",
                            "parties": [],
                            "inputs": {},
                        }
                    ]
                },
            }
        }

    def test_contract_instance_imports_when_type_already_exists(self):
        """合同类型已存在（全局资源被 kept）时，预设合同实例仍必须创建。"""
        ct = ContractType.objects.create(key="r02-type", name="R02-类型", party_count=0)
        result = self._import(self._payload("r02-type", "R02-类型"))

        self.assertEqual(
            Contract.objects.filter(competition=self.comp, contract_type=ct).count(), 1,
            "合同类型已存在不得导致合同实例被整类跳过（改前 created=0、kept=1 且只有中性 note）",
        )
        rows = {r["resource"]: r for r in result["resources"]}
        self.assertEqual(rows.get("contractInstances", {}).get("created"), 1)
        self.assertEqual(rows.get("contractInstances", {}).get("kept", 0), 0)

    def test_repeat_import_does_not_duplicate_instance(self):
        """回归：重复导入同一份归档不得重复创建合同实例。"""
        ContractType.objects.create(key="r02-type2", name="R02-类型2", party_count=0)
        payload = self._payload("r02-type2", "R02-类型2")
        self._import(payload)
        self._import(payload)
        self.assertEqual(
            Contract.objects.filter(
                competition=self.comp, contract_type__key="r02-type2"
            ).count(),
            1,
            "同一份合同实例重复导入应命中已有记录而不是再建一份",
        )
