# -*- coding: utf-8 -*-
"""CW-08 / CW-09 验证：记账样例的 Decimal 精度与 Excel 进程回收。

CW-08（金额量级错误）：`shang.py` 在模块级执行 `getcontext().prec = 2`，把**进程级** Decimal
精度改成 2 位有效数字。README 教程要求 handler `from shang import xledit`，import 即生效：
  Decimal('1234.56') + Decimal('0.44') → 1.2E+3（1200）
  Decimal('12345.67') * 3              → 3.7E+4（37000，正确 37037.01）
  Decimal('999999.99') / 3             → 3.3E+5
CW-09（Excel 进程泄漏）：`xledit.__init__` 先 `xw.App()` 再 `books.open()`，open 抛错时没有
`quit()` → 每次失败泄漏一个隐藏 EXCEL.EXE，并继续占用该 xlsx，watcher 又吞掉异常 ⇒ 静默漏账。

xlwings 未安装（记账样例只在真实环境跑），故这里注入一个假 xlwings 模块后按路径加载真实 shang.py。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw08_cw09_bookkeeping.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from decimal import Decimal, getcontext, localcontext
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SHANG_PY = REPO / "contract_watcher" / "bookkeeping_example" / "shang.py"
DEFAULT_PREC = 28


class FakeRange:
    def __init__(self, value=None):
        self.value = value
        self.formula = None

    @property
    def options(self):
        return self


class FakeSheet:
    def __getitem__(self, key):
        return FakeRange()


class FakeBook:
    def __init__(self, fail=False):
        self.sheets = [FakeSheet() for _ in range(10)]
        self.fail = fail
        self.saved = False
        self.closed = False

    def save(self):
        self.saved = True

    def close(self):
        self.closed = True


class FakeBooks:
    def __init__(self, app, fail=False):
        self.app = app
        self.fail = fail

    def open(self, path):
        if self.fail:
            raise RuntimeError("模拟 books.open 失败（文件被 Excel 占用 / 只读）")
        self.app.last_book = FakeBook()
        return self.app.last_book


class FakeApp:
    """假 Excel 应用：记录 quit 调用次数与启动次数。"""

    instances: list["FakeApp"] = []
    fail_open = False

    def __init__(self, visible=False, add_book=False):
        self.visible = visible
        self.quit_count = 0
        self.last_book = None
        self.books = FakeBooks(self, fail=type(self).fail_open)
        self.api = types.SimpleNamespace(ScreenUpdating=None, DisplayAlerts=None)
        FakeApp.instances.append(self)

    def quit(self):
        self.quit_count += 1


def install_fake_xlwings(fail_open=False) -> types.ModuleType:
    FakeApp.instances = []
    FakeApp.fail_open = fail_open
    mod = types.ModuleType("xlwings")
    mod.App = FakeApp
    mod.Book = FakeBook
    sys.modules["xlwings"] = mod
    return mod


def load_shang(fail_open=False):
    install_fake_xlwings(fail_open=fail_open)
    spec = importlib.util.spec_from_file_location("shang_under_test", SHANG_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cw08DecimalTests(unittest.TestCase):
    def setUp(self):
        # 每个用例从默认精度开始，避免相互影响
        getcontext().prec = DEFAULT_PREC

    def test_import_does_not_change_global_decimal_precision(self):
        load_shang()
        self.assertEqual(
            getcontext().prec, DEFAULT_PREC,
            f"import shang 不得改动进程级 Decimal 精度（改后应为 {DEFAULT_PREC}，实际 {getcontext().prec}）",
        )

    def test_amount_arithmetic_is_exact_after_import(self):
        load_shang()
        with localcontext() as ctx:
            ctx.prec = getcontext().prec
            self.assertEqual(Decimal("1234.56") + Decimal("0.44"), Decimal("1235.00"))
            self.assertEqual(Decimal("12345.67") * 3, Decimal("37037.01"))
            self.assertEqual(Decimal("999999.99") / 3, Decimal("333333.33"))

    def test_precision_override_would_be_visible(self):
        """反向取证：把精度改成 2 后这些运算就会失真（说明本缺陷确实是量级错误）。"""
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertNotEqual(Decimal("12345.67") * 3, Decimal("37037.01"))
            self.assertEqual(str(Decimal("12345.67") * 3), "3.7E+4")


class Cw09ExcelLifecycleTests(unittest.TestCase):
    def setUp(self):
        getcontext().prec = DEFAULT_PREC

    def test_open_failure_quits_excel(self):
        """books.open 失败：必须回收 Excel 进程（改前泄漏隐藏 EXCEL.EXE）。"""
        mod = load_shang(fail_open=True)
        xlsx = REPO / "contract_watcher" / "bookkeeping_example" / "target.xlsx"
        with self.assertRaises(RuntimeError):
            mod.xledit(str(xlsx))
        self.assertEqual(len(FakeApp.instances), 1, "应尝试启动过 Excel")
        self.assertEqual(
            FakeApp.instances[0].quit_count, 1,
            "打开失败时必须 quit() 回收进程（改前 quit_count=0，进程泄漏）",
        )

    def test_success_path_does_not_quit_early(self):
        """回归：正常打开时不得提前 quit（否则后续记账无 Excel 可用）。"""
        mod = load_shang()
        xlsx = REPO / "contract_watcher" / "bookkeeping_example" / "target.xlsx"
        editor = mod.xledit(str(xlsx))
        self.assertEqual(FakeApp.instances[0].quit_count, 0)
        self.assertIsNotNone(editor.wb)
        editor.save()
        self.assertEqual(FakeApp.instances[0].quit_count, 1, "save() 仍应保存→关闭→退出")

    def test_missing_file_raises_without_starting_excel(self):
        """回归：文件不存在时不启动 Excel（原行为）。"""
        mod = load_shang()
        with self.assertRaises(Exception):
            mod.xledit(str(REPO / "contract_watcher" / "bookkeeping_example" / "no-such.xlsx"))
        self.assertEqual(FakeApp.instances, [], "文件不存在时不应启动 Excel")


if __name__ == "__main__":
    unittest.main(verbosity=2)
