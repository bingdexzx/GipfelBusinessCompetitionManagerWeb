# -*- coding: utf-8 -*-
"""CW-18 验证：科目定位必须显式校验，`Find` 未命中不得变成静默漏账。

缺陷（改前 `shang.py` 的 `add_book_assets`）：
    found_cell = search_range.Find(What=name.value, LookIn=xlValues)
    rowT = found_cell.Row-1; colunmT = found_cell.Column-1; rowT += 3
完全不检查 `Find` 的返回值：
1. 账套换版 / 科目改名 / 名称多一个空格（枚举里 13 个中文名必须与模板**逐字**一致，`Find` 还在
   `UsedRange` 内任意列搜索）导致**未命中** ⇒ `found_cell` 是 `None` ⇒ `found_cell.Row` 抛
   AttributeError ⇒ 被 watcher 的 `dispatch` 吞掉 ⇒ 该合同**静默漏账**（且按 CW-02 永不重试）。
2. `Find` 命中标题/说明/合计行里的同名文本 ⇒ 代码继续按 `+3` 行向下找「两个空 formula
   单元格」写入 ⇒ **金额落进无关区域**，账表被污染且没有任何报错。
3. 定位循环没有上界：一旦条件永不满足就 `while True` 死循环。

改后：显式判 `found_cell is None` 并抛中文 ValueError；校验命中列必须是科目名称列（A 列）、
推导出的写入起点必须在表内，否则同样报错（提示疑似命中标题行），不再往无关区域写。

xlwings 未安装（记账样例只在真实环境跑），故这里注入假 xlwings 后按路径加载真实 shang.py。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw18_subject_lookup.py
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
    value = 1

    def __call__(self, **_kw):
        return self


class _Addr:
    def __init__(self, address: str):
        self.address = address

    @property
    def api(self):
        outer = self

        class _Api:
            def Cut(self):
                pass

        return _Api()

    def paste(self):
        pass


class Cell:
    def __init__(self, value=None, formula="", address="A1"):
        self.value = value
        self.formula = formula
        self.color = None
        self.address = address
        self.options = _Opts()

    def get_address(self, **_kw):
        return self.address


class SubjectSheet:
    """明细账汇总表：`Find` 返回可配置结果；其余单元格按「空」返回。"""

    def __init__(self, total_rows=40, find_result=None):
        self.cells: dict[tuple[int, int], Cell] = {}
        self.total_rows = total_rows
        self.find_result = find_result
        self.find_calls: list[str] = []

    def cell(self, r, c) -> Cell:
        return self.cells.setdefault((r, c), Cell(address=f"{chr(65+c)}{r+1}"))

    @property
    def used_range(self):
        total = self.total_rows

        class _LC:
            row = total

        class _Used:
            last_cell = _LC

        return _Used()

    @property
    def api(self):
        outer = self

        class _UsedRange:
            def Find(self, **kw):
                outer.find_calls.append(kw.get("What"))
                return outer.find_result

        class _Api:
            def __init__(self):
                self.UsedRange = _UsedRange()

        return _Api()

    def __getitem__(self, key):
        return self.cells.setdefault(key, Cell(address=f"{chr(65+key[1])}{key[0]+1}"))

    def range(self, *_a, **_kw):
        return _Addr("A1")


class FoundCell:
    """`Find` 命中结果（1 基行列 + Address）。"""

    def __init__(self, row=5, col=1):
        self.Row = row
        self.Column = col
        self.Address = f"${chr(64+col)}${row}"


class AssetBook(FakeBook):
    def __init__(self, sheet):
        super().__init__()
        self.sheets = [FakeSheet() for _ in range(4)] + [sheet] + [FakeSheet() for _ in range(5)]


def load_editor(sheet):
    mod = load_shang()
    # 假 xlwings 没有 constants（本文件用到 `xw.constants.FindLookIn.xlValues`），补一个占位
    sys.modules["xlwings"].constants = types.SimpleNamespace(
        FindLookIn=types.SimpleNamespace(xlValues=1)
    )
    book = AssetBook(sheet)
    app = FakeApp()
    app.last_book = book
    editor = mod.xledit.__new__(mod.xledit)
    editor.xlapp = app
    editor.wb = book
    return mod, editor


class Cw18SubjectLookupTests(unittest.TestCase):
    def test_missing_subject_raises_readable_error(self):
        """改前：`found_cell.Row` 抛 AttributeError（被上层吞掉 ⇒ 静默漏账）。"""
        sheet = SubjectSheet(find_result=None)
        mod, editor = load_editor(sheet)
        with self.assertRaises(ValueError) as ctx:
            editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, "100", "0")
        msg = str(ctx.exception)
        self.assertIn("银行存款", msg, f"错误信息必须点明科目名，实际 {msg!r}")
        self.assertIn("找不到", msg)
        self.assertEqual(sheet.find_calls, ["银行存款"], "应确实查过该科目")

    def test_wrong_column_hit_is_rejected(self):
        """`Find` 命中非科目列（标题/说明行里的同名文本）→ 必须报错，不得往无关区域写。"""
        sheet = SubjectSheet(find_result=FoundCell(row=5, col=3))
        mod, editor = load_editor(sheet)
        with self.assertRaises(ValueError) as ctx:
            editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, "100", "0")
        self.assertIn("定位不可信", str(ctx.exception))
        self.assertEqual(sheet.cells, {}, "报错路径不得写任何单元格")

    def test_start_row_beyond_table_is_rejected(self):
        """命中行靠表尾 → 推导出的写入起点越界，必须报错（改前会写到表外/最后一行）。"""
        sheet = SubjectSheet(total_rows=10, find_result=FoundCell(row=9, col=1))
        mod, editor = load_editor(sheet)
        with self.assertRaises(ValueError) as ctx:
            editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, "100", "0")
        self.assertIn("定位不可信", str(ctx.exception))

    def test_valid_hit_still_writes(self):
        """回归：正常命中科目名称列时，金额照常写入推导出的位置。"""
        sheet = SubjectSheet(total_rows=40, find_result=FoundCell(row=5, col=1))
        mod, editor = load_editor(sheet)
        editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, "100.5", "0")
        # rowT = 5-1+3 = 7（0 基），colunmT = 0；空槽分支写 (7,0)/(7,1)
        self.assertEqual(sheet.cells[(7, 0)].value, 100.5)
        self.assertEqual(sheet.cells[(7, 1)].value, 0)

    def test_liability_swap_unchanged(self):
        """回归：负债/权益类的借贷互换行为不变。"""
        sheet = SubjectSheet(total_rows=40, find_result=FoundCell(row=5, col=1))
        mod, editor = load_editor(sheet)
        book_sheets = list(editor.wb.sheets)
        book_sheets[5] = sheet
        editor.wb.sheets = book_sheets
        editor.add_book_assets(
            mod.BOOOKTYPE.LIABILITIES, mod.LIABILITIES.ADVANCE_RECEIVABLES, "7", "3"
        )
        self.assertEqual(sheet.cells[(7, 0)].value, 3, "负债类应互换：add 变 minus")
        self.assertEqual(sheet.cells[(7, 1)].value, 7)

    def test_repeated_calls_use_their_own_subject(self):
        """回归：同一实例连续记两个科目，Find 的查询名各自正确。"""
        sheet = SubjectSheet(total_rows=40, find_result=FoundCell(row=5, col=1))
        mod, editor = load_editor(sheet)
        editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.BANK_DEPOSITS, "1", "0")
        editor.add_book_assets(mod.BOOOKTYPE.ASSETS, mod.ASSET.LAND_USE_RIGHTS, "2", "0")
        self.assertEqual(sheet.find_calls, ["银行存款", "土地使用权"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
