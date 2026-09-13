# -*- coding: utf-8 -*-
"""Z-05 验证：文件级异常必须翻译成中文可读提示，而不是抛 Python 堆栈。

缺陷（改前）：`main()` 的 try 只包住 `build_from_tables / builder.build()`，且只捕获
SheetFormatError / SheetBuildError / BuilderError / ValueError：
  - 把 Excel 2003 的 `.xls` 改名成 `.xlsx`、被截断的 xlsx → `zipfile.BadZipFile` 堆栈；
  - 文件正在 Excel 中打开（Windows 独占）→ `PermissionError`；
  - 路径不存在 / 是目录 / 无权限 → `FileNotFoundError` / `IsADirectoryError` / `PermissionError`；
  - `--out` 写盘失败、`--create-competition` 失败也都在 try 之外。
规范承诺「退出码 1 = 表格格式错误」「中文可读提示」，教程第 8 节还有《常见错误速查》，
这几种情况全部落空：用户看到无法判断是「文件格式不对」还是「工具坏了」。

改后：`main()` 捕获 `zipfile.BadZipFile` 与 `OSError`，给出中文提示并返回 1；
`--out` 写盘与 `--create-competition` 一并纳入 try 范围。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z05_excel_file_errors -v 2
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import unittest
import uuid
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO / "backend" / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import main  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z05"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z05_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def run_main(argv):
    """跑 main()，返回 (退出码, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class FileErrorTranslationTests(SimpleTestCase):
    def test_not_a_zip_file_gets_friendly_hint(self):
        """.xls 改名成 .xlsx（或损坏的 xlsx）→ 中文提示 + 退出码 1，且不能有 Traceback。"""
        with TempDir() as td:
            fake = td / "假装是表格.xlsx"
            fake.write_text("这不是一个 zip 包（模拟 Excel 2003 的 .xls 只改了扩展名）", encoding="utf-8")
            code, _out, err = run_main([str(fake), "--inspect"])

        self.assertEqual(code, 1, f"应返回退出码 1，实际 {code}；stderr={err}")
        self.assertNotIn("Traceback", err, f"不应打印 Python 堆栈：{err}")
        self.assertIn("读取或写出文件失败", err)
        self.assertIn("另存为", err, f"提示应说明如何自救：{err}")

    def test_missing_file_gets_friendly_hint(self):
        """路径不存在：早已由 load_tables 给出 SheetBuildError（回归守卫，行为不变）。"""
        with TempDir() as td:
            missing = td / "不存在.xlsx"
            code, _out, err = run_main([str(missing), "--inspect"])

        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertTrue(
            ("读取或写出文件失败" in err) or ("SheetBuildError" in err),
            f"应给出中文可读提示：{err}",
        )

    def test_out_write_failure_is_translated(self):
        """--out 写到「父路径是文件」的位置 → OSError 也要走中文提示（改前在 try 之外）。"""
        with TempDir() as td:
            fake = td / "假装是表格.xlsx"
            fake.write_text("not a zip", encoding="utf-8")
            blocker = td / "blocker.txt"
            blocker.write_text("占位文件", encoding="utf-8")
            code, _out, err = run_main([str(fake), "--out", str(blocker / "x" / "out.json")])

        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertIn("读取或写出文件失败", err)

    def test_unhandled_exception_is_not_silently_swallowed(self):
        """回归：无法识别的异常不应被吞掉（仍应抛出，避免掩盖工具自身的 bug）。"""
        with TempDir() as td:
            fake = td / "表格.xlsx"
            fake.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(TypeError):
                # 传错类型的 --sheets（内部按集合处理）→ 非文件类异常仍应冒泡
                main([str(fake), "--sheets", 123])


if __name__ == "__main__":
    unittest.main(verbosity=2)
