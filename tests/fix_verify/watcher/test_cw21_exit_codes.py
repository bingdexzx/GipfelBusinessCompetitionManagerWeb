# -*- coding: utf-8 -*-
"""CW-21 验证：自测/浸泡脚本必须用退出码表达成败，不能让失败被当成成功。

缺陷（改前）：
1. `contract_watcher/selftest.py` 只 `print(f"TOTAL PASS={PASS} FAIL={FAIL}")`，**不设退出码** ——
   在 CI、Windows 任务计划、或"脚本跑完了没报错"的人工判断下，断言失败一律表现为成功
   （`test_run_recheck/REPORT.md:8` 的「11/11 通过」也只能靠人读输出）。
2. `bookkeeping_example/soak_test.py` 在不可恢复错误时 `raise SystemExit(0)` —— 退出码 0
   同样是"成功"，浸泡失效点不出现在调用方的判断里。

改后：
1. `selftest.py` 结束前 `sys.exit(1 if FAIL else 0)`（清理临时目录之后再退出）；
2. `soak_test.py` 失败时 `SystemExit(1)`，并保留现场（临时 xlsx 与 jsonl 日志不删）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw21_exit_codes.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PY = REPO / "backend" / ".venv" / "Scripts" / "python.exe"
SELFTEST = REPO / "contract_watcher" / "selftest.py"
SOAK = REPO / "contract_watcher" / "bookkeeping_example" / "soak_test.py"


class Cw21ExitCodeTests(unittest.TestCase):
    def test_selftest_success_exits_zero(self):
        """回归：全绿时退出码必须是 0（不能把成功写成失败）。"""
        proc = subprocess.run(
            [str(PY), str(SELFTEST)], cwd=str(REPO),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertIn("TOTAL PASS=11 FAIL=0", proc.stdout, proc.stdout[-500:])
        self.assertEqual(proc.returncode, 0, f"自测全绿应退出 0，实际 {proc.returncode}")

    def test_selftest_failure_exits_nonzero(self):
        """在临时副本里人为制造一次断言失败：退出码必须非 0。

        改前只打印 TOTAL 不设退出码，所以这里的 returncode 恒为 0。
        """
        src = SELFTEST.read_text(encoding="utf-8")
        anchor = '    print(f"TOTAL PASS={PASS} FAIL={FAIL}")'
        self.assertIn(anchor, src, "未能定位 selftest 的汇总输出（源码结构变了？）")
        # 在汇总之前注入一条必定失败的断言（改的是临时副本，不动仓库文件）
        patched = src.replace(anchor, '    check("【CW-21 注入失败】", 1 == 2)\n' + anchor, 1)
        tmp = SELFTEST.with_name("selftest_cw21_tmp.py")
        tmp.write_text(patched, encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(PY), str(tmp)], cwd=str(REPO),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        finally:
            tmp.unlink(missing_ok=True)
        self.assertIn("FAIL=1", proc.stdout, proc.stdout[-500:])
        self.assertNotEqual(
            proc.returncode, 0,
            "自测失败必须返回非 0 退出码（改前恒为 0，CI/任务计划会把失败当成功）",
        )

    def test_soak_failure_uses_nonzero_exit(self):
        """静态核对：浸泡脚本的不可恢复错误分支必须是 `raise SystemExit(1)`。"""
        src = SOAK.read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"raise\s+SystemExit\(0\)", src),
            "浸泡脚本不得再用 `raise SystemExit(0)` 表示失败（改前的行为）",
        )
        self.assertIn("raise SystemExit(1)", src)

    def test_soak_keeps_evidence_on_failure(self):
        """失败时不得删除现场（临时 xlsx / jsonl 日志）。"""
        src = SOAK.read_text(encoding="utf-8")
        self.assertIn("FAILED", src, "需要显式的失败标志用于退出码与现场保留")
        self.assertNotIn(
            "unlink", src,
            "浸泡脚本不应删除失败现场",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
