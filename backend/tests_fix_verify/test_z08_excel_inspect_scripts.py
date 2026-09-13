# -*- coding: utf-8 -*-
"""Z-08 验证：`--inspect` 纯预览不得执行工作簿里指定的 Python 脚本。

缺陷（改前）：`build_from_tables()` 无条件处理「合同类型」表，而该表的 handler 会用
`importlib` 执行「脚本路径」那一格指向的本地 Python 文件：
  - 规范第 1 节 ③ 与教程第 1 节 ① 都承诺 `--inspect`「只读表格…**不连库、不写任何东西**」，
    教程 5.1 节更把它当作「改完表都跑一遍」的安全检查；
  - 工作簿是可转发文件（策划之间传表很常见）→ 打开者只要跑一次 --inspect，就会执行别人表里
    写的一格路径（`exec_module`，无沙箱无白名单），且同一路径写两行会**执行两次**；
  - 脚本里的 `sys.exit()` 抛 SystemExit，不被 `except Exception` 捕获 → 工具静默退出无提示。

改后：纯预览（`--inspect` 且不 --out/--competition）默认不执行脚本，只提示「将引入脚本 X」；
需要真产出/真导入时才执行（也可显式 `--run-scripts`）；脚本结果按 (路径, mtime) 只执行一次；
脚本抛出的 SystemExit 等 BaseException 一律转成可读错误。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z08_excel_inspect_scripts -v 2
"""
from __future__ import annotations

import contextlib
import io
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
from sheet_spec import SheetContext, SheetFormatError, _contract_types_from_script  # noqa: E402

TMP_ROOT = Path(__file__).resolve().parent / ".tmp_z08"

SIDE_EFFECT_SCRIPT = """
import os
from pathlib import Path

marker = Path(__file__).with_name("脚本已执行.txt")
with open(marker, "a", encoding="utf-8") as fh:
    fh.write("ran\\n")


class _CT:
    key = "z08-demo"

    def payload(self):
        return {
            "key": self.key, "name": "Z08 演示类型", "partyRoles": [], "inputSchema": [],
            "effects": [], "conditions": [], "graph": None, "schemaVersion": 1, "enabled": True,
        }


def build():
    a = _CT()
    b = _CT()
    b.key = "z08-demo-2"
    return [a, b]
"""

EXIT_SCRIPT = """
import sys
sys.exit("脚本主动退出（模拟第三方脚本）")
"""


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"z08_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def write_tables(path: Path, script_name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "比赛.csv").write_text("比赛名称,状态\nZ08赛,ACTIVE\n", encoding="utf-8")
    (path / "合同类型.csv").write_text(
        f"脚本路径,类型标识\n{script_name},\n", encoding="utf-8"
    )


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class InspectDoesNotRunScriptsTests(SimpleTestCase):
    def test_inspect_does_not_execute_script(self):
        with TempDir() as td:
            script = td / "ct_script.py"
            script.write_text(SIDE_EFFECT_SCRIPT, encoding="utf-8")
            src = td / "tables"
            write_tables(src, str(script))

            code, out, err = run_main([str(src), "--inspect"])
            marker = script.with_name("脚本已执行.txt")

            self.assertEqual(code, 0, f"stdout={out} stderr={err}")
            self.assertFalse(
                marker.exists(),
                f"--inspect 不得执行工作簿指定的脚本（改前会执行；stdout={out}）",
            )
            self.assertIn("未执行脚本", out, f"应说明未执行：{out}")

    def test_run_scripts_flag_still_executes(self):
        """显式 --run-scripts 时才执行（用于确实要产出的场景）。"""
        with TempDir() as td:
            script = td / "ct_script.py"
            script.write_text(SIDE_EFFECT_SCRIPT, encoding="utf-8")
            src = td / "tables"
            write_tables(src, str(script))
            code, out, err = run_main([str(src), "--inspect", "--run-scripts"])
            ran = script.with_name("脚本已执行.txt").exists()

            self.assertEqual(code, 0, f"stdout={out} stderr={err}")
            self.assertTrue(ran, "显式 --run-scripts 应执行脚本")

    def test_out_still_executes_script(self):
        """--out（真产出归档）仍执行脚本：否则归档里会缺合同类型。"""
        with TempDir() as td:
            script = td / "ct_script.py"
            script.write_text(SIDE_EFFECT_SCRIPT, encoding="utf-8")
            src = td / "tables"
            write_tables(src, str(script))
            out_file = td / "归档.json"
            code, out, err = run_main([str(src), "--out", str(out_file)])
            ran = script.with_name("脚本已执行.txt").exists()

        self.assertEqual(code, 0, f"stdout={out} stderr={err}")
        self.assertTrue(ran, "--out 场景仍应执行脚本")

    def test_script_is_executed_once_for_repeated_rows(self):
        """同一脚本写两行「合同类型」不得执行两次（改前会重复执行并重复副作用）。"""
        with TempDir() as td:
            script = td / "ct_script.py"
            script.write_text(SIDE_EFFECT_SCRIPT, encoding="utf-8")
            src = td / "tables"
            src.mkdir(parents=True, exist_ok=True)
            (src / "比赛.csv").write_text("比赛名称,状态\nZ08赛,ACTIVE\n", encoding="utf-8")
            (src / "合同类型.csv").write_text(
                f"脚本路径,类型标识\n{script},z08-demo\n{script},z08-demo-2\n",
                encoding="utf-8",
            )
            code, out, err = run_main([str(src), "--inspect", "--run-scripts"])
            runs = len(script.with_name("脚本已执行.txt").read_text(encoding="utf-8").splitlines())

            self.assertEqual(code, 0, f"stdout={out} stderr={err}")
            self.assertEqual(runs, 1, f"同一脚本写两行时只应执行一次，实际 {runs} 次")

    def test_system_exit_is_reported_not_silent(self):
        with TempDir() as td:
            script = td / "ct_exit.py"
            script.write_text(EXIT_SCRIPT, encoding="utf-8")
            ctx = SheetContext(builder=None, run_scripts=True)
            with self.assertRaises(SheetFormatError) as cm:
                _contract_types_from_script(ctx, str(script))
        self.assertIn("SystemExit", str(cm.exception), "SystemExit 必须转成可读错误而非静默退出")
