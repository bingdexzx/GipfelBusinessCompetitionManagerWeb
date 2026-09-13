# -*- coding: utf-8 -*-
"""CW-14 验证：记账金额必须显式校验，不得用裸 `float()` 静默出错。

缺陷（改前）：`shang.py:92/94` 是
    if (add != 0):   sht[i,3].value = float(add)
    if (minus != 0): sht[i,4].value = float(minus)
而 README 教程教 handler 直接取 `contract["inputs"].get("amount")`，`DATA_GUIDE.md` 又明确
「未填写的输入项不会出现」且金额可能是字符串：
  - `amount is None` ⇒ `None != 0` 为真 ⇒ `float(None)` **TypeError**；
  - `""` / `"1,000"` ⇒ **ValueError**；
  两者都被 `contract_watcher.py:dispatch` 吞掉 ⇒ 合同标记为「已处理」但**一条分录都没有**
  （静默漏账、永不重试）。
  - `>15` 位有效数字经 float → Excel double 静默丢低位（`12345678901234567890` → `1.23456789012346E+19`）。
  - `add=minus=0` 时 D/E 两列都不写，只留下摘要与余额公式（借贷两列不对齐的「空金额行」）。

改后：金额统一走 `_as_amount()`（`Decimal(str(v))` + 显式拒绝 None/空串/bool/非数字），
校验失败抛**中文 ValueError**（让上层记入待处理队列并重试，而不是被吞）；
0 也写入 `0` 以保持借贷两列对齐；数值仍以 float 落入 Excel（Excel 单元格只支持 double），
但超出 double 精确整数范围的金额会被**显式拒绝**，不再静默丢低位。

xlwings 未安装（记账样例只在真实环境跑），故这里注入假 xlwings 后按路径加载真实 shang.py。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw14_amount_conversion.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw08_cw09_bookkeeping import FakeApp, FakeBook, FakeSheet, load_shang  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


class _Opts:
    """`sht[i,j].options(numbers=int).value` 的替身（序号列走「非首行」分支）。

    xlwings 的 `Range.options` 是**可调用**属性，返回一个带 `.value` 的 Range 视图。
    """

    value = 1

    def __call__(self, **_kw):
        return self


class _EmptyRange:
    """空单元格：value/formula 均为 None。"""

    value = None
    formula = None
    options = _Opts()


class Cell:
    """可写单元格：value 为 None 即「从未写入」（据此区分「写入 0」与「没写」）。

    `formula` 默认 `""`（与真实 xlwings 一致：空单元格的 formula 是空串而不是 None）。
    """

    def __init__(self, r=0, c=0):
        self.value = None
        self.formula = ""
        self.options = _Opts()
        self.r, self.c = r, c

    def get_address(self, **_kw):
        return f"Sheet1!${chr(65 + self.c)}${self.r + 1}"


class RecordingSheet:
    """按 (row, col) 记录写入的假工作表（0 基，与 xlwings 一致）。"""

    def __init__(self, first_free_row=2):
        self.cells: dict[tuple[int, int], Cell] = {}
        self.first_free_row = first_free_row
        self.summary_cell: Cell | None = None
        self.data_row: int | None = None

    @property
    def used_range(self):
        first_free_row = self.first_free_row

        class _LC:
            row = first_free_row + 20

        class _Used:
            last_cell = _LC

        return _Used()

    def __getitem__(self, key):
        r, c = key
        # G 列（col 6）在「第一个空行」上是空的 → add_book_entries 认为这里是可写的下一行
        if c == 6 and r >= self.first_free_row:
            if self.summary_cell is None:
                self.summary_cell = Cell(r, c)
                self.data_row = r
            return self.summary_cell
        return self.cells.setdefault((r, c), Cell(r, c))


class RecordingBook(FakeBook):
    def __init__(self):
        super().__init__()
        self.ledger = RecordingSheet()   # sheets[0]：记账
        self.assets = RecordingSheet()   # sheets[4]：资产负债
        self.sheets = [self.ledger] + [FakeSheet() for _ in range(3)] + [self.assets] + [
            FakeSheet() for _ in range(4)
        ]


def load_editor():
    mod = load_shang()
    # 假 xlwings 没有 constants（本文件用到 `xw.constants.FindLookIn.xlValues`），补一个占位
    sys.modules["xlwings"].constants = types.SimpleNamespace(
        FindLookIn=types.SimpleNamespace(xlValues=1)
    )
    book = RecordingBook()
    app = FakeApp()
    app.last_book = book
    editor = mod.xledit.__new__(mod.xledit)  # 绕过 __init__ 的 Excel 启动
    editor.xlapp = app
    editor.wb = book
    return mod, editor, book


class _Found:
    """`Find` 命中的科目单元格（1 基行列，与 COM 一致）。

    `Row=4, Column=3` ⇒ `rowT = 4-1+3 = 6`、`colunmT = 3-1 = 2`（0 基），
    即写入位置为 `(6,2)/(6,3)`、上一列为 `(6,1)`。
    """

    Row = 4
    Column = 3


class _FindApi:
    """`sht.api` 替身：`UsedRange.Find(...)` → 命中单元格。"""

    class _UsedRange:
        def Find(self, **_kw):
            return _Found()

    UsedRange = _UsedRange()


def _asset_sheet() -> "RecordingSheet":
    """资产负债表的假工作表：命中科目后 rowT=6、colunmT=2（0 基），上一列为空 ⇒ 走空槽分支。"""

    class _Api:
        def Cut(self):
            pass

    class _R:
        address = "C5"
        api = _Api()

        def paste(self):
            pass

    class _Sheet(RecordingSheet):
        api = _FindApi()

        def range(self, *_a, **_k):
            return _R()

    sheet = _Sheet()
    sheet.cells[(6, 1)] = Cell(6, 1)  # (rowT, colunmT-1) 为空 ⇒ 命中空槽分支，写 (6,2)/(6,3)
    return sheet


class Cw14AmountTests(unittest.TestCase):
    def _add(self, add, minus, sheet=None):
        """调用 add_book_entries 并返回 (D 列值, E 列值)；None 表示该列从未写入。"""
        _mod, editor, book = load_editor()
        editor.add_book_entries(add=add, minus=minus, number="HT-1", about="测试摘要")
        target = sheet if sheet is not None else book.ledger
        self.assertIsNotNone(target.summary_cell, "应写入一行摘要（G 列）")
        self.assertEqual(target.summary_cell.value, "HT-1 测试摘要", "摘要内容不得改变")
        row = target.data_row
        d = target.cells.get((row, 3))
        e = target.cells.get((row, 4))
        return (d.value if d else None), (e.value if e else None)

    def test_none_amount_raises_chinese_error(self):
        """改前：float(None) → TypeError，被上层吞掉 ⇒ 静默漏账。"""
        with self.assertRaises(ValueError) as ctx:
            self._add(None, 0)
        self.assertIn("金额", str(ctx.exception))
        self.assertIn("None", str(ctx.exception))

    def test_empty_string_amount_raises_chinese_error(self):
        """改前：float('') → ValueError（英文），被上层吞掉 ⇒ 静默漏账。"""
        with self.assertRaises(ValueError) as ctx:
            self._add("", 0)
        self.assertIn("金额", str(ctx.exception))

    def test_thousands_separator_string_raises_chinese_error(self):
        """改前：float('1,000') → ValueError（英文），被上层吞掉 ⇒ 静默漏账。"""
        with self.assertRaises(ValueError) as ctx:
            self._add("1,000", 0)
        self.assertIn("金额", str(ctx.exception))
        self.assertIn("1,000", str(ctx.exception))

    def test_bool_amount_rejected(self):
        """`True` 是 int 的子类，但它是「有没有填」而不是金额，必须拒绝。"""
        with self.assertRaises(ValueError):
            self._add(True, 0)

    def test_numeric_string_and_zero_minus_are_written(self):
        """正常路径不回归：数字串照常写入；minus=0 也写入 0（改前不写）。"""
        d, e = self._add("123.45", 0)
        self.assertEqual(d, 123.45)
        self.assertEqual(e, 0, "minus=0 也必须写入 0，保持借贷两列对齐")

    def test_decimal_amount_is_accepted(self):
        from decimal import Decimal

        d, _e = self._add(Decimal("0.1"), 0)
        self.assertEqual(d, 0.1)

    def test_zero_both_columns_written(self):
        """改前 add=minus=0 时 D/E 两列都不写 → 留下「空金额行」。"""
        d, e = self._add(0, 0)
        self.assertEqual(d, 0, "0 也必须写入 D 列")
        self.assertEqual(e, 0, "0 也必须写入 E 列")

    def test_out_of_double_range_rejected_instead_of_losing_digits(self):
        """改前：12345678901234567890 经 float 静默变成 1.23456789012346E+19。"""
        with self.assertRaises(ValueError) as ctx:
            self._add("12345678901234567890", 0)
        self.assertIn("精确表示", str(ctx.exception))

    def test_none_is_rejected_as_unfilled_not_as_typeerror(self):
        """改前 `None != 0` 为真 → float(None) TypeError；改后必须是可读的「未填写」。"""
        with self.assertRaises(ValueError) as ctx:
            self._add(0, None)
        self.assertIn("未填写", str(ctx.exception))

    def test_double_safe_large_amount_unchanged(self):
        """回归：仍在 double 精确整数范围内的金额照常写入。"""
        d, _e = self._add("9007199254740992", 0)  # 2**53
        self.assertEqual(d, 9007199254740992.0)

    def test_negative_amount_is_allowed(self):
        """回归：负数金额是合法业务值（方向由借贷列决定），不得被当成非法输入。"""
        d, e = self._add("-5.5", 0)
        self.assertEqual(d, -5.5)
        self.assertEqual(e, 0)

    def test_asset_amounts_are_validated_too(self):
        """`add_book_assets` 的 add/minus 是同一类金额，也必须走校验（改前 float(None)）。"""
        mod, editor, book = load_editor()
        sheet = _asset_sheet()
        book.sheets[4] = sheet

        with self.assertRaises(ValueError) as ctx:
            editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, None, 0)
        self.assertIn("金额", str(ctx.exception))

    def test_asset_valid_amounts_still_written(self):
        """回归：合法金额在 `add_book_assets` 里照常写入两列。"""
        mod, editor, book = load_editor()
        sheet = _asset_sheet()
        book.sheets[4] = sheet

        editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, "100.5", "0")
        self.assertEqual(sheet.cells[(6, 2)].value, 100.5)
        self.assertEqual(sheet.cells[(6, 3)].value, 0)

    def test_asset_amounts_are_validated_too(self):
        """`add_book_assets` 的 add/minus 是同一类金额，也必须走校验（改前 float(None)）。"""
        mod, editor, _book = load_editor()

        class _Found:
            Row = 5
            Column = 3

        class _Api:
            UsedRange = object()

        class _Sheet(RecordingSheet):
            api = _Api()

            def range(self, *_a, **_k):  # 仅用于 address 取址
                class _R:
                    address = "C5"

                return _R()

        sheet = _Sheet()
        sheet.cells.setdefault((6, 2), Cell())  # (rowT, colunmT-1) 命中空槽条件

        class _FindRange:
            def Find(self, **_k):
                return _Found()

        sheet.api = _FindRange()
        editor.wb.sheets[4] = sheet
        with self.assertRaises(ValueError) as ctx:
            editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, None, 0)
        self.assertIn("金额", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
