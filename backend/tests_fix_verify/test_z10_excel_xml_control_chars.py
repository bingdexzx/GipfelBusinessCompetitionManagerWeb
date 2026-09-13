# -*- coding: utf-8 -*-
"""Z-10 验证：写出的 xlsx 不得含 XML 非法控制字符。

缺陷（改前）：`_xml_escape` 的注释写着「XML 1.0 不允许的控制字符（Excel 会直接报文件损坏）」，
但代码只删了 `\\x00`。任何带 `\\x01`–`\\x08` / `\\x0b` / `\\x0c` / `\\x0e`–`\\x1f` 的文本
（从别的系统粘贴、CSV 里带 `\\x0b` 的字段…）都会被原样写进 XML：
  - 本工具再读该文件 → `xml.etree.ElementTree.ParseError: not well-formed`；
  - Excel / WPS 打开 → 报「文件已损坏」；
  - `make_template.py --from-sheets A.xlsx --out B.xlsx` 这类「转一手」会把原本能读的文件变成打不开。

改后：写入前剔除全部 XML 1.0 非法控制字符（保留 Tab/LF/CR）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z10_excel_xml_control_chars -v 2
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

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z10"

# XML 1.0 非法控制字符（\x09 \x0a \x0d 合法，不在此列）
ILLEGAL = ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1f"]


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z10_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


class XmlControlCharTests(SimpleTestCase):
    def test_control_chars_are_stripped_on_write(self):
        with TempDir() as td:
            target = td / "带控制字符.xlsx"
            rows = [["名称", "说明"], ["行1\x0b行2\x01", "含\x0c换页\x1f与控制\x08符"]]
            write_xlsx(str(target), {"区域": rows})

            # 1) 本工具自己必须能读回（改前 ParseError: not well-formed）
            tables = read_xlsx(target)
            self.assertIn("区域", tables)
            self.assertEqual(tables["区域"][1][0], "行1行2", "非法控制字符应被剔除")
            self.assertEqual(tables["区域"][1][1], "含换页与控制符")

            # 2) 原始 XML 里不得残留裸控制字符
            import zipfile

            with zipfile.ZipFile(target) as zf:
                sheet_name = next(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet"))
                xml = zf.read(sheet_name).decode("utf-8")
            for ch in ILLEGAL:
                self.assertNotIn(ch, xml, f"XML 里不得出现控制字符 {ch!r}")

    def test_tab_newline_carriage_return_are_allowed(self):
        """回归：XML 允许的 \\t \\n \\r 必须保留（多行说明是正常输入）。"""
        with TempDir() as td:
            target = td / "多行.xlsx"
            write_xlsx(str(target), {"区域": [["名称"], ["行1\n行2\t制表\r回车"]]})
            tables = read_xlsx(target)
        self.assertIn("\n", tables["区域"][1][0])
        self.assertIn("\t", tables["区域"][1][0])

    def test_normal_text_and_escaping_unchanged(self):
        with TempDir() as td:
            target = td / "转义.xlsx"
            write_xlsx(str(target), {"区域": [["名称"], ['A&B <C> "D"']]})
            tables = read_xlsx(target)
        self.assertEqual(tables["区域"][1][0], 'A&B <C> "D"')
