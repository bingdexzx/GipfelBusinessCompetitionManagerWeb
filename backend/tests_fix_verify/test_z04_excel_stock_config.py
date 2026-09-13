# -*- coding: utf-8 -*-
"""Z-04 验证：股票参数只写一行不得绕过交叉校验。

缺陷（改前）：`_assert_stock_config_sane` 只在**两个键都出现在表格里**时才比对：
  - 只写一行 `limitPct` → `maxMovePct` 缺省（运行期补成默认 0.05），`limit < move` 的检查被跳过；
  - `limitPct` 没有上界：`100` / `'1e3'` 只得到一句「建议不超过 0.10」的提示，照样落库；
    `Competition.stockConfig` 导入时无条件覆盖 → 一次手滑就改掉既有比赛的股票规则，单轮涨跌幅
    上限变成 100000%。
规范与教程都承诺「表格层会替你挡住未知参数名 / limitPct < maxMovePct / mmMinQty > mmMaxQty」。

改后：与 `DEFAULT_STOCK_CONFIG` 合并后再校验（缺省键按运行期默认参与比较）、`limitPct > 0.10`
直接拒绝、并拒绝 nan/inf 等非有限数值。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z04_excel_stock_config -v 2
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from sheet_spec import (  # noqa: E402
    SHEET_BY_NAME,
    SheetContext,
    SheetFormatError,
    _assert_stock_config_sane,
)


class _FakeBuilder:
    def __init__(self):
        self.stock_config = None
        self.calls = []

    def stock_config_set(self, config):
        self.stock_config = dict(config)
        self.calls.append(config)

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None

        return _rec


def ctx():
    return SheetContext(builder=_FakeBuilder())


def sheet_ctx():
    """真正走「股票参数表」handler 的上下文（builder 需支持 stock_config_set）。"""
    return SheetContext(builder=_FakeBuilder())


class StockConfigSaneTests(SimpleTestCase):
    def test_single_limit_key_is_validated_against_default_move(self):
        """只写 limitPct=0.02 时必须报错（默认 maxMovePct=0.05）。"""
        with self.assertRaises(SheetFormatError):
            _assert_stock_config_sane({"limitPct": 0.02}, ctx())

    def test_valid_single_key_passes(self):
        _assert_stock_config_sane({"limitPct": 0.08}, ctx())
        _assert_stock_config_sane({"maxMovePct": 0.03}, ctx())

    def test_limit_upper_bound_is_enforced(self):
        for bad in (0.5, 100, "1e3", 1000.0):
            with self.assertRaises(SheetFormatError, msg=str(bad)):
                _assert_stock_config_sane({"limitPct": bad}, ctx())

    def test_non_finite_is_rejected(self):
        for bad in ("nan", "inf", float("inf"), float("nan")):
            with self.assertRaises(SheetFormatError, msg=str(bad)):
                _assert_stock_config_sane({"limitPct": bad}, ctx())

    def test_mm_bounds_still_checked(self):
        with self.assertRaises(SheetFormatError):
            _assert_stock_config_sane({"mmMinQty": 60000, "mmMaxQty": 50000}, ctx())

    def test_defaults_alone_are_sane(self):
        from apps.stock.engine import DEFAULT_STOCK_CONFIG

        _assert_stock_config_sane(dict(DEFAULT_STOCK_CONFIG), ctx())


class StockSheetHandlerTests(SimpleTestCase):
    """走真实 handler：只写一行 limitPct 非法值必须被拦下。"""

    def _run(self, rows):
        c = sheet_ctx()
        handler = SHEET_BY_NAME["股票参数"].handler
        for row in rows:
            handler(c, row)
        return c.builder

    def test_single_illegal_limit_row_rejected(self):
        with self.assertRaises(SheetFormatError):
            self._run([{"param": "limitPct", "value": "100"}])
        with self.assertRaises(SheetFormatError):
            self._run([{"param": "limitPct", "value": "1e3"}])

    def test_single_limit_lower_than_default_move_rejected(self):
        with self.assertRaises(SheetFormatError):
            self._run([{"param": "limitPct", "value": "0.02"}])

    def test_legal_rows_still_apply(self):
        builder = self._run(
            [
                {"param": "limitPct", "value": "0.08"},
                {"param": "maxMovePct", "value": "0.03"},
                {"param": "mmMinQty", "value": "500"},
            ]
        )
        self.assertEqual(builder.stock_config["limitPct"], 0.08)
        self.assertEqual(builder.stock_config["maxMovePct"], 0.03)
