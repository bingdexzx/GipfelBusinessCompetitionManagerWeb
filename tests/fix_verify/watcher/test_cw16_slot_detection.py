# -*- coding: utf-8 -*-
"""CW-16 验证：货品表槽位判定必须与模板一致，且「没有空槽」时不得覆写最后一行。

缺陷（改前，`shang.py` 的两处判定互相矛盾）：
1. 写数据循环用 `if (sht[i+6,3].value == 0) and (sht[i+6,6].value == 0)` 判「空槽」，而模板
   （实测 `target.xlsx` 的「原材料(加工用)」表：块首 0 基 0/19/39/…、可用槽位数量列 D/G 预置 0、
   数据行由 `sht.range(f'{i+8}:{i+8}').insert()` + `autofill` 插行复制）里被插出来的行是
   **空单元格**（None）——`None == 0` 为假 ⇒ 该槽位被跳过；走到表尾
   `if i == sht.used_range.last_cell.row: break` ⇒ **数量既不写入也不报错**（静默漏记）。
2. 定位循环 `while (i != sht.used_range.last_cell.row)` 走到底后 `i -= 1`，把这行覆写成
   「库存商品成本期末移动平均结转报告」并 `sht.range(f'A{i+1}:L{i+1}').merge()` ——
   0 基索引算出的正是 Excel **最后一行**，合并只保留左上角值，**原数据不可恢复**。

改后：
- 空槽判定统一为 `is_blank_cell`（None / 空串 / 纯空白 / 数值 0 都算空槽，模板用 0 表示「还没用」）；
- 写数据前用 `find_free_row` 在块内显式找空槽行，找不到就抛中文 ValueError（让 watcher 把合同
  留在待处理队列重试），不再走到表尾静默丢弃；
- 定位循环走到底时抛业务异常，**不再覆写最后一行**（原「自动新建块」的破坏性代码已删除）。

xlwings 未安装（记账样例只在真实环境跑），故这里注入假 xlwings 后按路径加载真实 shang.py，
并用稀疏网格工作表按实测几何建模。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw16_slot_detection.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw08_cw09_bookkeeping import load_shang  # noqa: E402

REPO = Path(__file__).resolve().parents[3]

# 实测几何（target.xlsx，1 基行 → 0 基）：块首 1/20/40/…，数量行 6..17（0 基 5..16），
# 「本期采购入库」标签在块首 +7（0 基），插入锚点在块首 +8（0 基）。
BLOCK_STRIDE = 20
TITLE = "库存商品成本期末移动平均结转报告"
UNIT_ROW = "编制单位：XXX公司"
LABEL = "本期采购入库"


class _Opts:
    """`Range.options(numbers=int)` 的替身（序号列按「非首行」处理，值恒为 1）。"""

    value = 1

    def __call__(self, **_kw):
        return self


class R:
    """假 Range（可读可写，带 address / formula / color / options）。"""

    def __init__(self, value=None, address="A1"):
        self.value = value
        self.formula = ""
        self.color = None
        self.address = address
        self.options = _Opts()

    def get_address(self, **_kw):
        return self.address

    def insert(self, **_kw):
        pass

    def autofill(self, *_a, **_kw):
        pass


class GridSheet:
    """按实测几何建模的稀疏网格：模板把候选槽位的数量列预置为 0，物料名列留空。

    `blocks=[(name_or_None, start_row), ...]`：`start_row` 是 0 基块首（标题行）。每块自动生成
      +0 标题行、+1 编制单位行、+4 数量表头行、+5..+16 候选槽位（模板预置 D/G = 0）、
      +7 「本期采购入库」标签、+8 插入锚点；`name` 非 None 时写到 +5 的物料名格并着色为绿。
    """

    def __init__(self, total_rows=200, blocks=(), zero_slots=True):
        self.cells: dict[tuple[int, int], R] = {}
        self.total_rows = total_rows
        for name, start in blocks:
            self.cell(start, 0).value = TITLE
            self.cell(start + 1, 0).value = UNIT_ROW
            self.cell(start + 4, 3).value = "数量"
            self.cell(start + 4, 6).value = "数量"
            self.cell(start + 7, 5).value = LABEL
            if zero_slots:
                for slot in range(start + 5, start + 17):
                    self.cell(slot, 3).value = 0
                    self.cell(slot, 6).value = 0
            if name is not None:
                self.cell(start + 5, 0).value = name
                self.cell(start + 5, 0).color = (0, 255, 0)

    # ---------- 网格基础设施 ----------

    def cell(self, r, c) -> R:
        return self.cells.setdefault((r, c), R())

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
        class _Api:
            UsedRange = object()

        return _Api()

    def __getitem__(self, key):
        # 与真实 xlwings 一致：返回**持久**对象（`sht[i,j].value = v` 编译成「取下标 + 改属性」）
        return self.cells.setdefault(key, R())

    def range(self, *_a, **_kw):
        return R()


def load_editor(mod, sheet):
    editor = mod.xledit.__new__(mod.xledit)   # 绕过 __init__ 的 Excel 启动
    editor.wb = types.SimpleNamespace(sheets=[sheet] * 10, save=lambda: None)
    return editor


class Cw16SlotTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_shang()

    # ---------- 判定函数 ----------

    def test_is_blank_cell_matches_template_semantics(self):
        """模板用 0 表示「还没用」，插行出来的空单元格是 None —— 两者都必须算可写。"""
        for blank in (None, "", "   ", 0, 0.0):
            self.assertTrue(self.mod.is_blank_cell(blank), f"{blank!r} 应算空槽位")
        for used in (5, "5", 1.0, -3, "abc"):
            self.assertFalse(self.mod.is_blank_cell(used), f"{used!r} 应算已占用")

    def test_find_free_row_picks_first_blank_slot(self):
        """实测几何：块首 0 ⇒ 首个空槽行是 0+5（模板预置 D/G = 0）。"""
        sheet = GridSheet(total_rows=200, blocks=[(None, 0), (None, BLOCK_STRIDE)])
        self.assertEqual(
            self.mod.find_free_row(sheet, range(5, 20), quantity_cols=(3, 6)), 5,
        )

    def test_find_free_row_accepts_none_cells(self):
        """关键回归：被插行复制出来的行是 None（改前 `None == 0` 为假 ⇒ 被跳过）。"""
        sheet = GridSheet(total_rows=40, blocks=[(None, 0)], zero_slots=False)
        self.assertIsNone(sheet.cells.get((5, 3)))
        self.assertEqual(
            self.mod.find_free_row(sheet, range(5, 19), quantity_cols=(3, 6)), 5,
            "空单元格（None）必须被当作可用槽位（改前会跳过它）",
        )

    def test_find_free_row_skips_used_slots(self):
        sheet = GridSheet(total_rows=40, blocks=[(None, 0)])
        sheet.cell(5, 3).value = 7          # 第一行已记账
        self.assertEqual(self.mod.find_free_row(sheet, range(5, 19), quantity_cols=(3, 6)), 6)

    def test_find_free_row_returns_none_when_block_full(self):
        sheet = GridSheet(total_rows=40, blocks=[(None, 0)])
        for slot in range(5, 19):
            sheet.cell(slot, 3).value = 1
            sheet.cell(slot, 6).value = 1
        self.assertIsNone(
            self.mod.find_free_row(sheet, range(5, 19), quantity_cols=(3, 6)),
            "写满时必须返回 None 让调用方报错，而不是给一个越界/末行的行号",
        )

    def test_find_free_row_rejects_slots_too_close_to_table_end(self):
        """写数据还会用到 i+1/i+2，越出表尾的槽位一律不可用。"""
        sheet = GridSheet(total_rows=10, blocks=[(None, 0)])
        self.assertIsNone(self.mod.find_free_row(sheet, [9], quantity_cols=(3, 6)))
        self.assertEqual(self.mod.find_free_row(sheet, [7], quantity_cols=(3, 6)), 7)

    # ---------- 端到端：写数据 ----------

    def test_add_direction_writes_into_first_slot(self):
        sheet = GridSheet(total_rows=200, blocks=[("原料A", 0)])
        editor = load_editor(self.mod, sheet)
        editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 12, "3.5", True, False)
        self.assertEqual(sheet.cell(7, 3).value, 12, "采购数量必须写进第一个空槽（块首+7）")
        self.assertEqual(sheet.cell(7, 4).value, 3.5, "单价必须写进同一行")
        self.assertEqual(sheet.cell(7, 6).value, 0, "出库列不得被本次入库改动")

    def test_minus_direction_writes_out_quantity(self):
        sheet = GridSheet(total_rows=200, blocks=[("原料A", 0)])
        editor = load_editor(self.mod, sheet)
        editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 4, "0", False, True)
        self.assertEqual(sheet.cell(7, 6).value, 4, "出库数量必须写进第一个空槽")
        self.assertEqual(sheet.cell(7, 3).value, 0, "采购列应保持模板预置的 0")

    def test_second_entry_goes_to_next_slot(self):
        sheet = GridSheet(total_rows=200, blocks=[("原料A", 0)])
        editor = load_editor(self.mod, sheet)
        editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 12, "3.5", True, False)
        editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 8, "4.0", True, False)
        self.assertEqual(sheet.cell(7, 3).value, 12)
        self.assertEqual(sheet.cell(8, 3).value, 8, "第二次入库必须落到下一个空槽")

    def test_direction_must_be_specified(self):
        sheet = GridSheet(total_rows=200, blocks=[("原料A", 0)])
        editor = load_editor(self.mod, sheet)
        with self.assertRaises(ValueError):
            editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 1, "1", False, False)

    # ---------- 端到端：没有空槽时必须报错，不得覆写最后一行 ----------

    def test_block_full_raises_instead_of_silently_dropping(self):
        """块内槽位写满 → 改前会一路走到表尾 break（静默丢弃），改后必须报错。"""
        sheet = GridSheet(total_rows=200, blocks=[("原料A", 0)])
        for slot in range(5, 21):          # 5..20 覆盖该块全部可用槽位行
            sheet.cell(slot, 3).value = 1
            sheet.cell(slot, 6).value = 1
        editor = load_editor(self.mod, sheet)

        with self.assertRaises(ValueError) as ctx:
            editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 5, "2", True, False)
        self.assertIn("槽位已写满", str(ctx.exception))

    def test_overflow_row_lands_on_last_excel_row(self):
        """改前：定位循环走到底 → `i -= 1` 落在 Excel 最后一行 → 覆写标题行 + `A{i+1}:L{i+1}` 合并。

        用「一个写满的块 + 表尾正好落在块内」的最小场景固定住「会覆写最后一行」这个事实。
        """
        sheet = GridSheet(total_rows=20, blocks=[("原料A", 0)])
        for slot in range(5, 20):
            sheet.cell(slot, 3).value = 1
            sheet.cell(slot, 6).value = 1
        last_row_before = sheet.cell(19, 0).value
        editor = load_editor(self.mod, sheet)

        with self.assertRaises(ValueError) as ctx:
            editor.add_book_item(self.mod.things.RAWMETRIAL, "原料A", 5, "2", True, False)
        self.assertIn("槽位已写满", str(ctx.exception))
        self.assertEqual(
            sheet.cell(19, 0).value, last_row_before,
            f"最后一行（Excel 第 20 行）不得被改写成 {TITLE!r}",
        )

    def test_no_slot_anywhere_raises_and_never_touches_last_row(self):
        """改前：定位循环走到底 → `i -= 1` 覆写最后一行并 A:L 合并（原数据不可恢复）。"""
        sheet = GridSheet(total_rows=30, blocks=[], zero_slots=False)
        # 没有任何块首/绿色槽位：定位循环会一路走到表尾
        editor = load_editor(self.mod, sheet)

        with self.assertRaises(ValueError) as ctx:
            editor.add_book_item(self.mod.things.RAWMETRIAL, "新物料", 1, "1", True, False)

        msg = str(ctx.exception)
        self.assertIn("空槽位", msg, f"必须是可读的业务异常，实际 {msg!r}")
        self.assertEqual(
            sheet.cells.get((29, 0), R()).value, None,
            "绝不能写 Excel 最后一行（改前会把它覆写成报表标题并合并 A30:L30）",
        )

    def test_green_slot_matching_still_works(self):
        """回归：绿色空槽位（模板预置的可用槽位）仍能被定位到。"""
        sheet = GridSheet(total_rows=200, blocks=[(None, 0)])
        sheet.cell(4, 0).color = (0, 255, 0)     # 块首 +4 的绿色空槽行（值为 None）
        editor = load_editor(self.mod, sheet)
        editor.add_book_item(self.mod.things.RAWMETRIAL, "原料Z", 3, "1.5", True, False)
        self.assertEqual(sheet.cell(4, 0).value, "原料Z", "绿色空槽应被写上物料名")
        self.assertEqual(sheet.cell(6, 3).value, 3, "数量必须写进该块的第一个空槽（块首 + 6）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
