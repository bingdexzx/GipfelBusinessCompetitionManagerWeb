# -*- coding: utf-8 -*-
"""Z-12 验证：Excel 错误值不得被当普通文本写进比赛。

缺陷（改前）：`xlsx_io._cell_text` 对 `t="e"`（错误值单元格）与普通文本一视同仁，直接返回
`#DIV/0!` / `#N/A` 这类错误码；落在文本列上会**原样写进比赛** —— 库里出现一个叫 `#DIV/0!`
的原料名或公司名（若它在首列则触发 Z-01 被整行丢弃）；数值列则因 `float()` 失败报一个
不友好的 ValueError。用户屏幕上看到的是公式算错，工具却把错误码当成数据。

改后：`_table_rows` 显式拒绝含 Excel 错误值的行，报错里给出**行号 + 表头名 + 错误码**，
让用户回去修公式；正常的 `#` 开头名称（如 `#1 号矿区`）不受影响。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z12_excel_error_values -v 2
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import _table_rows  # noqa: E402

try:  # 改前不存在该常量（错误值与普通文本一视同仁）
    from build_from_sheets import EXCEL_ERROR_VALUES  # noqa: E402
except ImportError:  # pragma: no cover - 仅在“改前”状态下走到
    EXCEL_ERROR_VALUES = frozenset({"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!"})
from sheet_spec import SHEET_BY_NAME, SheetFormatError  # noqa: E402

REGION = SHEET_BY_NAME["区域"]


class ExcelErrorValueTests(SimpleTestCase):
    def rows(self, table):
        return _table_rows(REGION, table)

    def test_error_values_are_rejected_with_location(self):
        for err in sorted(EXCEL_ERROR_VALUES):
            table = [["区域名称", "说明"], ["甲", err]]
            with self.assertRaises(SheetFormatError, msg=err) as cm:
                self.rows(table)
            msg = str(cm.exception)
            self.assertIn(err, msg, f"应指出错误值：{msg}")
            self.assertIn("第 2 行", msg, f"应指出行号：{msg}")
            self.assertIn("说明", msg, f"应指出原始表头名：{msg}")

    def test_error_value_in_first_column_is_rejected_not_silently_dropped(self):
        """首列错误值：改前被当注释整行丢弃，现在必须显式报错（不得静默丢数据）。"""
        with self.assertRaises(SheetFormatError) as cm:
            self.rows([["区域名称", "说明"], ["#REF!", "引用被删了"], ["乙", ""]])
        self.assertIn("#REF!", str(cm.exception))

    def test_hash_prefixed_names_are_not_error_values(self):
        """回归：#1 号矿区 这类正式名称不是错误值，照常录入。"""
        data = self.rows([["区域名称", "说明"], ["#1 号矿区", "正式名称"], ["乙区", ""]])
        self.assertEqual([r.get("name") for _no, r in data], ["#1 号矿区", "乙区"])

    def test_normal_rows_unaffected(self):
        data = self.rows([["区域名称", "说明"], ["甲", "普通说明"]])
        self.assertEqual([r.get("name") for _no, r in data], ["甲"])
