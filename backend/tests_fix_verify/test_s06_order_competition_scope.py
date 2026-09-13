# -*- coding: utf-8 -*-
"""S-06 验证：下单/撤单必须按比赛隔离，高级管理也不能跨比赛操作。

缺陷（改前）：
- `OrderCreateView.post`：`Stock.objects.get(pk=data["stockId"])` **不校验比赛归属**；
  且 `if not _is_high_manager(user): _assert_account_operable(...)` —— 高级管理直接
  跳过账户校验。于是比赛 B 的 `stock:manage` 账号可以对比赛 A 的股票/账户下单。
- `OrderItemView.delete`（撤单）：`StockOrder.objects.select_for_update().get(pk=pk)`
  同样不校验比赛归属，高级管理又跳过账户校验 → 可撤掉**任意比赛**的挂单。

改后：下单复用 `_get_stock_scoped()`（非超管跨比赛一律 404「股票不存在」）；
撤单先校验订单所属比赛与当前用户一致。
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.test import Client, TestCase

from apps.auth.authentication import create_jwt
from apps.companies.models import Company
from apps.competitions.models import Competition
from apps.industry_types.models import IndustryField, IndustryType
from apps.regions.models import Region
from apps.stock.models import Stock, StockFundsAccount, StockHolding, StockOrder
from apps.users.models import User


class OrderCompetitionScopeTests(TestCase):
    def setUp(self):
        # 比赛 A：股票 + 公司账户 + 挂单
        self.comp_a = Competition.objects.create(name="S06-比赛A")
        self.comp_b = Competition.objects.create(name="S06-比赛B")
        self.region_a = Region.objects.create(competition=self.comp_a, name="A区")
        self.industry = IndustryType.objects.create(code=9601, name="S06产业")
        self.field = IndustryField.objects.create(
            industry_type=self.industry, name="现金", field_key="cash", field_type="NUMBER"
        )
        self.company_a = Company.objects.create(
            competition=self.comp_a, name="A公司", industry_type=self.industry, region=self.region_a
        )
        self.stock_a = Stock.objects.create(
            code="S06A", name="A股", total_shares=Decimal("1000000"),
            init_net_profit=Decimal("1000000"), industry_pe=10, current_carbon=0,
            industry_avg_carbon=0, happiness=50, init_price=Decimal("1000"),
            current_price=Decimal("1000"), round=0, competition=self.comp_a,
        )
        self.account_a = StockFundsAccount.objects.create(
            name="A账户", owner_type="COMPANY", company_id=self.company_a.id,
            cash_balance=Decimal("1000000"), competition=self.comp_a,
        )
        StockHolding.objects.create(
            funds_account=self.account_a, stock=self.stock_a,
            shares=Decimal("10"), cost_price=Decimal("1000"), competition=self.comp_a,
        )
        self.order_a = StockOrder.objects.create(
            stock=self.stock_a, funds_account=self.account_a, side="BUY",
            price=Decimal("1000"), quantity=Decimal("1"), amount=Decimal("1000"),
            status="PENDING", round=0, competition=self.comp_a,
        )

        # 比赛 B 的高级管理（stock:manage）——改前可跨比赛下单/撤单
        self.manager_b = self._make_user(
            "s06-manager-b", self.comp_b, ["stock:view", "stock:edit", "stock:manage"], []
        )
        # 比赛 B 的普通选手（持 stock:view），被误配了 A 公司的账户范围
        self.player_b = self._make_user(
            "s06-player-b", self.comp_b, ["stock:view"], [self.company_a.id]
        )
        # 比赛 A 的高级管理（功能不变对照）
        self.manager_a = self._make_user(
            "s06-manager-a", self.comp_a, ["stock:view", "stock:edit", "stock:manage"],
            [self.company_a.id],
        )

        self.client = Client()

    def _make_user(self, username, competition, permissions, scopes):
        u = User(
            username=username, role="COMPETITION_ADMIN", is_active=True,
            competition=competition,
            permissions=json.dumps(permissions) if permissions else None,
            stock_company_scopes=json.dumps(scopes) if scopes else None,
        )
        u.set_password("Pw!123456")
        u.save()
        return u

    def _post_order(self, user, price="1000", quantity="1"):
        return self.client.post(
            "/api/stocks/orders",
            data={
                "stockId": self.stock_a.id,
                "fundsAccountId": self.account_a.id,
                "side": "BUY",
                "price": price,
                "quantity": quantity,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {create_jwt(user)}",
        )

    def _cancel(self, user, order_id):
        return self.client.delete(
            f"/api/stocks/orders/{order_id}",
            HTTP_AUTHORIZATION=f"Bearer {create_jwt(user)}",
        )

    # ---------- 缺陷场景 1：跨比赛下单 ----------
    def test_other_competition_manager_cannot_place_order(self):
        before = StockOrder.objects.filter(competition=self.comp_a).count()
        resp = self._post_order(self.manager_b)
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(
            StockOrder.objects.filter(competition=self.comp_a).count(), before,
            "跨比赛下单不得写入",
        )

    def test_other_competition_player_with_a_scopes_cannot_place_order(self):
        resp = self._post_order(self.player_b)
        self.assertEqual(resp.status_code, 404, resp.content)

    # ---------- 缺陷场景 2：跨比赛撤单 ----------
    def test_other_competition_manager_cannot_cancel_order(self):
        resp = self._cancel(self.manager_b, self.order_a.id)
        self.assertEqual(resp.status_code, 404, resp.content)
        self.order_a.refresh_from_db()
        self.assertEqual(self.order_a.status, "PENDING", "跨比赛订单不得被撤销")

    # ---------- 功能不变 ----------
    def test_same_competition_manager_can_place_and_cancel(self):
        resp = self._post_order(self.manager_a)
        self.assertEqual(resp.status_code, 200, resp.content)
        order_id = resp.json()["data"]["id"]
        self.assertTrue(
            StockOrder.objects.filter(pk=order_id, competition=self.comp_a).exists()
        )
        cancel = self._cancel(self.manager_a, order_id)
        self.assertEqual(cancel.status_code, 200, cancel.content)
        self.assertEqual(
            StockOrder.objects.get(pk=order_id).status, "CANCELLED"
        )

    def test_same_competition_manager_can_cancel_existing_order(self):
        resp = self._cancel(self.manager_a, self.order_a.id)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.order_a.refresh_from_db()
        self.assertEqual(self.order_a.status, "CANCELLED")

    def test_super_admin_can_still_cross_competition(self):
        """超管不受比赛域限制（既有行为）。"""
        superuser = User(username="s06-super", role="SUPER_ADMIN", is_active=True)
        superuser.set_password("Pw!123456")
        superuser.save()
        resp = self._post_order(superuser)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_price_limit_still_enforced(self):
        """既有委托价 ±10% 限制不受影响。"""
        resp = self._post_order(self.manager_a, price="5000")
        self.assertEqual(resp.status_code, 400)
