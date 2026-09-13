# -*- coding: utf-8 -*-
"""Z-01 验证：Excel 建包不得把「首列以 # 开头」的真实数据行当注释丢掉。

缺陷（改前）：`_table_rows` 只判断首格是否以 `#` / `//` 开头就整行跳过，于是
  - 公式错误值所在的数据行（`#N/A` / `#REF!` / `#DIV/0!` …）整行静默消失 —— 恰恰是
    「VLOOKUP 没匹配上」这种最该被看见的一行；
  - 以 `#` 开头的正式名称（`#1 号矿区`）无法录入；
  且 `--inspect` 的「已处理 N 行」、`--out` 归档、导入结果会**一致地**少一行，没有任何提示。
改后：只有「首格以 # / // 开头且该行没有其它非空单元格」才算整行注释。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z01_excel_comment_rows -v 2
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import _table_rows  # noqa: E402
from sheet_spec import SHEET_BY_NAME, SheetFormatError  # noqa: E402

try:  # 改前不存在该函数（只有内联的 startswith 判断）
    from build_from_sheets import is_comment_row  # noqa: E402
except ImportError:  # pragma: no cover - 仅在“改前”状态下走到
    is_comment_row = None

REGION = SHEET_BY_NAME["区域"]


class CommentRowTests(SimpleTestCase):
    def rows(self, table):
        return _table_rows(REGION, table)

    def test_formula_error_row_is_rejected_loudly(self):
        """#N/A 数据行：改前被当注释静默丢弃，现在**显式报错**（Z-12 收紧：错误值不得写进比赛）。

        Z-01 的底线是「不得静默丢弃」；Z-12 进一步要求错误值不能被当成普通文本落库，
        故最终采用「明确报错并指出是哪一格」——不再静默丢，也不再静默写脏数据。
        """
        table = [
            ["区域名称", "说明"],
            ["甲", ""],
            ["#N/A", "公式没匹配到的区域"],
            ["乙", ""],
        ]
        with self.assertRaises(SheetFormatError) as cm:
            self.rows(table)
        msg = str(cm.exception)
        self.assertIn("#N/A", msg, f"错误应指出具体的错误值：{msg}")
        self.assertIn("第 3 行", msg, f"错误应指出行号：{msg}")
        self.assertIn("区域名称", msg, f"错误应指出列名：{msg}")

    def test_rows_without_error_values_are_still_parsed(self):
        """回归：没有错误值的行照常解析（行号与内容一致）。"""
        table = [
            ["区域名称", "说明"],
            ["甲", ""],
            ["乙", "公式算出的人文名称"],
        ]
        data = self.rows(table)
        self.assertEqual([row.get("name") for _no, row in data], ["甲", "乙"])
        self.assertEqual([no for no, _row in data], [2, 3], "行号必须与表格一致")

    def test_hash_prefixed_real_name_is_kept(self):
        """以 # 开头的正式名称必须能录入（改前被当注释）。"""
        table = [
            ["区域名称", "说明"],
            ["#1 号矿区", "首列以 # 开头的正式名称"],
            ["乙区", ""],
        ]
        names = [row.get("name") for _no, row in self.rows(table)]
        self.assertEqual(names, ["#1 号矿区", "乙区"], f"实际解析出 {names}")

    def test_real_comment_rows_are_still_skipped(self):
        """回归：整行注释（首格 # / // 且其余为空）仍然跳过。"""
        table = [
            ["区域名称", "说明"],
            ["# 这是整行注释", "", ""],
            ["甲", ""],
            ["// 另一种注释写法", ""],
            ["", "", ""],
            ["乙", ""],
        ]
        data = self.rows(table)
        names = [row.get("name") for _no, row in data]
        self.assertEqual(names, ["甲", "乙"], f"实际解析出 {names}")
        self.assertEqual([no for no, _row in data], [3, 6])

    def test_is_comment_row_semantics(self):
        self.assertIsNotNone(is_comment_row, "改后应导出一行注释判定函数 is_comment_row")
        self.assertTrue(is_comment_row(["# 注释", "", ""]))
        self.assertTrue(is_comment_row(["// 注释"]))
        self.assertFalse(is_comment_row(["#N/A", "有数据"]))
        self.assertFalse(is_comment_row(["#1 号矿区", "有数据"]))
        self.assertFalse(is_comment_row(["甲", ""]))
        self.assertFalse(is_comment_row([]))

    def test_header_detection_unaffected(self):
        """回归：表头识别（跳过前置空行）与表头之后的注释行处理不受影响。"""
        table = [
            ["", ""],
            ["区域名称", "说明"],       # 表头（前置空行会被跳过）
            ["# 表格说明", "", ""],     # 表头之后的整行注释 → 跳过
            ["甲", ""],
        ]
        data = self.rows(table)
        self.assertEqual([row.get("name") for _no, row in data], ["甲"])
        self.assertEqual(data[0][0], 4)
