# -*- coding: utf-8 -*-
"""Z-06 验证：`--create-competition` 复用同名比赛后必须能继续导入（append 模式）。

缺陷（改前）：第二次跑同一条命令（文档与教程都写成「同名比赛会复用、一条命令可反复执行」）时：
`_create_competition` 复用已有比赛 → `apply_import(..., allow_non_empty=False)` → 占用检查命中
（比赛里已有区域/燃料/基建等）→ `ArchiveError` → 退出码 2「目标比赛已有业务数据…默认拒绝导入」。
即「复用」是事实，但复用后立刻失败。

改后：复用已有比赛且模式为 **append**（默认，纯增量、不改动既有数据）时自动允许继续导入并打印
提示；**overwrite**（覆盖，破坏性）仍要求显式 `--allow-non-empty`，不静默放开。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z06_excel_create_competition_reuse -v 2
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import uuid
from pathlib import Path

from django.test import TestCase

from apps.competitions.models import Competition
from apps.regions.models import Region

REPO = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO / "backend" / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from build_from_sheets import main  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z06"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z06_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def write_tables(path: Path, comp_name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "比赛.csv").write_text(f"比赛名称,状态\n{comp_name},ACTIVE\n", encoding="utf-8")
    (path / "区域.csv").write_text("区域名称,说明\nZ06区,最小示例\n", encoding="utf-8")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class CreateCompetitionReuseTests(TestCase):
    def test_second_run_in_append_mode_succeeds(self):
        name = f"Z06-复用赛-{uuid.uuid4().hex[:6]}"
        with TempDir() as td:
            src = td / "tables"
            write_tables(src, name)

            code1, out1, err1 = run_main([str(src), "--create-competition"])
            code2, out2, err2 = run_main([str(src), "--create-competition"])

        self.assertEqual(code1, 0, f"首跑应成功：stdout={out1} stderr={err1}")
        self.assertEqual(
            code2, 0,
            f"第二次跑同一条命令应成功（改前退出码 2：占用保护拒绝导入）；stdout={out2} stderr={err2}",
        )
        self.assertIn("复用已有比赛", out2)
        self.assertIn("自动允许", out2, f"应说明为何放行：{out2}")

        comp = Competition.objects.get(name=name)
        self.assertEqual(
            Region.objects.filter(competition=comp, name="Z06区").count(), 1,
            "append 模式不得重复建区域（只补缺）",
        )

    def test_append_reuse_does_not_duplicate_or_modify(self):
        """回归：复用 + append 不改动既有数据（自检：改一次库里的说明，再跑不应被覆盖）。"""
        name = f"Z06-保留赛-{uuid.uuid4().hex[:6]}"
        with TempDir() as td:
            src = td / "tables"
            write_tables(src, name)
            run_main([str(src), "--create-competition"])

            comp = Competition.objects.get(name=name)
            region = Region.objects.get(competition=comp, name="Z06区")
            Region.objects.filter(pk=region.pk).update(description="人工改过的说明")

            run_main([str(src), "--create-competition"])
            region.refresh_from_db()

        self.assertEqual(region.description, "人工改过的说明", "append 模式不得覆盖既有记录")

    def test_overwrite_reuse_still_requires_explicit_flag(self):
        """overwrite 是破坏性模式：复用非空比赛时必须仍被拦住（不静默放开）。"""
        name = f"Z06-覆盖赛-{uuid.uuid4().hex[:6]}"
        with TempDir() as td:
            src = td / "tables"
            write_tables(src, name)
            run_main([str(src), "--create-competition"])

            code, out, err = run_main([str(src), "--create-competition", "--mode", "overwrite"])

        self.assertEqual(code, 2, f"overwrite 复用非空比赛应被拒绝；stdout={out} stderr={err}")
        self.assertIn("allow-non-empty", err, f"应提示显式开关：{err}")

    def test_overwrite_reuse_with_flag_succeeds(self):
        name = f"Z06-覆盖赛2-{uuid.uuid4().hex[:6]}"
        with TempDir() as td:
            src = td / "tables"
            write_tables(src, name)
            run_main([str(src), "--create-competition"])
            code, out, err = run_main(
                [str(src), "--create-competition", "--mode", "overwrite", "--allow-non-empty"]
            )

        self.assertEqual(code, 0, f"显式允许后应成功：stdout={out} stderr={err}")
