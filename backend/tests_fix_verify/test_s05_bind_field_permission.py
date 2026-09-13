# -*- coding: utf-8 -*-
"""S-05 验证：`bindFieldId` 改派必须限高级管理（否则任意充值）。

缺陷（改前）：`stock/views.py::AccountItemView.patch` 里，`cashBalance` /
`companyId` / `userId` 三个高危写都校验了 `high = _is_high_manager(user)`，
**唯独 `bindFieldId` 漏了**（第 684-691 行）。而绑定字段会直接把账户余额同步成
该产业字段的值（`cash_balance = 字段值`），且引擎下单/结算都以绑定字段为可用现金。
→ 持 `stock:edit` 的比赛管理员（COMPETITION_ADMIN 默认具备）只要 PATCH 一次
`bindFieldId`，就能把余额设成任意产业字段（例如注册资本 888888），即任意充值。

改后：`bindFieldId` 与其它三项一致，仅超管 / `stock:manage` 可改。
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.test import Client, TestCase

from apps.common.permissions import BASE_VIEW_PERMISSIONS
from apps.companies.models import Company, CompanyFieldValue
from apps.competitions.models import Competition
from apps.industry_types.models import IndustryField, IndustryType
from apps.regions.models import Region
from apps.stock.models import StockFundsAccount
from apps.users.models import User


class BindFieldPermissionTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="S05 绑定字段权限")
        self.region = Region.objects.create(competition=self.comp, name="S区")
        self.industry = IndustryType.objects.create(code=9501, name="S05产业")
        self.field = IndustryField.objects.create(
            industry_type=self.industry, name="注册资本", field_key="capital", field_type="NUMBER"
        )
        self.company = Company.objects.create(
            competition=self.comp, name="S05公司", industry_type=self.industry, region=self.region
        )
        CompanyFieldValue.objects.create(
            company=self.company, industry_field=self.field, value="888888"
        )
        self.account = StockFundsAccount.objects.create(
            name="S05账户", owner_type="COMPANY", company_id=self.company.id,
            cash_balance=Decimal("100"), competition=self.comp,
        )

        # 只有 stock:edit 的比赛管理员（非高级管理）
        self.editor = User(
            username="s05-editor", role="COMPETITION_ADMIN", is_active=True,
            competition=self.comp,
            permissions=json.dumps(["stock:edit"]),
            stock_company_scopes=json.dumps([self.company.id]),
        )
        self.editor.set_password("EditorPw!123")
        self.editor.save()

        # 高级管理（stock:manage）
        self.manager = User(
            username="s05-manager", role="COMPETITION_ADMIN", is_active=True,
            competition=self.comp,
            permissions=json.dumps(["stock:edit", "stock:manage"]),
            stock_company_scopes=json.dumps([self.company.id]),
        )
        self.manager.set_password("ManagerPw!123")
        self.manager.save()

        self.client = Client()
        from apps.auth.authentication import create_jwt

        self.editor_token = create_jwt(self.editor)
        self.manager_token = create_jwt(self.manager)
        self.url = f"/api/stocks/accounts/{self.account.pk}"

    def _patch(self, token, payload):
        return self.client.patch(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _cash(self) -> Decimal:
        self.account.refresh_from_db()
        return self.account.cash_balance

    # ---------- 缺陷场景 ----------
    def test_stock_edit_user_cannot_rebind_field(self):
        """改前：200 且余额被同步为 888888（任意充值）；改后：403 且余额不变。"""
        before = self._cash()
        resp = self._patch(self.editor_token, {"bindFieldId": self.field.id})
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(self._cash(), before, "非高级管理改派绑定字段不得改动余额")
        self.account.refresh_from_db()
        self.assertIsNone(self.account.bind_field_id)

    def test_unbind_field_also_requires_high_manager(self):
        """解绑（bindFieldId=null）同样属高危写，须一并拦住。"""
        resp = self._patch(self.editor_token, {"bindFieldId": None})
        self.assertEqual(resp.status_code, 403, resp.content)

    # ---------- 功能不变 ----------
    def test_high_manager_can_still_rebind_field(self):
        resp = self._patch(self.manager_token, {"bindFieldId": self.field.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bind_field_id, self.field.id)
        self.assertEqual(self.account.cash_balance, Decimal("888888"))

    def test_stock_edit_user_can_still_rename_account(self):
        """非高危字段（改名）不受影响，stock:edit 仍可用。"""
        resp = self._patch(self.editor_token, {"name": "改名后的账户"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.account.refresh_from_db()
        self.assertEqual(self.account.name, "改名后的账户")

    def test_cash_balance_still_requires_high_manager(self):
        """既有行为回归保护：cashBalance 一直只允许高级管理。"""
        resp = self._patch(self.editor_token, {"cashBalance": "999999"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._cash(), Decimal("100.0000"))

    def test_viewer_permission_cannot_patch_at_all(self):
        viewer = User(
            username="s05-viewer", role="PLAYER", is_active=True, competition=self.comp,
            permissions=json.dumps(list(BASE_VIEW_PERMISSIONS)),
        )
        viewer.set_password("ViewerPw!123")
        viewer.save()
        from apps.auth.authentication import create_jwt

        resp = self._patch(create_jwt(viewer), {"name": "x"})
        self.assertEqual(resp.status_code, 403)
