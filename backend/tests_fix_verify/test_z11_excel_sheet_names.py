# -*- coding: utf-8 -*-
"""Z-11 验证：写 xlsx 前必须校验工作表名（长度/非法字符/重名）。

缺陷（改前）：`write_xlsx` 不校验工作表名：
  - 超过 Excel 的 31 字符上限、或含 `[ ] : * ? / \\`、或以单引号开头结尾的名字，会写出
    Excel/WPS 打开时提示「发现不可读取的内容」并自动改名（或直接报损坏）的文件；
  - **重名**最隐蔽：`tables` 是 dict，重名在调用方构造 dict 时就已经互相覆盖 → 一张表被
    静默丢掉，用户拿到的 xlsx 少了整张表而毫无提示。

改后：`write_xlsx` 先调用 `validate_sheet_names`，非法名字直接报错（不再产出坏文件）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z11_excel_sheet_names -v 2
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO / "backend" / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from xlsx_io import read_xlsx, write_xlsx  # noqa: E402

try:  # 改前不存在该校验函数（工作表名完全不校验）
    from xlsx_io import validate_sheet_names  # noqa: E402
except ImportError:  # pragma: no cover - 仅在“改前”状态下走到
    validate_sheet_names = None

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z11"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z11_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


class SheetNameTests(SimpleTestCase):
    def _require(self):
        self.assertIsNotNone(validate_sheet_names, "改后应提供 validate_sheet_names（审计 Z-11）")

    def test_overlong_name_is_rejected(self):
        self._require()
        long_name = "长" * 32
        with self.assertRaises(ValueError) as cm:
            validate_sheet_names({long_name: [["x"]]})
        self.assertIn("31", str(cm.exception))

    def test_illegal_characters_are_rejected(self):
        self._require()
        for bad in ["区域[1]", "a:b", "a*b", "a?b", "a/b", "a\\b", "'开头", "结尾'"]:
            with self.assertRaises(ValueError, msg=bad):
                validate_sheet_names({bad: [["x"]]})

    def test_empty_name_is_rejected(self):
        self._require()
        with self.assertRaises(ValueError):
            validate_sheet_names({"   ": [["x"]]})

    def test_normal_names_pass_and_roundtrip(self):
        with TempDir() as td:
            target = td / "正常.xlsx"
            tables = {"比赛": [["比赛名称"], ["Z11赛"]], "区域": [["区域名称"], ["Z11区"]]}
            validate_sheet_names(tables)
            write_xlsx(str(target), tables)
            read_back = read_xlsx(target)
            self.assertEqual(sorted(read_back), ["区域", "比赛"])
            self.assertEqual(read_back["区域"][1][0], "Z11区")

    def test_write_xlsx_rejects_bad_names(self):
        with TempDir() as td:
            target = td / "坏名字.xlsx"
            with self.assertRaises(ValueError):
                write_xlsx(str(target), {"a:b": [["x"]]})
            self.assertFalse(target.exists(), "校验失败时不得留下半成品文件")

    def test_max_length_name_is_allowed(self):
        self._require()
        name = "长" * 31
        validate_sheet_names({name: [["x"]]})
