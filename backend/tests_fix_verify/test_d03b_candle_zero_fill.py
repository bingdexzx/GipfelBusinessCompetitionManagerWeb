# -*- coding: utf-8 -*-
"""D-03 相邻缺陷：撮合「判定为可成交、实际零成交」时 K 线构建抛 TypeError。

本模块与 D-03 的死循环是**两个独立根因**：
- D-03：`qty` 量化归 0 导致循环不推进（挂死）；
- 本模块：循环正常结束但 `trade_prices` 为空（本轮一股未成交）时，
  `build_candle(..., trade_high=None, trade_low=None)` 走到
  `theory_diff = abs(float(theoretical) - close)`，而 `close` 是
  `price["final"]`（`round2()` 返回 Decimal）→ `float - Decimal` → TypeError。

复现路径与 D-03 无关：买方现金为 0 → 循环走 `qty <= EPS` 分支并推进索引 →
循环正常结束 → 仍带 `theoretical`（float）+ `close`（Decimal）调用 build_candle。
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.db import transaction
from django.test import TestCase

from apps.competitions.models import Competition
from apps.stock import engine as stock_engine
from apps.stock.models import Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder


class CandleZeroFillTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="D03b 零成交K线")
        self.stock = Stock.objects.create(
            code="D03B", name="零成交测试股",
            total_shares=Decimal("1000000"), init_net_profit=Decimal("1000000"),
            industry_pe=10, current_carbon=0, industry_avg_carbon=0, happiness=50,
            init_price=Decimal("1000000"), current_price=Decimal("1000000"),
            round=0, competition=self.comp,
        )
        # 买方现金 0（挂单后余额被花光的现实情形）：可成交判定成立，但一股都买不起
        self.buyer = StockFundsAccount.objects.create(
            name="零现金买方", owner_type="COMPANY", cash_balance=Decimal("0"), competition=self.comp
        )
        self.seller = StockFundsAccount.objects.create(
            name="卖方", owner_type="COMPANY", cash_balance=Decimal("0"), competition=self.comp
        )
        StockHolding.objects.create(
            funds_account=self.seller, stock=self.stock,
            shares=Decimal("1"), cost_price=Decimal("1"), competition=self.comp,
        )
        StockOrder.objects.create(
            stock=self.stock, funds_account=self.buyer, side="BUY",
            price=Decimal("1000000"), quantity=Decimal("1"), amount=Decimal("1000000"),
            status="PENDING", round=0, competition=self.comp,
        )
        StockOrder.objects.create(
            stock=self.stock, funds_account=self.seller, side="SELL",
            price=Decimal("1000000"), quantity=Decimal("1"), amount=Decimal("1000000"),
            status="PENDING", round=0, competition=self.comp,
        )

    def _advance(self, rollback=True):
        with mock.patch.object(
            stock_engine, "generate_market_maker_orders", return_value=(0, False)
        ):
            if not rollback:
                return stock_engine.advance_one_stock(
                    self.stock, self.comp.id, {}, stock_engine.resolve_stock_config(None)
                )
            with transaction.atomic():
                result = stock_engine.advance_one_stock(
                    self.stock, self.comp.id, {}, stock_engine.resolve_stock_config(None)
                )
                transaction.set_rollback(True)
        return result

    def test_zero_fill_round_builds_candle_without_type_error(self):
        """改前：TypeError: unsupported operand type(s) for -: 'float' and 'Decimal'。"""
        result = self._advance()
        self.assertIsNotNone(result)
        self.assertEqual(result["round"], 1)

    def test_zero_fill_round_records_empty_candle(self):
        """零成交轮照常生成 K 线（volume=0），价格不动、轮次推进。"""
        with transaction.atomic():
            self._advance(rollback=False)
            candle = StockCandle.objects.filter(stock=self.stock, round=1).first()
            self.assertIsNotNone(candle, "零成交轮必须照常落 K 线")
            self.assertEqual(candle.volume, Decimal("0.0000"))
            self.assertEqual(candle.close, Decimal("1000000.0000"))
            self.assertEqual(candle.open, Decimal("1000000.0000"))
            transaction.set_rollback(True)
