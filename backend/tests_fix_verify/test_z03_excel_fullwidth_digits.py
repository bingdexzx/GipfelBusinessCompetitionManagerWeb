# -*- coding: utf-8 -*-
"""Z-03 验证：建包不得静默归一化全角/指数写法的数字标识。

缺陷（改前）：
  1. `_as_scalar` 用 `re.fullmatch(r"[+-]?\\d+", s)`，而 Python 的 `\\d` 也匹配**全角数字**：
     `_as_scalar('１００') -> 100`、`_as_scalar('１') -> 1`；产业类型 code 走
     `int(float(code))`，`float('００１０')` = 10.0 → **全局标识被悄悄改写**：表格里写 `００１０`
     会导入成 `10`，与库里既有 code 撞车后导入侧按 code 复用并覆盖对方的名称/描述。
  2. `float()` 还接受 `1e3` / `1_000`：文本被当成二进制浮点，教程里「金额/数量写数字文本保精度」
     的承诺不成立。

改后：只认半角数字（`[+-]?[0-9]+` / `[+-]?[0-9]*\\.[0-9]+`）；全角数字直接报错并提示改用半角；
指数/下划线等写法按文本原样保留（不再被静默改成 float）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z03_excel_fullwidth_digits -v 2
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from sheet_spec import SHEET_BY_NAME, SheetContext, SheetFormatError, _as_scalar, _num_or_none  # noqa: E402


class _FakeBuilder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None

        return _rec


def ctx():
    return SheetContext(builder=_FakeBuilder())


class ScalarParsingTests(SimpleTestCase):
    def test_fullwidth_digits_are_rejected_not_normalized(self):
        for text in ["１００", "００１０", "１２３.４５", "矿石:１"]:
            with self.assertRaises(SheetFormatError, msg=text):
                _as_scalar(text)

    def test_halfwidth_numbers_still_parse(self):
        self.assertEqual(_as_scalar("100"), 100)
        self.assertEqual(_as_scalar("-3"), -3)
        self.assertEqual(_as_scalar("+3"), 3)
        self.assertEqual(_as_scalar("0.35"), 0.35)
        self.assertEqual(_as_scalar(".5"), 0.5)
        self.assertEqual(_as_scalar("007"), 7)

    def test_exponent_and_underscore_are_kept_as_text(self):
        """改前 float() 会把它们悄悄变成 1000.0（文本精度保证不成立）。"""
        self.assertEqual(_as_scalar("1e3"), "1e3")
        self.assertEqual(_as_scalar("1_000"), "1_000")
        self.assertEqual(_as_scalar("nan"), "nan")
        self.assertEqual(_as_scalar("inf"), "inf")

    def test_text_values_unchanged(self):
        self.assertEqual(_as_scalar("待定"), "待定")
        self.assertEqual(_as_scalar(""), "")
        self.assertEqual(_as_scalar("N1"), "N1")

    def test_num_or_none_is_ascii_only(self):
        self.assertEqual(_num_or_none("180"), 180.0)
        self.assertIsNone(_num_or_none("１８０"), "全角数字不得被 float() 接受")
        self.assertIsNone(_num_or_none("1e3"), "指数写法不再当数字")
        self.assertIsNone(_num_or_none(""))


class IndustryCodeTests(SimpleTestCase):
    """产业类型 code 是全局标识：全角写法必须报错，半角照常。"""

    def test_fullwidth_code_is_rejected(self):
        handler = SHEET_BY_NAME["产业类型"].handler
        with self.assertRaises(SheetFormatError):
            handler(ctx(), {"code": "００１０", "name": "某产业"})

    def test_halfwidth_code_is_accepted(self):
        builder = _FakeBuilder()
        c = SheetContext(builder=builder)
        SHEET_BY_NAME["产业类型"].handler(c, {"code": "0010", "name": "某产业"})
        self.assertEqual(builder.calls[0][0], "industry_type")
        self.assertEqual(builder.calls[0][1][0], 10)

    def test_non_numeric_code_is_rejected(self):
        handler = SHEET_BY_NAME["产业类型"].handler
        with self.assertRaises(SheetFormatError):
            handler(ctx(), {"code": "一号产业", "name": "某产业"})
