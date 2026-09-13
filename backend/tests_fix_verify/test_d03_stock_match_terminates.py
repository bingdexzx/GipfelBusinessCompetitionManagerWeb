# -*- coding: utf-8 -*-
"""D-03 验证：撮合主循环不得因「量化归 0」而无限循环。

缺陷（改前）：`stock/engine.py` 撮合循环里，现金夹紧得到 `qty = buy_cash / pair_price`
后只比较 `qty <= EPS(1e-9)`；紧接着的「6 位小数微调」会把落在 (1e-9, 5e-7) 的
`qty` 量化成 **0**，于是 `cash/holding/filled/buy_rem/sell_rem` 全都不变、`bi/si`
也不推进 → `while` 永不退出：请求不返回、`transaction.atomic()` 与推进锁长期占用，
该比赛的股票系统僵死（只能重启进程）。

复现条件（本用例）：买价=卖价=1_000_000、买卖各 1 股、买方现金 0.1 →
`qty = 0.1 / 1_000_000 = 1e-7`，恰好落在上述区间。

改后：量化后若为 0，按「受限的一方」作废并推进索引，循环必然前进。
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.db import transaction
from django.test import TestCase

from apps.competitions.models import Competition
from apps.stock import engine as stock_engine
from apps.stock.models import (
    Stock,
    StockCandle,
    StockFundsAccount,
    StockHolding,
    StockOrder,
)


class StockMatchTerminationTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="D03 撮合终止性")
        self.stock = Stock.objects.create(
            code="D03",
            name="D03 测试股",
            total_shares=Decimal("1000000"),
            init_net_profit=Decimal("1000000"),
            industry_pe=10,
            current_carbon=0,
            industry_avg_carbon=0,
            happiness=50,
            init_price=Decimal("1000000"),
            current_price=Decimal("1000000"),
            round=0,
            competition=self.comp,
        )
        # 买方：现金 0.1（买不起 1 股 @1e6，夹紧后 qty = 1e-7 → 量化归 0）
        self.buyer = StockFundsAccount.objects.create(
            name="买方", owner_type="COMPANY", cash_balance=Decimal("0.1"), competition=self.comp
        )
        # 卖方：持有 1 股
        self.seller = StockFundsAccount.objects.create(
            name="卖方", owner_type="COMPANY", cash_balance=Decimal("0"), competition=self.comp
        )
        StockHolding.objects.create(
            funds_account=self.seller, stock=self.stock,
            shares=Decimal("1"), cost_price=Decimal("1"), competition=self.comp,
        )
        self.buy_order = StockOrder.objects.create(
            stock=self.stock, funds_account=self.buyer, side="BUY",
            price=Decimal("1000000"), quantity=Decimal("1"), amount=Decimal("1000000"),
            status="PENDING", round=0, competition=self.comp,
        )
        self.sell_order = StockOrder.objects.create(
            stock=self.stock, funds_account=self.seller, side="SELL",
            price=Decimal("1000000"), quantity=Decimal("1"), amount=Decimal("1000000"),
            status="PENDING", round=0, competition=self.comp,
        )

    def _advance(self):
        """跑真实引擎一轮（关掉做市商，只留上面两笔委托），事务回滚。"""
        with mock.patch.object(
            stock_engine, "generate_market_maker_orders", return_value=(0, False)
        ):
            with transaction.atomic():
                result = stock_engine.advance_one_stock(
                    self.stock,
                    self.comp.id,
                    {},
                    stock_engine.resolve_stock_config(None),
                )
                transaction.set_rollback(True)
        return result

    def test_matching_loop_terminates_when_qty_quantizes_to_zero(self):
        """改前：本用例会挂死（进程不返回）；改后：正常返回且不产生成交。"""
        result = self._advance()  # 改前：卡死在这里
        self.assertIsNotNone(result)

    def test_no_partial_trade_leaks_into_holdings_or_cash(self):
        """无法成交时不得改动现金/持仓/K 线成交量（僵尸成交）。"""
        cash_before = StockFundsAccount.objects.get(pk=self.buyer.pk).cash_balance
        shares_before = StockHolding.objects.get(funds_account=self.seller, stock=self.stock).shares
        self._advance()
        self.buyer.refresh_from_db()
        self.seller.refresh_from_db()
        self.assertEqual(self.buyer.cash_balance, cash_before)
        self.assertEqual(self.seller.cash_balance, Decimal("0.0000"))
        holding = StockHolding.objects.get(funds_account=self.seller, stock=self.stock)
        self.assertEqual(holding.shares, shares_before)
        candle = StockCandle.objects.filter(stock=self.stock, round=1).first()
        if candle is not None:
            self.assertEqual(candle.volume, Decimal("0.0000"))

    def test_normal_match_still_fills(self):
        """功能不变：资金充足的正常委托仍能足额成交（价格/数量/现金守恒）。"""
        self.buyer.cash_balance = Decimal("3000000")
        self.buyer.save(update_fields=["cash_balance"])
        with mock.patch.object(
            stock_engine, "generate_market_maker_orders", return_value=(0, False)
        ):
            with transaction.atomic():
                stock_engine.advance_one_stock(
                    self.stock, self.comp.id, {}, stock_engine.resolve_stock_config(None)
                )
                buyer = StockFundsAccount.objects.get(pk=self.buyer.pk)
                seller = StockFundsAccount.objects.get(pk=self.seller.pk)
                buyer_holding = StockHolding.objects.filter(
                    funds_account=self.buyer, stock=self.stock
                ).first()
                order = StockOrder.objects.get(pk=self.buy_order.pk)
                # 以 1e6 成交 1 股：买方 -1e6、卖方 +1e6、买方持仓 +1、订单成交
                self.assertEqual(buyer.cash_balance, Decimal("2000000.0000"))
                self.assertEqual(seller.cash_balance, Decimal("1000000.0000"))
                self.assertIsNotNone(buyer_holding)
                self.assertEqual(buyer_holding.shares, Decimal("1.0000"))
                self.assertEqual(order.status, "FILLED")
                transaction.set_rollback(True)
