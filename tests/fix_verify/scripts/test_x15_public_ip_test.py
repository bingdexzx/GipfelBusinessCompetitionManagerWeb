"""X-15 回归：tests/deploy_public_ip_test.sh 必须与调用 cwd 无关。

改前现象（真实执行，非静态推演）：
    $ cd tests && bash deploy_public_ip_test.sh
    sed: can't read scripts/deploy-linux.sh: No such file or directory
    normalize_ip: command not found
    结果：PASS=8 FAIL=14      exit=1
    $ cd <仓库根> && bash tests/deploy_public_ip_test.sh
    结果：PASS=22 FAIL=0      exit=0

即：只要 cwd 不是仓库根，14 条断言全部 FAIL 并以 1 退出，看起来像"被测脚本回归"。

本文件做两件事：
  1. 静态断言脚本用 BASH_SOURCE 定位仓库根、有 exit 2 的环境错误分支、且已删除对
     deploy-linux.sh 中**不存在**的交互式 read 分支（READ_VAL/READ_INVALID/READ_TIMEOUT）
     的镜像实现；
  2. 若本机找得到可执行的 bash，则在"错误 cwd"下真实执行该脚本并断言 exit 0 且无 FAIL；
     找不到 bash 时 skip（不伪装成通过）。

运行：backend/.venv/Scripts/python.exe tests/fix_verify/scripts/test_x15_public_ip_test.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TEST_SH = REPO / "tests" / "deploy_public_ip_test.sh"


def _find_bash() -> str | None:
    """找可执行的 bash：PATH 里的往往是未安装 WSL 的 WindowsApps 存根，需跳过。"""
    candidates: list[str] = []
    for name in ("bash", "bash.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for guess in (
        r"D:\Git\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        "/bin/bash",
        "/usr/bin/bash",
    ):
        candidates.append(guess)
    for cand in candidates:
        try:
            p = Path(cand)
            if not p.is_file():
                continue
            # WindowsApps 下的 bash.exe 是 WSL 存根，执行会 E_ACCESSDENIED
            if "WindowsApps" in str(p):
                continue
            proc = subprocess.run(
                [str(p), "-c", "echo ok"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if proc.returncode == 0 and "ok" in proc.stdout:
                return str(p)
        except Exception:  # noqa: BLE001 - 环境探测，任何异常都视为不可用
            continue
    return None


class X15ScriptSourceTests(unittest.TestCase):
    """静态契约：脚本必须自定位、区分环境错误、不再镜像已删除分支。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = TEST_SH.read_text(encoding="utf-8", errors="replace")
        # 注释里会引用"改前的坏写法"作为说明，负向断言只能针对真正的代码行
        cls.code = "\n".join(
            ln for ln in cls.src.splitlines() if not ln.lstrip().startswith("#")
        )

    def test_repo_root_from_bash_source(self):
        self.assertIn('SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"', self.code)
        self.assertIn('REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"', self.code)
        self.assertNotIn('SCRIPT="$PWD/', self.code, "不得再用 $PWD 定位被测脚本")

    def test_environment_error_uses_exit_code_2(self):
        m = re.search(r'if \[\[ ! -f "\$SCRIPT" \]\]; then(.*?)fi', self.code, re.S)
        self.assertIsNotNone(m, "缺少被测脚本存在性前置断言")
        self.assertIn("exit 2", m.group(1), "环境错误必须用退出码 2，区别于用例失败的 1")

    def test_no_mirror_of_removed_read_branch(self):
        # resolve() 里复刻 TTY/read 的镜像实现必须已被删除（注释与断言文本不算）
        self.assertNotIn("local TTY=", self.code, "仍在镜像已删除的 TTY 分支")
        self.assertNotIn('echo "READ_INVALID"', self.code, "仍在镜像已删除的 READ_INVALID 分支")
        self.assertNotIn('echo "READ_TIMEOUT"', self.code, "仍在镜像已删除的 READ_TIMEOUT 分支")

    def test_production_script_really_has_no_read_branch(self):
        """镜像分支之所以要删，是因为生产脚本里确实没有交互式 read。"""
        prod = (REPO / "scripts" / "deploy-linux.sh").read_text(encoding="utf-8", errors="replace")
        self.assertIn("exec 0</dev/null", prod)
        for token in ("READ_VAL", "READ_INVALID", "READ_TIMEOUT"):
            self.assertNotIn(token, prod, f"生产脚本出现了 {token}，本测试的前提已失效")

    def test_uses_production_port_helper(self):
        self.assertIn('LIB="$REPO_ROOT/scripts/lib/deploy-common.sh"', self.code)
        self.assertIn('source "$LIB"', self.code, "端口解析必须用生产实现，不得复刻")


class X15ScriptExecutionTests(unittest.TestCase):
    """真实执行：从错误的 cwd 运行也必须全绿。"""

    def test_runs_green_from_wrong_cwd(self):
        bash = _find_bash()
        if bash is None:
            self.skipTest("本机没有可执行的 bash，跳过真实执行（静态断言已覆盖）")
        for cwd, label in ((REPO / "tests", "tests/ 目录"), (REPO, "仓库根")):
            with self.subTest(cwd=label):
                proc = subprocess.run(
                    [bash, str(TEST_SH)],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                self.assertEqual(proc.returncode, 0, f"cwd={label} 退出码非 0：\n{out}")
                m = re.search(r"PASS=(\d+) FAIL=(\d+)", out)
                self.assertIsNotNone(m, f"没有看到结果行：\n{out}")
                self.assertEqual(m.group(2), "0", f"cwd={label} 存在 FAIL：\n{out}")
                self.assertGreaterEqual(int(m.group(1)), 30, f"cwd={label} 断言数异常少：\n{out}")
                self.assertNotIn("command not found", out, f"cwd={label} 仍出现命令未找到：\n{out}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
