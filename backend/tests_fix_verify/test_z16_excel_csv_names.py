# -*- coding: utf-8 -*-
"""Z-16 验证：CSV 目录导出前必须校验表名（表名就是文件名）。

缺陷（改前）：`write_csv_dir` 直接 `(path / f"{name}.csv").open("w")`：
  - 表名里带 `/` `\\` `:` `*` `?` `"` `<` `>` `|` 或控制字符时，Windows/macOS 上会失败；
  - 更糟的是**写到一半才抛**：排在前面的表已经落地，目录里留下内容参差的半成品，
    而用户看到部分文件存在，容易以为导出成功。

改后：`write_csv_dir` 先整体校验所有表名，任何一个不合法就在写盘之前报错（目录里不产生文件）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z16_excel_csv_names -v 2
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

from xlsx_io import read_csv_dir, write_csv_dir  # noqa: E402

try:  # 改前不存在该校验
    from xlsx_io import validate_csv_file_names  # noqa: E402
except ImportError:  # pragma: no cover - 仅在“改前”状态下走到
    validate_csv_file_names = None

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z16"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z16_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


class CsvFileNameTests(SimpleTestCase):
    def test_partial_write_is_prevented(self):
        """坏表名排在好表名之后：必须先整体校验，目录里不得留下半成品。"""
        with TempDir() as td:
            target = td / "导出目录"
            tables = {"区域": [["区域名称"], ["Z16区"]], "地图/连线": [["起点"], ["A"]]}
            with self.assertRaises(Exception):
                write_csv_dir(target, tables)

            left = sorted(p.name for p in target.glob("*.csv")) if target.exists() else []
            self.assertEqual(
                left, [],
                f"校验失败时不得留下任何半成品 CSV（改前会先写出「区域.csv」再抛错；实际 {left}）",
            )

    def test_illegal_characters_rejected(self):
        if validate_csv_file_names is None:
            self.fail("改后应提供 validate_csv_file_names（审计 Z-16）")
        for bad in ["a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b"]:
            with self.assertRaises(ValueError, msg=bad):
                validate_csv_file_names({bad: [["x"]]})

    def test_normal_names_still_work(self):
        with TempDir() as td:
            target = td / "导出目录"
            tables = {"比赛": [["比赛名称"], ["Z16赛"]], "区域": [["区域名称"], ["Z16区"]]}
            write_csv_dir(target, tables)
            read_back = read_csv_dir(target)
            self.assertEqual(sorted(read_back), ["区域", "比赛"])
            self.assertEqual(read_back["区域"][1][0], "Z16区")
