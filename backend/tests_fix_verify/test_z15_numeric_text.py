# -*- coding: utf-8 -*-
"""Z-15 回归：数字文本的识别口径（「看起来是数字」的串不得静默变字符串）。

背景：Z-03 已经把 `sheet_spec._as_scalar` 从「`\\d` 正则 + `float()`」改成「只认半角十进制」。
本用例把该口径**锁死**，避免以后又被"顺手"改回宽容解析：

- `'1,000'` / `'1,000.50'` / `'50%'` / `'100元'` / `'(100)'` / `'--'` / `'1_000'` / `'1e3'`
  ⇒ 一律**原样保留文本**（改前 `'1_000'`→1000.0、`'1e3'`→1000.0，是纯意外行为）；
- 数值列收到这些串时必须给出**中文可读**错误（而不是英文 ValueError 或静默入库）；
- 文本列（产地/备注/载具名称）照常原样入库 —— 这是"保精度"的既定口径；
- 全角数字继续报错（Z-03），半角正常数值继续转换。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z15_numeric_text
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from sheet_spec import SHEET_BY_NAME, SheetFormatError, _as_scalar, _check_num, _num_or_none  # noqa: E402

# 审计里点名的「数字文本」：都不满足半角十进制形态
NUMERIC_LOOKALIKES = ["1,000", "1,000.50", "50%", "100元", "(100)", "--", "1_000", "1e3", "1E3", "１２３"]


class Z15ScalarTests(SimpleTestCase):
    def test_lookalikes_stay_text(self):
        """改前 `1_000`→1000.0、`1e3`→1000.0（`float()` 宽容解析）；现在全部原样保留。"""
        for text in NUMERIC_LOOKALIKES:
            if text == "１２３":
                with self.assertRaises(SheetFormatError) as cm:
                    _as_scalar(text)
                self.assertIn("全角数字", str(cm.exception))
                continue
            self.assertEqual(
                _as_scalar(text), text,
                f"{text!r} 必须原样保留文本（不得被 float() 静默转成数字）",
            )

    def test_plain_numbers_still_convert(self):
        """回归：正常半角数值照常转换（整数 → int，小数 → float）。"""
        self.assertEqual(_as_scalar("100"), 100)
        self.assertIsInstance(_as_scalar("100"), int)
        self.assertEqual(_as_scalar("-5"), -5)
        self.assertEqual(_as_scalar("3.5"), 3.5)
        self.assertEqual(_as_scalar(".5"), 0.5)
        self.assertEqual(_as_scalar("12."), 12.0)
        self.assertEqual(_as_scalar(""), "")

    def test_num_or_none_rejects_lookalikes(self):
        for text in NUMERIC_LOOKALIKES:
            self.assertIsNone(
                _num_or_none(text),
                f"{text!r} 不是合法半角十进制数，必须判为「非数字」",
            )
        self.assertEqual(_num_or_none("12.5"), 12.5)
        self.assertIsNone(_num_or_none(""))
        self.assertIsNone(_num_or_none(None))


class Z15ColumnMessageTests(SimpleTestCase):
    def test_numeric_column_error_is_chinese_and_quotes_value(self):
        """数值列收到「看起来是数字」的串时必须给中文提示（而不是英文 ValueError）。"""
        for text in NUMERIC_LOOKALIKES:
            with self.assertRaises(SheetFormatError) as cm:
                _check_num("每升单价", text, 0)
            msg = str(cm.exception)
            self.assertIn("必须是数字", msg, f"{text!r} 的错误提示：{msg}")
            self.assertIn(text, msg, f"提示里应回显原始取值：{msg}")

    def test_valid_number_passes(self):
        _check_num("每升单价", "7.6", 0)      # 不抛异常即通过

    def test_negative_still_blocked(self):
        with self.assertRaises(SheetFormatError) as cm:
            _check_num("每升单价", "-7.6", 0)
        self.assertIn("不能小于", str(cm.exception))


class Z15TextColumnTests(SimpleTestCase):
    def test_text_columns_keep_lookalikes_verbatim(self):
        """文本列（产地/备注/载具名称）里 `1,000` 这类串照常原样入库 —— 既定「保精度」口径。"""
        region = SHEET_BY_NAME["区域"]
        rows = [
            ["区域名称", "说明"],
            ["甲区", "备注：1,000 元/吨"],
            ["1,000", "名称本身就是这个串"],
        ]
        data = [(no, row) for no, row in _table_rows(region, rows)]
        self.assertEqual([row.get("name") for _no, row in data], ["甲区", "1,000"])
        self.assertEqual(data[0][1].get("description"), "备注：1,000 元/吨")


def _table_rows(spec, table):
    from build_from_sheets import _table_rows as impl

    return impl(spec, table)
