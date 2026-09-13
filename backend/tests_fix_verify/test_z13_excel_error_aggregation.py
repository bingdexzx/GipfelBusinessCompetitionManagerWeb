# -*- coding: utf-8 -*-
"""Z-13 验证：表格校验必须一次列出全部错误，而不是遇到第一个就中断。

缺陷（改前）：`build_from_tables` 在 `spec.handler` 抛错时立刻 `raise` —— 十几行的表要
「改一处 → 跑一次 → 再报下一处」，来回十几轮；`--inspect` 宣传的「改完表都跑一遍，10 秒」
在这种表上完全不成立。

改后：逐行收集全部错误（最多列出 20 条并提示剩余条数），最后一次性抛出 `SheetBuildError`；
有错时仍不产出归档、退出码仍为 1。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z13_excel_error_aggregation -v 2
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import SheetBuildError, build_from_tables  # noqa: E402
from sheet_spec import SheetFormatError  # noqa: E402


class TempCsvDir:
    """把 {表名: 行} 写成 CSV 目录（工具支持目录形式的表格源）。"""

    def __init__(self, root: Path, tables: dict[str, list[list[str]]]):
        self.root = root
        self.tables = tables

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for name, rows in self.tables.items():
            lines = [",".join(f'"{c}"' if "," in c else c for c in row) for row in rows]
            (self.root / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.root

    def __exit__(self, *exc):
        return False


class ErrorAggregationTests(SimpleTestCase):
    def _build(self, td, tables):
        with TempCsvDir(td, tables) as src:
            return build_from_tables(src, fallback_name="Z13赛")

    def test_all_row_errors_are_reported_at_once(self):
        import shutil
        import uuid

        tmp = Path(__file__).resolve().parent / ".tmp_z13" / f"z13_{uuid.uuid4().hex[:8]}"
        try:
            tables = {
                "比赛": [["比赛名称", "状态"], ["Z13赛", "ACTIVE"]],
                # 三行都缺必填的「区域名称」，第四行正常
                "区域": [["区域名称", "说明"], ["", "缺名称1"], ["", "缺名称2"], ["", "缺名称3"], ["乙区", "正常"]],
            }
            with self.assertRaises((SheetFormatError, SheetBuildError)) as cm:
                self._build(tmp, tables)
            msg = str(cm.exception)
            self.assertIn("3 处错误", msg, f"应一次报出全部 3 处：{msg}")
            for no in ("第 2 行", "第 3 行", "第 4 行"):
                self.assertIn(no, msg, f"应包含 {no}：{msg}")

            # 改前只报第一条（用同一份数据验证行为差异由测试的「3 处」断言承担）
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

    def test_valid_table_still_builds(self):
        import shutil
        import uuid

        tmp = Path(__file__).resolve().parent / ".tmp_z13" / f"z13_{uuid.uuid4().hex[:8]}"
        try:
            builder, stats, _notes = self._build(
                tmp, {"比赛": [["比赛名称", "状态"], ["Z13赛", "ACTIVE"]],
                      "区域": [["区域名称", "说明"], ["甲区", "正常"]]}
            )
            self.assertEqual(stats.get("区域"), 2 - 1, "有效表仍应正常建包")
            self.assertIsNotNone(builder.build())
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)
