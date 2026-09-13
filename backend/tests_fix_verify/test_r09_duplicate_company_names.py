# -*- coding: utf-8 -*-
"""R-09 验证：目标比赛存在重名公司时的自然键兜底与「公司」资源导入。

缺陷（改前）：
  1. `RefResolver.resolve('companies', …, name=…)` 直接 `.first()`（无排序）→ 公司字段值 /
     合同参与方 / 概览卡片 / 股票归属 / 资金账户 / 账号范围都可能静默挂到**另一家同名公司**上，
     且没有任何提示（`companies` 没有 (competition, name) 唯一约束，`plan.py` 明确把同名公司
     当作正常状态）；
  2. `_imp_companies` 用 `get_or_create(competition_id=…, name=…)` → 同名时内部 `get()` 抛
     `MultipleObjectsReturned`（不是数据库错误、无法自愈），被 `apply_import` 的 per-resource
     except 捕获 ⇒ **整个「公司」资源全部跳过**，只留一条「资源 公司 导入失败」。

改后：按名兜底改为 `order_by("id")` 取最小 id 并在命中多条时记 problem；
      `_imp_companies` 改为显式「先查后建」，同名只处理 id 最小的那条并记 problem。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r09_duplicate_company_names -v 2
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


class DuplicateCompanyNameTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R09-目标比赛")
        self.admin = User(
            username="r09-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R09Pw!123")
        self.admin.save()

        self.industry = IndustryType.objects.create(code=9403, name="R09产业")
        self.region = Region.objects.create(competition=self.comp, name="R09区")
        # 目标比赛里已存在两家同名公司（可预期状态）
        self.company_a = Company.objects.create(
            competition=self.comp, name="R09重名公司", industry_type=self.industry, region=self.region
        )
        self.company_b = Company.objects.create(
            competition=self.comp, name="R09重名公司", industry_type=self.industry, region=self.region
        )

    def _import(self, payload, mode="append"):
        return archive.apply_import(
            payload,
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode=mode,
            user=self.admin,
        )

    def test_companies_resource_is_not_skipped_when_names_duplicate(self):
        """公司资源必须照常导入（改前整类失败：MultipleObjectsReturned）。"""
        payload = {
            "resources": {
                "companies": {
                    "rows": [
                        {"_id": 1, "name": "R09重名公司", "industryTypeCode": 9403},
                        {"_id": 2, "name": "R09新公司", "industryTypeCode": 9403},
                    ]
                }
            }
        }
        result = self._import(payload)

        self.assertTrue(
            Company.objects.filter(competition=self.comp, name="R09新公司").exists(),
            f"公司资源不得因同名而整类跳过；problems={result.get('problems')}",
        )
        self.assertFalse(
            any("MultipleObjectsReturned" in p for p in (result.get("problems") or [])),
            f"不应再出现 MultipleObjectsReturned：{result.get('problems')}",
        )
        self.assertTrue(
            any("同名公司" in p for p in (result.get("problems") or [])),
            f"同名场景应记 problem 提示核对：{result.get('problems')}",
        )

    def test_reference_resolution_is_deterministic_and_reported(self):
        """按名兜底必须稳定（id 最小）且记 problem（改前无序、随机绑定且无提示）。"""
        payload = {
            "resources": {
                "companyFieldValues": {
                    "rows": [
                        {
                            "_id": 1,
                            "companyName": "R09重名公司",
                            "industryTypeCode": 9403,
                            "fieldKey": "cash",
                            "value": "123",
                        }
                    ]
                }
            }
        }
        # 先让 companyFieldValues 能解析字段：建一个同 key 的字段
        from apps.industry_types.models import IndustryField

        IndustryField.objects.create(
            industry_type=self.industry, name="现金", field_key="cash", field_type="NUMBER"
        )
        result = self._import(payload)

        self.assertTrue(
            any("同名" in p for p in (result.get("problems") or [])),
            f"同名兜底应记 problem：{result.get('problems')}",
        )
        # 公司字段值应挂到 id 最小的那家（确定行为，而不是随机）
        from apps.companies.models import CompanyFieldValue

        value = CompanyFieldValue.objects.filter(company_id=self.company_a.id).first()
        self.assertIsNotNone(
            value, "按名兜底应绑定到 id 最小的同名公司（改前无排序，可能绑到另一家）"
        )

    def test_no_problem_when_names_are_unique(self):
        """回归：名称唯一时不产生同名 problem。"""
        payload = {
            "resources": {
                "companies": {"rows": [{"_id": 1, "name": "R09唯一公司", "industryTypeCode": 9403}]}
            }
        }
        result = self._import(payload)
        self.assertFalse(
            any("同名" in p for p in (result.get("problems") or [])),
            f"唯一名称不应报同名问题：{result.get('problems')}",
        )
