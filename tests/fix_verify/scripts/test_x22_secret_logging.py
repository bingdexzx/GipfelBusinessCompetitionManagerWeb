"""X-22 回归：部署脚本不得把管理员初始口令/密钥明文写进 stdout 或 [DIAG] 日志流。

改前实测（真实 Git bash；把 deploy-linux.sh 里"打印初始口令"的两段真实代码抽出来跑决策表，
只把 `-t 1` 换成可注入的 `FAKE_TTY`，其余一字不改）：

    ### X-22 探针（脚本形态：before；片段 A=327-327，B=642-649）
      TTY=0 --print-seed-password=0 -> 输出含明文口令: 是
      TTY=0 --print-seed-password=1 -> 输出含明文口令: 是
      TTY=1 --print-seed-password=0 -> 输出含明文口令: 是
      TTY=1 --print-seed-password=1 -> 输出含明文口令: 是
      守卫语句出现次数: 0（期望 2）
      "[DIAG] … JWT_SECRET/DJANGO_SECRET_KEY/LOGVIEWER_SECRET_KEY/SEED_ADMIN_PASSWORD 已就绪" 枚举行: 1（期望 0）

    即：无论有没有终端、无论传什么参数，`SEED_ADMIN_PASSWORD` 明文都会进 stdout；
    `sudo bash scripts/deploy-linux.sh | tee deploy.log`、CI 捕获、screen/tmux 回滚缓冲、
    堡垒机命令记录都会留存它 —— 在管理员首次登录前拿到日志即可直接接管系统。

改后实测（同一探针）：
    ### X-22 探针（脚本形态：after；片段 A=335-343，B=660-672）
      TTY=0 --print-seed-password=0 -> 输出含明文口令: 否 （给了查看命令）
      TTY=0 --print-seed-password=1 -> 输出含明文口令: 否 （给了查看命令）
      TTY=1 --print-seed-password=0 -> 输出含明文口令: 否 （给了查看命令）
      TTY=1 --print-seed-password=1 -> 输出含明文口令: 是
      守卫语句出现次数: 2（期望 2）；枚举行: 0（期望 0）

运行：backend/.venv/Scripts/python.exe tests/fix_verify/scripts/test_x22_secret_logging.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "scripts" / "deploy-linux.sh"
UPDATE = REPO / "scripts" / "update-from-github.sh"
HARNESS = REPO / "code_audit" / "_x22_harness.sh"
PY = REPO / "backend" / ".venv" / "Scripts" / "python.exe"

GUARD = 'if [[ "$PRINT_SEED_PASSWORD" == "1" && -t 1 ]]; then'


def _find_bash() -> str | None:
    for cand in (r"D:\Git\bin\bash.exe", "/bin/bash", "/usr/bin/bash"):
        p = Path(cand)
        if not p.is_file() or "WindowsApps" in str(p):
            continue
        try:
            proc = subprocess.run(
                [str(p), "-c", "echo ok"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
            if proc.returncode == 0 and "ok" in proc.stdout:
                return str(p)
        except Exception:  # noqa: BLE001
            continue
    found = shutil.which("bash")
    return found if found and "WindowsApps" not in found else None


class X22StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DEPLOY.read_bytes().decode("utf-8")
        cls.code = "\n".join(
            ln for ln in cls.text.splitlines() if not ln.lstrip().startswith("#")
        )

    def test_both_prints_are_guarded(self):
        self.assertEqual(self.code.count(GUARD), 2, "两处打印口令都必须受 TTY+显式开关守卫")

    def test_no_unconditional_password_echo(self):
        """出现口令且以 echo/ok/warn/log 开头的行，必须落在某个 TTY 守卫块内部。

        写 `.env` 的行（带 `>>`）不算"打印"，跳过。
        """
        lines = self.code.splitlines()
        guards = [i for i, ln in enumerate(lines) if GUARD in ln]
        self.assertEqual(len(guards), 2, "找不到两个 TTY 守卫")
        ends = []
        for g in guards:
            end = next(i for i in range(g + 1, len(lines)) if lines[i].strip() == "fi")
            ends.append(end)

        printing = [
            i
            for i, ln in enumerate(lines)
            if ">>" not in ln
            and ("${ADMIN_PW}" in ln or "${_SEED_PW}" in ln)
            and ln.lstrip().startswith(("echo", "ok ", "warn", "log"))
        ]
        self.assertTrue(printing, "没有找到任何打印口令的行 —— 断言本身失效，请检查解析")
        for i in printing:
            inside = any(g < i < e for g, e in zip(guards, ends))
            self.assertTrue(inside, f"第 {i + 1} 行疑似无条件打印口令：{lines[i].strip()}")

    def test_flag_is_documented_and_parsed(self):
        self.assertIn("--print-seed-password) PRINT_SEED_PASSWORD=1; shift ;;", self.code)
        self.assertIn("--print-seed-password", self.text)
        self.assertIn("PRINT_SEED_PASSWORD=0", self.code, "默认必须是关闭")

    def test_non_tty_with_flag_warns_instead_of_printing(self):
        self.assertIn("stdout 不是终端（管道/CI）", self.text)

    def test_diag_no_longer_enumerates_secret_names(self):
        self.assertNotIn(
            "JWT_SECRET/DJANGO_SECRET_KEY/LOGVIEWER_SECRET_KEY/SEED_ADMIN_PASSWORD 已就绪",
            self.code,
        )
        self.assertIn("首次部署所需密钥/口令已全部生成并写入", self.text)

    def test_update_from_github_never_echoes_the_password(self):
        text = UPDATE.read_bytes().decode("utf-8")
        for i, ln in enumerate(text.splitlines(), 1):
            if "${ADMIN_PW}" not in ln or ">>" in ln:
                continue  # 写 .env 的那一行不算"打印"
            self.assertNotRegex(
                ln, r"^\s*(echo|log|warn|ok)\b",
                f"update-from-github.sh 第 {i} 行把口令打了出来：{ln.strip()}",
            )
        self.assertIn("请查看 .env 中的 SEED_ADMIN_PASSWORD", text)

    def test_deploy_script_line_endings_consistent(self):
        raw = DEPLOY.read_bytes()
        crlf = raw.count(b"\r\n")
        self.assertIn(crlf, (0, raw.count(b"\n")), "deploy-linux.sh 行尾混杂")


class X22RuntimeTests(unittest.TestCase):
    def test_decision_table(self):
        if _find_bash() is None:
            self.skipTest("本机没有可执行的 bash，跳过真实执行（静态断言已覆盖）")
        if not HARNESS.is_file():
            self.skipTest("code_audit/_x22_harness.sh 不存在（非交付物，允许缺失）")

        proc = subprocess.run(
            [_find_bash(), str(HARNESS)], cwd=str(REPO), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        self.assertEqual(proc.returncode, 0, out)

        table = {
            (tty, flag): leaked
            for tty, flag, leaked in re.findall(
                r"TTY=(\d) --print-seed-password=(\d) -> 输出含明文口令: (\S+)", out
            )
        }
        self.assertEqual(len(table), 4, f"没有采到四条组合：\n{out}")
        self.assertEqual(table[("0", "0")], "否")
        self.assertEqual(table[("0", "1")], "否", "非终端 + 显式开关仍然泄露了口令")
        self.assertEqual(table[("1", "0")], "否")
        self.assertEqual(table[("1", "1")], "是", "终端 + 显式开关应显示（这是用户主动要求的）")

        self.assertIn("守卫语句", out)
        self.assertIn("出现次数: 2（期望 2）", out)
        self.assertIn("枚举行: 0（期望 0）", out)
        self.assertNotIn("脚本形态：before", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
