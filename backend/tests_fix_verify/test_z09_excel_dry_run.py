# -*- coding: utf-8 -*-
"""Z-09 验证：`--dry-run` 预演必须一行都不落库（含不新建比赛）。

缺陷（改前）：`main()` 在 `apply_import`（及其回滚）之前就调用 `_create_competition`，
而它是裸的 `Competition.objects.create(...)`、没有任何外层事务 → `--create-competition
--dry-run` 这一标准姿势会真实建出一场**空比赛**；又因比赛名全局唯一，第二次真导时落到
「复用已有比赛」分支并撞上占用保护（Z-06）。规范与教程都写着「预演导入（事务回滚，一行都不落库）」。

改后：`--dry-run` 时不落库、只打印「将新建比赛「X」（状态 …）—— dry-run 不落库」；
比赛尚不存在时也不再去 apply_import 报「目标比赛不存在」，而是直接给出建包预览。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z09_excel_dry_run -v 2
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import uuid
from pathlib import Path

from django.test import TestCase

from apps.competitions.models import Competition

REPO = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO / "backend" / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import main  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z09"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z09_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def write_min_table(path: Path, comp_name: str) -> None:
    """写一份最小 CSV 目录（工具支持目录形式的 CSV 表格源）。"""
    path.mkdir(parents=True, exist_ok=True)
    (path / "比赛.csv").write_text(f"比赛名称,状态\n{comp_name},ACTIVE\n", encoding="utf-8")
    (path / "区域.csv").write_text("区域名称,说明\nZ09区,最小示例\n", encoding="utf-8")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class DryRunTests(TestCase):
    def test_dry_run_does_not_create_competition(self):
        name = f"Z09-预演赛-{uuid.uuid4().hex[:6]}"
        with TempDir() as td:
            src = td / "tables"
            write_min_table(src, name)
            code, out, err = run_main([str(src), "--create-competition", "--dry-run"])

        self.assertFalse(
            Competition.objects.filter(name=name).exists(),
            f"dry-run 不得建出比赛（改前会真实 create）；stdout={out} stderr={err}",
        )
        self.assertIn("dry-run 不落库", out, f"应明确说明未落库：{out}")
        self.assertEqual(code, 0, f"预演应正常结束；stderr={err}")

    def test_dry_run_then_real_import_works(self):
        """预演之后真导必须能建出比赛（改前预演已占名 → 真导落到复用分支并撞占用保护）。"""
        name = f"Z09-真导赛-{uuid.uuid4().hex[:6]}"
        with TempDir() as td:
            src = td / "tables"
            write_min_table(src, name)
            code1, _out1, err1 = run_main([str(src), "--create-competition", "--dry-run"])
            code2, out2, err2 = run_main([str(src), "--create-competition"])

        self.assertEqual(code1, 0, err1)
        self.assertEqual(code2, 0, f"预演后的真导应成功；stdout={out2} stderr={err2}")
        self.assertTrue(Competition.objects.filter(name=name).exists())

    def test_dry_run_with_existing_competition_reuses_and_rolls_back(self):
        """目标比赛已存在时：复用其 id，预演仍不写入业务数据。"""
        name = f"Z09-已有赛-{uuid.uuid4().hex[:6]}"
        comp = Competition.objects.create(name=name)
        from apps.regions.models import Region

        with TempDir() as td:
            src = td / "tables"
            write_min_table(src, name)
            code, out, err = run_main([str(src), "--create-competition", "--dry-run"])

        self.assertEqual(code, 0, f"stdout={out} stderr={err}")
        self.assertIn("复用已有比赛", out)
        self.assertFalse(
            Region.objects.filter(competition=comp, name="Z09区").exists(),
            "dry-run 不得落库区域数据",
        )
