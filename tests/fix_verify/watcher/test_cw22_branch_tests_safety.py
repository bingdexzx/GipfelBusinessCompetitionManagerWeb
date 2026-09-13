# -*- coding: utf-8 -*-
"""CW-22 验证：`run_branch_tests.py` 的「运行后哈希」必须真算，且不得误杀用户自己的 Excel。

缺陷（改前）：
1. `main()` 里 `src_sha = sha(SRC)` 在循环**之前**算好，循环结束后却打印
   `原文件 SHA256（运行后）: {src_sha}` —— 脚本从未验证 `target.xlsx` 未被用例改动。
   `test_output/TEST_REPORT_v2.md:8` 声称的「运行前后哈希一致」并非由脚本保障（那次靠人工算）。
2. `reap(new)` 对「用例期间新出现的**所有** EXCEL.EXE」执行 `taskkill /F`，会连用户自己打开、
   正在编辑的 Excel 一起强杀（未保存数据丢失）；而 `SOAK_REPORT.md:24` 又证明外部 taskkill
   与该环境下的 COM 崩溃高度相关，误杀会反过来污染后续用例结论。
3. `excel_pids()` 用固定共享临时文件 `dsh_tasklist_out.txt`，并发跑两个用例会互相覆盖。

改后：
1. 循环结束后重新计算哈希并显式比对，不一致则 `sys.exit(1)`；
2. 只强杀「`xledit` 记录到的、由本脚本启动的」PID（`plan_reap` 纯函数可断言），
   其余新出现的 Excel 仅告警不回收；
3. `excel_pids()` 用 `tempfile.mkstemp` 唯一化临时文件。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw22_branch_tests_safety.py
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw08_cw09_bookkeeping import install_fake_xlwings  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "contract_watcher" / "bookkeeping_example" / "run_branch_tests.py"


def load_script_module():
    """按路径加载 run_branch_tests.py（顶层会 import shang，故先注入假 xlwings）。"""
    install_fake_xlwings()
    import importlib.util

    spec = importlib.util.spec_from_file_location("rbt_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rbt_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class Cw22HashTests(unittest.TestCase):
    def test_post_run_hash_is_recomputed(self):
        """源码层面：必须在循环之后重新计算哈希并比对（改前只在循环前算一次）。"""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            "src_sha_after = sha(SRC)", src,
            "运行后哈希必须重新计算（改前打印的『运行后』其实是运行前算的）",
        )
        self.assertRegex(
            src, r"if\s+src_sha_after\s*!=\s*src_sha",
            "必须显式比对两次哈希",
        )
        # 「运行后」那行必须打印重新计算的值，而不是循环前的
        after_line = next(
            ln for ln in src.splitlines() if "原文件 SHA256（运行后）" in ln
        )
        self.assertIn("src_sha_after", after_line)

    def test_mismatch_exits_nonzero(self):
        """哈希不一致时必须非零退出，便于 CI / 任务计划发现。"""
        src = SCRIPT.read_text(encoding="utf-8")
        # 取「哈希对比」之后的 6 行，确认里面有 sys.exit(非零)
        idx = src.index("if src_sha_after != src_sha")
        tail = src[idx: idx + 400]
        self.assertRegex(tail, r"sys\.exit\([1-9]")


class Cw22ReapPlanTests(unittest.TestCase):
    """`plan_reap` 的纯函数语义（真正的杀进程决策）。"""

    def setUp(self):
        self.mod = load_script_module()

    def test_users_excel_is_never_planned_for_kill(self):
        """用户自己的 Excel（用例前就存在）绝不能被回收。"""
        plan = self.mod.plan_reap(present={100, 200}, owned={200}, before={100})
        self.assertEqual(plan["kill"], [200], "只应回收本脚本启动的 PID")
        self.assertEqual(plan["foreign"], [], "用例前已存在的进程不该被当成外来新进程")

    def test_new_foreign_excel_is_only_warned(self):
        """用例期间新出现但不是本脚本启动的 Excel：只告警，不杀（改前会 taskkill）。"""
        plan = self.mod.plan_reap(present={100, 300}, owned={100}, before=set())
        self.assertEqual(plan["kill"], [100])
        self.assertEqual(plan["foreign"], [300], "外来的新 Excel 必须列入告警而不是回收")

    def test_owned_pid_registered_by_xledit(self):
        """`xledit` 启动 Excel 后会登记 PID，供脚本按「自己启动的」精确回收。"""
        mod = self.mod
        mod.xledit.owned_pids.clear()
        editor = mod.xledit.__new__(mod.xledit)
        editor.xlapp = type("App", (), {"impl": type("Impl", (), {"pid": 4242})()})()
        editor._remember_pid()
        self.assertIn(4242, mod.xledit.owned_pids)

    def test_reap_only_kills_owned(self):
        """端到端（不真杀进程）：把 tasklist 输出替换掉，核对 taskkill 的目标集合。"""
        mod = self.mod
        mod.xledit.owned_pids.clear()
        mod.xledit.owned_pids.add(111)

        csv = (
            '"映像名称","PID","会话名","会话#","内存使用"\n'
            '"EXCEL.EXE","111","Console","1","100,000 K"\n'
            '"EXCEL.EXE","222","Console","1","100,000 K"\n'
        )

        def fake_system(cmd: str) -> int:
            if cmd.startswith("tasklist"):
                target = cmd.split(">")[1].strip().strip('"')
                Path(target).write_text(csv, encoding="gbk")
                return 0
            commands.append(cmd)
            return 0

        commands: list[str] = []
        real_system = mod.os.system
        mod.os.system = fake_system
        try:
            mod.reap({111, 222})
        finally:
            mod.os.system = real_system

        killed = [c for c in commands if c.startswith("taskkill")]
        self.assertEqual(len(killed), 1, f"只应杀 1 个进程，实际 {killed}")
        self.assertIn("/PID 111", killed[0], "必须杀掉本脚本启动的 111")
        self.assertNotIn(
            "/PID 222", " ".join(killed),
            "用户/外来的 222 绝不能被杀（改前 taskkill 会把用例期间新出现的 Excel 全杀）",
        )

    def test_excel_pids_uses_unique_temp_file(self):
        """并发跑两个用例不得互相覆盖解析结果（改前用固定名 dsh_tasklist_out.txt）。"""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("dsh_tasklist_out.txt", src, "不得再用固定共享临时文件名")
        self.assertIn("tempfile.mkstemp", src)


class Cw22SyntaxTests(unittest.TestCase):
    def test_script_compiles(self):
        ast.parse(SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
