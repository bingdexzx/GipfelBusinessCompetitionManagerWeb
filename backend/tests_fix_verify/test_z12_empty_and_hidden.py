# -*- coding: utf-8 -*-
"""Z-12 余项验证：空表段、隐藏工作表、隐藏行。

缺陷（改前）：
1. **空表被整表吞掉**：表格里放一张「稍后再填」的空表（只有表头）时，`CompetitionBuilder.build()`
   对空资源 `continue`，归档里**根本没有该段**；`--inspect` 只列非空资源，用户看不出
   「我放了表却没产出」。
2. **隐藏工作表**：`xlsx_io._sheet_files` 只读 `name`/`r:id`，不看 `state="hidden"` ——
   藏在隐藏表里的旧数据照常被建进比赛，而用户在界面上看不到这些数据。
3. **隐藏行/列**：`read_xlsx` 不看 `row/@hidden`、`col/@hidden` —— 被隐藏的草稿行也会进库。

改后：
- `xlsx_io.inspect_workbook(path)` 只读体检：报告隐藏工作表、含隐藏行的工作表；
  `_sheet_entries` 读出 `state`（**不改变读取行为** —— 隐藏表仍要读，否则会静默丢数据）；
- `build_from_tables` 对「只有表头」的工作表给出明确提示（归档里没有该段）；
- `--inspect` 的产出概览单独列出这些空表。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z12_empty_and_hidden
"""
from __future__ import annotations

import io
import shutil
import sys
import uuid
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import _print_summary  # noqa: E402
from xlsx_io import read_xlsx  # noqa: E402

try:  # 改前不存在这些入口（本文件要能在「改前」状态下跑出有意义的失败）
    from build_from_sheets import _empty_sheet_names  # noqa: E402
except ImportError:  # pragma: no cover - 仅“改前”走到
    _empty_sheet_names = None
try:
    from xlsx_io import _sheet_entries, inspect_workbook  # noqa: E402
except ImportError:  # pragma: no cover - 仅“改前”走到
    _sheet_entries = None
    inspect_workbook = None

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# 沙箱下系统 temp 目录不可写，临时文件统一放仓库内的 .tmp/
_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


class TmpDir:
    """仓库内临时目录（与 watcher 用例同一原因：系统 temp 在沙箱下不可写）。"""

    def __enter__(self) -> Path:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = _TMP_ROOT / f"z12_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def write_workbook(path: Path, sheets, rows_xml) -> None:
    """写一个最小 xlsx。

    `sheets` = [(表名, 工作表 id, 是否隐藏)]；`rows_xml` = {表名: "<row>…"}。
    """
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/{sid}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for _n, sid, _h in sheets
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{NS_PKG_REL}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{overrides}"
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{NS_PKG_REL}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    sheet_nodes = ""
    for i, (name, sid, hidden) in enumerate(sheets):
        state = ' state="hidden"' if hidden else ""
        sheet_nodes += f'<sheet name="{name}" sheetId="{i + 1}"{state} r:id="{sid}"/>'
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}"><sheets>{sheet_nodes}</sheets></workbook>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{NS_PKG_REL}">'
        + "".join(
            f'<Relationship Id="{sid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/{sid}.xml"/>'
            for _n, sid, _h in sheets
        )
        + "</Relationships>"
    )

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        for name, sid, _h in sheets:
            zf.writestr(
                f"xl/worksheets/{sid}.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<worksheet xmlns="{NS_MAIN}"><sheetData>{rows_xml.get(name, "")}</sheetData></worksheet>',
            )


def _inline(ref: str, text: str, *, hidden: bool = False) -> str:
    row = ref[1:]
    attr = ' hidden="1"' if hidden else ""
    return f'<row r="{row}"{attr}><c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c></row>'


class Z12EmptySheetTests(SimpleTestCase):
    def test_empty_sheet_stats_zero(self):
        """只有表头的工作表：行数为 0（stats 里可见「表在但 0 行」）。"""
        self.assertIsNotNone(
            _empty_sheet_names,
            "改前没有 `_empty_sheet_names`：空表既不产出段也没有任何提示",
        )
        self.assertEqual(_empty_sheet_names({"区域": 0, "公司": 3}), ["区域"])
        self.assertEqual(_empty_sheet_names({"公司": 3}), [])

    def test_summary_lists_empty_sheets(self):
        """`--inspect` 概览必须单独列出空表（改前只列非空资源，用户看不出漏了什么）。"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_summary({"resources": {}}, empty_sheets=["区域", "燃料"])
        out = buf.getvalue()
        self.assertIn("区域", out)
        self.assertIn("燃料", out)
        self.assertIn("没有", out, f"必须说明归档里没有该段：{out!r}")

    def test_summary_without_empty_sheets_unchanged(self):
        """回归：没有空表时概览行为不变。"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_summary({"resources": {}})
        self.assertNotIn("没有任何数据行", buf.getvalue())

    def test_build_from_tables_warns_about_empty_sheet(self):
        """端到端：`build_from_tables` 必须提示空表（改前既无该段、也无任何提示）。"""
        from build_from_sheets import build_from_tables

        with TmpDir() as td:
            path = td / "wb.xlsx"
            write_workbook(
                path,
                sheets=[("比赛", "sheet1", False), ("区域", "sheet2", False)],
                rows_xml={
                    "比赛": _inline("A1", "比赛名称"),
                    "区域": _inline("A1", "区域名称"),      # 只有表头
                },
            )
            _builder, stats, notes = build_from_tables(path, fallback_name="空表用例")
            self.assertEqual(stats.get("区域"), 0, f"区域表应为 0 行，实际 {stats}")
            self.assertTrue(
                any("区域" in n and "没有该段" in n for n in notes),
                f"必须提示「空表不会产出对应资源」，实际 {notes}",
            )
            archive = _builder.build()
            self.assertNotIn(
                "regions", archive["resources"],
                "本工具的既定语义是「空资源不产出段」——提示必须让用户知道这一点",
            )


class Z12HiddenSheetTests(SimpleTestCase):
    def test_hidden_sheet_is_reported(self):
        self.assertIsNotNone(
            inspect_workbook,
            "改前没有 `inspect_workbook`：隐藏工作表不会被报告",
        )
        with TmpDir() as td:
            path = td / "wb.xlsx"
            write_workbook(
                path,
                sheets=[("区域", "sheet1", False), ("旧数据", "sheet2", True)],
                rows_xml={
                    "区域": _inline("A1", "区域名称"),
                    "旧数据": _inline("A1", "废弃"),
                },
            )
            info = inspect_workbook(path)
            self.assertIn("旧数据", info["hidden_sheets"])
            self.assertNotIn("区域", info["hidden_sheets"])
            # 隐藏表**照常被读取**（不改变读取行为，否则会静默丢数据）
            tables = read_xlsx(path)
            self.assertIn("旧数据", tables)
            self.assertEqual(tables["旧数据"][0][0], "废弃")

    def test_hidden_rows_are_reported(self):
        self.assertIsNotNone(inspect_workbook, "改前没有 `inspect_workbook`")
        with TmpDir() as td:
            path = td / "wb.xlsx"
            write_workbook(
                path,
                sheets=[("区域", "sheet1", False)],
                rows_xml={
                    "区域": (
                        _inline("A1", "区域名称")
                        + _inline("A2", "草稿区", hidden=True)
                        + _inline("A3", "甲区")
                    )
                },
            )
            info = inspect_workbook(path)
            self.assertIn("区域", info["sheets_with_hidden_rows"])
            entry = next(s for s in info["sheets"] if s["name"] == "区域")
            self.assertEqual(entry["rows"], 3)
            self.assertEqual(entry["hidden_rows"], 1)
            # 隐藏行也照常被读出来
            tables = read_xlsx(path)
            self.assertEqual([r[0] for r in tables["区域"]], ["区域名称", "草稿区", "甲区"])

    def test_visible_workbook_reports_nothing(self):
        self.assertIsNotNone(inspect_workbook, "改前没有 `inspect_workbook`")
        with TmpDir() as td:
            path = td / "wb.xlsx"
            write_workbook(
                path,
                sheets=[("区域", "sheet1", False)],
                rows_xml={"区域": _inline("A1", "区域名称")},
            )
            info = inspect_workbook(path)
            self.assertEqual(info["hidden_sheets"], [])
            self.assertEqual(info["sheets_with_hidden_rows"], [])

    def test_missing_file_is_tolerated(self):
        """体检失败/文件不存在不得抛异常（调用方按「无提示」处理）。"""
        self.assertIsNotNone(inspect_workbook, "改前没有 `inspect_workbook`")
        info = inspect_workbook(Path("no-such-file.xlsx"))
        self.assertEqual(info["sheets"], [])
        self.assertEqual(info["hidden_sheets"], [])

    def test_sheet_entries_reads_state(self):
        """`_sheet_entries` 必须读出 `state`（hidden 之后仍能按顺序拿到路径）。"""
        self.assertIsNotNone(_sheet_entries, "改前没有 `_sheet_entries`")
        with TmpDir() as td:
            path = td / "wb.xlsx"
            write_workbook(
                path,
                sheets=[("A", "sheet1", False), ("B", "sheet2", True)],
                rows_xml={},
            )
            with zipfile.ZipFile(path) as zf:
                entries = _sheet_entries(zf)
            self.assertEqual([(n, h) for n, _t, h in entries], [("A", False), ("B", True)])
            self.assertEqual([t for _n, t, _h in entries],
                             ["xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"])

    def test_read_xlsx_unchanged_by_refactor(self):
        """回归：`_sheet_files` 改成基于 `_sheet_entries` 后，读取结果不变。"""
        self.assertIsNotNone(_sheet_entries, "改前没有 `_sheet_entries`")
        with TmpDir() as td:
            path = td / "wb.xlsx"
            write_workbook(
                path,
                sheets=[("区域", "sheet1", False), ("燃料", "sheet2", False)],
                rows_xml={"区域": _inline("A1", "区域名称"), "燃料": _inline("A1", "燃料名称")},
            )
            tables = read_xlsx(path)
            self.assertEqual(list(tables), ["区域", "燃料"])
            self.assertEqual(tables["燃料"][0][0], "燃料名称")
