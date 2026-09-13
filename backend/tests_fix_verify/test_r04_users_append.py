# -*- coding: utf-8 -*-
"""R-04 验证：账号范围引用的公司已存在时，追加模式仍必须创建账号。

缺陷：`_CHILD_OF_LIST["users"]` 把账号的四个公司范围字段（companyScopes / viewCompanyScopes /
contractViewCompanyScopes / stockCompanyScopes）登记为「列表型父引用」——只要范围内有**任意一家**
已存在的公司，整行账号被丢弃。而产品推荐的流程正是「先导入本组③参赛主体、再导入本组⑧账号与权限」，
此时公司必然已存在 → **一个账号都不建**（ctx.ids 里也没有 user 映射，连带消息/资金账户的引用全部
落空），用户看到的却是一条「账号与权限：追加模式下有 N 条因所属对象已存在而保留未改动」的误导提示。

修复：users 移出 `_CHILD_OF_LIST`（账号是否存在只取决于 username；范围只是引用，去重与合并交给
`_imp_users` 按 username 处理）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r04_users_append -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.companies.models import Company
from apps.competitions.models import Competition
from apps.industry_types.models import IndustryType
from apps.preparation import archive
from apps.regions.models import Region
from apps.users.models import User


class UsersAppendTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R04-目标比赛")
        self.admin = User(
            username="r04-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R04Pw!123")
        self.admin.save()

        self.industry = IndustryType.objects.create(code=9401, name="R04产业")
        self.region = Region.objects.create(competition=self.comp, name="R04区")
        self.company = Company.objects.create(
            competition=self.comp, name="R04公司", industry_type=self.industry, region=self.region
        )

    def _payload(self):
        return {
            "resources": {
                # 模拟「先导参赛主体」：公司已在库里
                "companies": {"rows": [{"_id": 1, "name": "R04公司", "industryTypeCode": 9401}]},
                "users": {
                    "rows": [
                        {
                            "_id": 1,
                            "username": "r04-new-player",
                            "name": "R04新账号",
                            "role": "PLAYER",
                            "password": "PlayerPw!123",
                            "companyScopes": [1],
                            "viewCompanyScopes": [1],
                        }
                    ]
                },
            }
        }

    def _import(self):
        return archive.apply_import(
            self._payload(),
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode="append",
            user=self.admin,
        )

    def test_user_is_created_even_if_scoped_company_exists(self):
        result = self._import()

        self.assertTrue(
            User.objects.filter(username="r04-new-player").exists(),
            "公司已存在不得导致账号整行跳过（改前 users 一行都不建）",
        )
        created = User.objects.get(username="r04-new-player")
        self.assertIn(
            self.company.id, created.company_scopes_list,
            "账号的公司范围必须映射到目标比赛里已存在的公司",
        )
        rows = {r["resource"]: r for r in result["resources"]}
        users_stat = rows.get("users", {})
        self.assertEqual(
            users_stat.get("created", 0) + users_stat.get("kept", 0), 1,
            f"users 统计应体现该账号（created 或 kept），实际 {users_stat}",
        )

    def test_repeat_import_does_not_duplicate_user(self):
        """回归：重复导入不得重复建号（username 去重）。"""
        self._import()
        self._import()
        self.assertEqual(User.objects.filter(username="r04-new-player").count(), 1)
