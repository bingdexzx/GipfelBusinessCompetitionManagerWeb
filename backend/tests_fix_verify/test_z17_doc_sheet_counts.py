# -*- coding: utf-8 -*-
"""Z-17 验证：建包文档的表数量口径与 `--sheets` 统计口径必须与实际一致。

缺陷（改前）：
1. **表数量文档内部矛盾**：`docs/比赛Excel建包规范.md` 一处写「最小示例.xlsx（最小框架，17 张表）」、
   另一处写「最小示例.xlsx | 教程用的最小框架（16 张表）」；同一文件在不同段落给出 16/17 两个数；
   `汽车产业链示例.xlsx` 写「20 张表」，实测 21 张（20 张业务表 + 1 张「说明」表）；
   `docs/比赛Excel建包教程.md` 同样写「16 张表 / 20 张表」。
   实测：`SHEETS` = 21 张业务表；最大示例 21 张、最小示例 17 张、空白模板 22 张（各含 1 张「说明」表）。
2. **`--sheets` 统计口径**：`build_from_tables` 的 `stats` 只统计**选中且存在于表格里**的表，
   总结行「共处理 N 张表」会被读成「表格里的表都处理了」；被过滤掉的表没有任何说明。

改后：
1. 文档统一按「N 张工作表 = M 张业务表 + 1 张「说明」表」的口径写，三份示例的实测数量一致；
2. `build_from_tables` 记录被 `--sheets` 过滤掉（但确实在表格里）的表，并在提示里列出。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z17_doc_sheet_counts
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
EXAMPLES_DIR = BACKEND / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from sheet_spec import SHEETS  # noqa: E402

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SPEC_DOC = REPO / "docs" / "比赛Excel建包规范.md"
TUTORIAL_DOC = REPO / "docs" / "比赛Excel建包教程.md"

EXAMPLES = {
    "汽车产业链示例.xlsx": (21, 20),
    "最小示例.xlsx": (17, 16),
    "比赛建包模板.xlsx": (22, 21),
}


def _sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("xl/workbook.xml"))
        return [node.get("name") for node in root.iter(NS_MAIN + "sheet")]


class Z17WorkbookCountsTests(SimpleTestCase):
    def test_spec_sheets_count_is_21(self):
        self.assertEqual(len(SHEETS), 21, "规范本体应覆盖 21 张业务表")

    def test_example_workbooks_match_documented_counts(self):
        """三份示例工作簿的实际工作表数（= 业务表 + 说明）必须与文档声明一致。"""
        for filename, (total, business) in EXAMPLES.items():
            path = EXAMPLES_DIR / filename
            self.assertTrue(path.is_file(), f"{filename} 不存在")
            names = _sheet_names(path)
            self.assertEqual(len(names), total, f"{filename} 实际 {len(names)} 张：{names}")
            self.assertIn("说明", names, f"{filename} 应含「说明」表")
            self.assertEqual(
                len([n for n in names if n != "说明"]), business,
                f"{filename} 业务表数量应为 {business}，实际 {names}",
            )
            self.assertEqual(len(set(names)), len(names), f"{filename} 有重名工作表：{names}")


class Z17DocConsistencyTests(SimpleTestCase):
    """文档里不得再出现互相矛盾的表数量。"""

    def _count_claims(self, text: str, filename: str) -> list[tuple[int, int]]:
        """返回 [(声明的张数, 行号)]，只取「<文件名>…N 张表」这种断言。"""
        out = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if filename not in line:
                continue
            for m in re.finditer(r"(\d+)\s*张(?:工作表|表)", line):
                out.append((int(m.group(1)), lineno))
        return out

    def test_spec_doc_counts_are_consistent(self):
        text = SPEC_DOC.read_text(encoding="utf-8")
        for filename, (total, _b) in EXAMPLES.items():
            claims = self._count_claims(text, filename)
            self.assertTrue(claims, f"{SPEC_DOC.name} 里应至少提及一次 {filename}")
            numbers = {n for n, _line in claims}
            self.assertEqual(
                numbers, {total},
                f"{SPEC_DOC.name} 里 {filename} 的张数声明应统一为 {total}，实际 {claims}",
            )

    def test_tutorial_doc_counts_are_consistent(self):
        text = TUTORIAL_DOC.read_text(encoding="utf-8")
        for filename, (total, _b) in EXAMPLES.items():
            claims = self._count_claims(text, filename)
            if not claims:
                continue          # 教程未提该文件不算矛盾
            numbers = {n for n, _line in claims}
            self.assertEqual(
                numbers, {total},
                f"{TUTORIAL_DOC.name} 里 {filename} 的张数声明应统一为 {total}，实际 {claims}",
            )

    def test_spec_doc_business_table_claim(self):
        """规范第 1 节声明的业务表数量必须等于 `len(SHEETS)`。"""
        text = SPEC_DOC.read_text(encoding="utf-8")
        m = re.search(r"本规范覆盖[，,]\s*(\d+)\s*张表", text)
        self.assertIsNotNone(m, "规范应有一句「本规范覆盖，N 张表」")
        self.assertEqual(int(m.group(1)), len(SHEETS))


class Z17SheetsFilterNoticeTests(SimpleTestCase):
    def test_skipped_sheets_are_reported(self):
        """`--sheets` 过滤掉的表必须出现在提示里（改前只有一句笼统的统计）。"""
        from build_from_sheets import build_from_tables

        source = EXAMPLES_DIR / "最小示例.xlsx"
        builder, stats, notes = build_from_tables(
            source, only_sheets="区域", fallback_name="Z17 过滤用例"
        )
        self.assertIn("区域", stats, f"选中的表应被处理，实际 {stats}")
        self.assertNotIn("产业类型", stats, "未选中的表不应进入 stats")
        self.assertTrue(
            any("--sheets" in n and "未参与产出" in n for n in notes),
            f"必须提示被过滤掉的表，实际 {notes}",
        )
        self.assertTrue(
            any("产业类型" in n for n in notes),
            f"提示里应列出被过滤的表名，实际 {notes}",
        )
        # 归档里确实没有未选中表的资源
        archive = builder.build()
        self.assertNotIn("industryTypes", archive["resources"])

    def test_no_filter_no_skip_notice(self):
        """回归：不加 --sheets 时不得出现「未参与产出」提示。"""
        from build_from_sheets import build_from_tables

        source = EXAMPLES_DIR / "最小示例.xlsx"
        _builder, _stats, notes = build_from_tables(source, fallback_name="Z17 全量用例")
        self.assertFalse(
            any("未参与产出" in n for n in notes),
            f"未使用 --sheets 时不应有该提示，实际 {notes}",
        )
