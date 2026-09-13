# -*- coding: utf-8 -*-
"""Z-07 验证：`--out` 不得无提示地覆盖已有归档，且要显示本次归档的规模。

缺陷（改前）：`--out` 无条件 `write_text` 覆盖：
  1. 对同一路径跑两遍（教程把 `--out a.json` 列为常规命令）→ 直接覆盖，无备份；
  2. `--sheets 产业类型,产业字段 --out 框架.json`（规范第 1 节 ⑥ 与教程第 5 节把两者并列介绍）
     → 本次归档**只含这两类资源**，却整体替换上一次的完整归档 → 前端导入得到一场只有行业口径、
     没有区域/地图/物资的比赛，而用户手里没有任何旧副本；
  3. 输出只说「已写出归档」，不显示资源类数与条数，用户无法察觉内容缩水。
改后：目标已存在时默认拒绝（退出码 2）并提示 `--force` 或改用带时间戳的新文件名；
写出后打印「本次归档含 N 类资源、M 条记录」；`--sheets` 与 `--out` 同用时额外告警。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z07_excel_out_backup -v 2
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import uuid
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO / "backend" / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import main  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z07"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z07_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def write_tables(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "比赛.csv").write_text("比赛名称,状态\nZ07赛,ACTIVE\n", encoding="utf-8")
    (path / "区域.csv").write_text("区域名称,说明\nZ07区,最小示例\n", encoding="utf-8")
    (path / "燃料.csv").write_text("燃料名称,每升单价\nZ07柴油,7.5\n", encoding="utf-8")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class OutOverwriteTests(SimpleTestCase):
    def test_existing_out_is_not_overwritten_by_default(self):
        with TempDir() as td:
            src = td / "tables"
            write_tables(src)
            out = td / "归档.json"
            code1, _o1, err1 = run_main([str(src), "--out", str(out)])
            self.assertEqual(code1, 0, err1)
            original = out.read_text(encoding="utf-8")

            # 第二次用只有一张表的子集导出，指向同一路径
            code2, _o2, err2 = run_main(
                [str(src), "--sheets", "产业类型,产业字段", "--out", str(out)]
            )

            self.assertEqual(code2, 2, f"已存在的归档默认不得被覆盖；stderr={err2}")
            self.assertIn("--force", err2, f"应提示如何覆盖：{err2}")
            self.assertEqual(out.read_text(encoding="utf-8"), original, "文件内容必须保持不变")

    def test_force_allows_overwrite(self):
        with TempDir() as td:
            src = td / "tables"
            write_tables(src)
            out = td / "归档.json"
            run_main([str(src), "--out", str(out)])
            code, _o, err = run_main([str(src), "--out", str(out), "--force"])
            self.assertEqual(code, 0, err)
            self.assertTrue(out.exists(), "加了 --force 应允许覆盖写出")

    def test_written_summary_shows_scale(self):
        with TempDir() as td:
            src = td / "tables"
            write_tables(src)
            out = td / "归档.json"
            code, stdout, err = run_main([str(src), "--out", str(out)])
            self.assertEqual(code, 0, err)
            self.assertIn("类资源", stdout, f"应显示本次归档规模：{stdout}")
            self.assertIn("条记录", stdout)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("resources", data)

    def test_sheets_with_out_warns_about_partial_archive(self):
        with TempDir() as td:
            src = td / "tables"
            write_tables(src)
            out = td / "子集.json"
            code, stdout, err = run_main([str(src), "--sheets", "区域", "--out", str(out)])
            self.assertEqual(code, 0, err)
            self.assertIn("--sheets", err, f"子集导出应告警：stderr={err}")
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotIn("fuels", data.get("resources", {}), "子集归档确实只含被选中的表")
