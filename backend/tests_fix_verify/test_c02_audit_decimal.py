# -*- coding: utf-8 -*-
"""C-02 验证：含 Decimal 字段的模型写操作必须有审计留痕。

缺陷（改前）：`apps/common/audit.py::log_write` 用 `json.dumps(sanitize_changes(changes))`
序列化变更，而 `sanitize_changes` 只做脱敏、**不做类型转换** → 只要 changes 里含
`Decimal`（fuels/warehouses/production_lines/infrastructures/vehicles/stock 等
金额、数量字段）就抛 `TypeError: Object of type Decimal is not JSON serializable`，
被 `except Exception` 静默吞掉 → 这些模型的**所有写操作零审计**
（U01 C-02；仓库里 `dumps_json_safe` 就是为此存在的，只是这里没用）。

改后：改用 `dumps_json_safe()`（Decimal 整值→int、小数→字符串、大 int→字符串），
与出站渲染口径一致；脱敏行为不变。
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.common.audit import log_write


class AuditDecimalSerializationTests(TestCase):
    def _logs(self):
        return AuditLog.objects.filter(kind="write", model="Fuel")

    # ---------- 缺陷场景 ----------
    def test_decimal_changes_are_audited(self):
        log_write(
            model="Fuel",
            action="Fuel:create",
            record_id=1,
            changes={"name": "柴油", "pricePerLiter": Decimal("7.5000")},
        )
        logs = self._logs()
        self.assertEqual(logs.count(), 1, "含 Decimal 的写操作必须落审计")
        payload = json.loads(logs.first().changes)
        self.assertEqual(payload["name"], "柴油")
        # 与出站渲染口径一致：非整 Decimal 用 format(obj, "f") → 保留字段标度（"7.5000"）
        self.assertEqual(payload["pricePerLiter"], "7.5000")

    def test_large_number_changes_are_audited(self):
        """大整数（>2^53）同样不能丢：按字符串记录，避免前端/JSON 丢精度。"""
        big = Decimal("12345678901234567890123.4567")
        log_write(model="Stock", action="Stock:create", record_id=2, changes={"cash": big})
        logs = AuditLog.objects.filter(kind="write", model="Stock")
        self.assertEqual(logs.count(), 1)
        self.assertEqual(json.loads(logs.first().changes)["cash"], "12345678901234567890123.4567")

    def test_nested_and_list_decimal_changes_are_audited(self):
        log_write(
            model="Warehouse",
            action="Warehouse:update",
            record_id=3,
            changes={"items": [{"price": Decimal("1.25")}], "capacity": Decimal("100")},
        )
        logs = AuditLog.objects.filter(kind="write", model="Warehouse")
        self.assertEqual(logs.count(), 1)
        payload = json.loads(logs.first().changes)
        self.assertEqual(payload["items"][0]["price"], "1.25")
        self.assertEqual(payload["capacity"], 100)

    # ---------- 功能不变 ----------
    def test_plain_changes_still_audited(self):
        log_write(model="Material", action="Material:create", record_id=9, changes={"name": "铁矿石"})
        logs = AuditLog.objects.filter(kind="write", model="Material")
        self.assertEqual(logs.count(), 1)
        self.assertEqual(json.loads(logs.first().changes), {"name": "铁矿石"})

    def test_sensitive_keys_still_redacted(self):
        log_write(
            model="User",
            action="User:update",
            record_id=10,
            changes={"username": "u1", "password_hash": "$2b$12$abc", "token": "t"},
        )
        payload = json.loads(AuditLog.objects.get(kind="write", model="User").changes)
        self.assertEqual(payload["username"], "u1")
        self.assertEqual(payload["password_hash"], "***REDACTED***")
        self.assertEqual(payload["token"], "***REDACTED***")

    def test_none_changes_stays_null(self):
        log_write(model="Material", action="Material:delete", record_id=11, changes=None)
        self.assertIsNone(AuditLog.objects.get(kind="write", model="Material").changes)
