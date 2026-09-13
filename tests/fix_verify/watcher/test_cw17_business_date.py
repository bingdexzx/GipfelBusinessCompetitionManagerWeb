# -*- coding: utf-8 -*-
"""CW-17 验证：账期必须取合同执行时间，而不是「运行当天」。

缺陷（改前）：`shang.py` 的 `add_book_entries` 里
    cdt = dt.date.today(); dtstr = cdt.strftime("%Y/%m/%d"); sht[i,0].value = dtstr
账期一律是**运行当天**。而任何「延迟处理」都会发生：`--backfill` 补存量、后端/凭据故障恢复后
补记（CW-10）、监听程序停机几天后重启、CW-01/CW-02 的重试。于是昨天甚至上季度通过的合同被记成
**今天**发生的业务 ⇒ 跨天/跨月/跨财年错期，与合同 `executedAt` 无法对账。
函数签名 `add_book_entries(add, minus, number, about)` 里根本没有日期参数，说明这是设计缺口。

改后：新增 `business_date` 参数（+ `parse_business_date` / `format_business_date`）：
调用方传合同 `executedAt`（后端是 UTC，会换算到本地时区再取日期），缺省仍是运行当天（旧行为）。

xlwings 未安装（记账样例只在真实环境跑），故这里注入假 xlwings 后按路径加载真实 shang.py。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw17_business_date.py
"""
from __future__ import annotations

import datetime as dt
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw08_cw09_bookkeeping import FakeApp, FakeBook, FakeSheet, load_shang  # noqa: E402

UTC8 = timezone(timedelta(hours=8))


class _Opts:
    """`Range.options(numbers=int)` 的替身（序号列走「非首行」分支）。"""

    value = 1

    def __call__(self, **_kw):
        return self


class Cell:
    """可写单元格：`value is None` 表示从未写入。"""

    def __init__(self, r=0, c=0):
        self.value = None
        self.formula = ""
        self.options = _Opts()
        self.r, self.c = r, c

    def get_address(self, **_kw):
        return f"Sheet1!${chr(65 + self.c)}${self.r + 1}"


class LedgerSheet:
    """记账表（sheets[0]）：按 (row, col) 记录写入。"""

    def __init__(self, first_free_row=2):
        self.cells: dict[tuple[int, int], Cell] = {}
        self.first_free_row = first_free_row

    @property
    def used_range(self):
        first = self.first_free_row

        class _LC:
            row = first + 30

        class _Used:
            last_cell = _LC

        return _Used()

    def __getitem__(self, key):
        r, c = key
        # G 列（摘要）在第一个空行上是空的 → add_book_entries 认为这里是下一行
        if c == 6 and r >= self.first_free_row:
            return self.cells.setdefault((r, c), Cell(r, c))
        return self.cells.setdefault((r, c), Cell(r, c))


class LedgerBook(FakeBook):
    def __init__(self):
        super().__init__()
        self.ledger = LedgerSheet()
        self.sheets = [self.ledger] + [FakeSheet() for _ in range(9)]


def load_ledger():
    mod = load_shang()
    book = LedgerBook()
    app = FakeApp()
    app.last_book = book
    editor = mod.xledit.__new__(mod.xledit)   # 绕过 __init__ 的 Excel 启动
    editor.xlapp = app
    editor.wb = book
    return mod, editor, book


def written_date(book) -> str | None:
    """取第一个写了摘要（G 列）的那一行的 A 列（账期）值。"""
    rows = sorted({r for (r, c) in book.ledger.cells if c == 6 and book.ledger.cells[(r, c)].value})
    return book.ledger.cells.get((rows[0], 0)).value if rows else None


class Cw17BusinessDateTests(unittest.TestCase):
    # ---------- 纯函数 ----------

    def test_utc_executed_at_converts_to_local_date(self):
        mod = load_shang()
        # 2026-09-10T15:20:46Z = 北京时间 2026-09-10 23:20:46 → 当天
        self.assertEqual(mod.parse_business_date("2026-09-10T15:20:46.731818Z", UTC8), dt.date(2026, 9, 10))
        # 2026-09-10T22:30:00Z = 北京时间次日 06:30 → 次日
        self.assertEqual(mod.parse_business_date("2026-09-10T22:30:00Z", UTC8), dt.date(2026, 9, 11))

    def test_accepted_input_shapes(self):
        mod = load_shang()
        self.assertEqual(mod.parse_business_date(dt.date(2026, 3, 1), UTC8), dt.date(2026, 3, 1))
        self.assertEqual(
            mod.parse_business_date(datetime(2026, 3, 1, 8, 0, tzinfo=UTC8), UTC8),
            dt.date(2026, 3, 1),
        )
        self.assertEqual(
            mod.parse_business_date("2026-03-01 08:00:00", UTC8), dt.date(2026, 3, 1),
            "无时区的时间戳按 UTC 解读（后端约定）",
        )

    def test_unparsable_values_fall_back_to_today(self):
        mod = load_shang()
        today = dt.date.today().strftime("%Y/%m/%d")
        for bad in (None, "", "   ", "不是时间", "2026/13/45"):
            self.assertIsNone(mod.parse_business_date(bad, UTC8))
            self.assertEqual(
                mod.format_business_date(bad, UTC8), today,
                f"{bad!r} 无法解析时必须回退运行当天（不能崩、也不能写坏账期）",
            )

    def test_format_uses_slash_form(self):
        mod = load_shang()
        self.assertEqual(mod.format_business_date("2026-09-10T15:20:46Z", UTC8), "2026/09/10")

    # ---------- 端到端 ----------

    def test_entry_date_comes_from_contract_executed_at(self):
        """改前：A 列恒为运行当天；改后：等于 executedAt 的本地日期。"""
        mod, editor, book = load_ledger()
        editor.add_book_entries(
            add="100", minus=0, number="HT-1", about="补记", business_date="2026-09-10T15:20:46Z",
        )
        got = written_date(book)
        self.assertEqual(got, "2026/09/10", f"账期必须等于合同执行日期，实际 {got!r}")
        self.assertNotEqual(
            got, dt.date.today().strftime("%Y/%m/%d"),
            "延迟处理时账期不得是运行当天（改前的行为）",
        )

    def test_delayed_backfill_keeps_original_period(self):
        """补去年同期（跨财年）的存量合同时，账期必须仍落在原期间。"""
        mod, editor, book = load_ledger()
        editor.add_book_entries(
            add="1000", minus=0, number="HT-2", about="补记去年",
            business_date="2025-12-31T16:30:00Z",   # 北京时间 2026-01-01 00:30
        )
        self.assertEqual(written_date(book), "2026/01/01", "必须按本地时区落到次日")

    def test_default_keeps_old_behaviour(self):
        """回归：不传 business_date 时仍是运行当天（老调用方不受影响）。"""
        mod, editor, book = load_ledger()
        editor.add_book_entries(add="1", minus=0, number="HT-3", about="默认")
        self.assertEqual(written_date(book), dt.date.today().strftime("%Y/%m/%d"))

    def test_decimal_date_object_accepted(self):
        mod, editor, book = load_ledger()
        editor.add_book_entries(
            add="1", minus=0, number="HT-4", about="date 对象", business_date=dt.date(2024, 6, 30),
        )
        self.assertEqual(written_date(book), "2024/06/30")


if __name__ == "__main__":
    unittest.main(verbosity=2)
