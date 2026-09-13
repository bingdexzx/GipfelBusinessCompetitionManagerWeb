# -*- coding: utf-8 -*-
"""D-01 验证：SQLite 上 `DecimalField(max_digits=60)` 的精确存储守卫。

背景（改前实测）：SQLite 的 NUMERIC 亲和性把 `decimal` 列按 double(REAL) 存储，
读回时 Django 以 `Context(prec=15)` 还原 —— 有效数字超过 15 位即静默丢精度
（仓库自带 `tests/sqlite_decimal_roundtrip.py` 实测 FAIL：写入
`12345678901234567890123.4567` 读回 `12345678901234600000000.0000`）。

本模块同时是「改前 / 改后」的判定器：
- 改前：`test_oversized_value_is_rejected_not_silently_truncated` 等用例失败（未拦截）；
- 改后：超精度写入被明确拒绝（400），且正常量级金额读写行为完全不变。
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.test import TestCase

from apps.common.exceptions import BusinessError
from apps.competitions.models import Competition
from apps.fuels.models import Fuel


class DecimalExactStorageGuardTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="D01 精度验证赛")

    def _create_fuel(self, value, name="f"):
        return Fuel.objects.create(competition=self.comp, name=name, price_per_liter=value)

    def _assert_rejected(self, fn, message=""):
        """断言写入被守卫拒绝（用 savepoint 包住：Django 会把写失败标记到当前事务）。"""
        with self.assertRaises(BusinessError, msg=message) as ctx:
            with transaction.atomic():
                fn()
        self.assertEqual(getattr(ctx.exception, "status_code", None), 400)
        return ctx.exception

    # ---------- 缺陷场景：超精度写入必须被拒绝，而不是静默截断 ----------
    def test_oversized_value_is_rejected_not_silently_truncated(self):
        value = Decimal("12345678901234567890123.4567")  # 27 位有效数字
        self._assert_rejected(lambda: self._create_fuel(value))
        # 拒绝必须发生在写库之前：不能留下一条被截断的记录
        self.assertEqual(Fuel.objects.filter(competition=self.comp).count(), 0)

    def test_16_digit_value_is_rejected(self):
        # 16 位有效数字已超出 double 往返精度：1234567890123456 → 读回 …460
        self._assert_rejected(lambda: self._create_fuel(Decimal("1234567890123456")))

    def test_decimal_fraction_beyond_15_digits_is_rejected(self):
        # 17 位有效数字的小数
        self._assert_rejected(lambda: self._create_fuel(Decimal("0.12345678901234567")))

    def test_guard_covers_queryset_update(self):
        """守卫在字段层：QuerySet.update() 同样要被拦住。"""
        fuel = self._create_fuel(Decimal("1"), name="upd")
        self._assert_rejected(
            lambda: Fuel.objects.filter(pk=fuel.pk).update(
                price_per_liter=Decimal("12345678901234567890.1234")
            )
        )
        fuel.refresh_from_db()
        self.assertEqual(fuel.price_per_liter, Decimal("1.0000"))

    def test_guard_covers_bulk_create(self):
        from apps.warehouses.models import Warehouse

        self._assert_rejected(
            lambda: Warehouse.objects.bulk_create(
                [
                    Warehouse(
                        competition=self.comp,
                        name="bulk",
                        capacity=Decimal("12345678901234567890.1234"),
                        price=Decimal("1"),
                    )
                ]
            )
        )

    # ---------- 功能不变：正常量级金额读写与改前一致 ----------
    def test_normal_values_still_round_trip_exactly(self):
        cases = [
            Decimal("0"),
            Decimal("0.0001"),
            Decimal("1234567890.1234"),        # 14 位有效数字
            Decimal("99999999999.9999"),       # 15 位有效数字（阈值内）
            Decimal("100000000000000.0000"),   # 1 位有效数字的大数
            Decimal("-1234.5678"),
        ]
        for i, v in enumerate(cases):
            fuel = self._create_fuel(v, name=f"ok-{i}")
            fuel.refresh_from_db()
            self.assertEqual(fuel.price_per_liter, v, f"{v} 往返不精确")

    def test_threshold_matches_sqlite_round_trip(self):
        """阈值自证：恰好 15 位有效数字可精确往返（不依赖守卫逻辑）。"""
        exact = Decimal("999999999999999")
        fuel = self._create_fuel(exact, name="t15")
        fuel.refresh_from_db()
        self.assertEqual(fuel.price_per_liter, exact)

    def test_serializer_write_path_unchanged_for_normal_values(self):
        """接口层：正常价格仍可创建（回归保护）。"""
        from apps.fuels.serializers import FuelSerializer

        ser = FuelSerializer(
            data={"name": "api", "pricePerLiter": "12.3456", "competitionId": self.comp.id}
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        instance = ser.create(dict(ser.validated_data))
        instance.refresh_from_db()
        self.assertEqual(instance.price_per_liter, Decimal("12.3456"))
