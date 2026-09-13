# -*- coding: utf-8 -*-
"""B01 验证：`stop-dev.bat` 的误杀路径必须消失，PID 文件必须带可校验身份。

缺陷（改前）：
- **D-01**：`stop-dev.bat` 的「端口兜底」对任何监听 `8000/5173/8120` 的进程执行
  `taskkill /PID <n> /T /F`，没有任何身份校验 —— Docker Desktop、另一个 Vite、用户的其它服务
  都会被整棵进程树强杀；而 `dev.py` 端口占用时的报错文案还**主动引导**用户去跑它。
- **D-02**：`%TEMP%\\gipfel-dev.pids` 只写 4 个裸 PID（无映像名/创建时间/项目标识），
  非优雅退出（关窗 X / 任务管理器 / taskkill）不会删它；几小时后 PID 被系统回收再执行
  `stop-dev.bat`，就会强杀**无关**进程树。

改后：
- `dev.py` 新增安全的 `stop` 子命令：逐条校验「映像名 ∈ {python(.exe), node(.exe)} +
  创建时间与记录一致 + 项目标识一致」，不符只告警不杀；端口占用只**报告候选**（PID/映像名/命令行），
  绝不代杀；旧格式（裸 PID）一律不杀。
- PID 文件改为 JSON Lines，每条记录带 `pid/role/image/created/root/nonce`。
- `stop-dev.bat` 变成 `dev.py stop` 的薄包装，删掉了两条 taskkill 路径。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe -m unittest tests.fix_verify.scripts.test_b01_stop_safety -v
    或： backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\scripts\\test_b01_stop_safety.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEV_PY = REPO / "scripts" / "dev.py"
STOP_BAT = REPO / "scripts" / "stop-dev.bat"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def load_dev():
    spec = importlib.util.spec_from_file_location("dev_under_test", DEV_PY)
    mod = importlib.util.module_from_spec(spec)
    # 必须先登记进 sys.modules：dev.py 用了 @dataclass，dataclasses 依赖
    # `sys.modules[cls.__module__].__dict__` 解析类型注解。
    sys.modules["dev_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class _TmpPidFile:
    """把 PID_FILE 指到仓库内临时路径（沙箱下系统 temp 不可写）。"""

    def __init__(self, mod):
        import uuid

        self.mod = mod
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"b01_{uuid.uuid4().hex[:8]}.pids"

    def __enter__(self):
        self.original = self.mod.PID_FILE
        self.mod.PID_FILE = self.path
        return self.path

    def __exit__(self, *exc):
        self.mod.PID_FILE = self.original
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


class B01StopSafetyTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_dev()

    # ---------- stop-dev.bat 不得再有危险路径 ----------

    def test_bat_has_no_taskkill_and_no_port_fallback(self):
        """只看**可执行行**（REM 注释可以叙述历史，但不得再出现可执行的 taskkill/netstat）。"""
        lines = STOP_BAT.read_text(encoding="utf-8", errors="replace").splitlines()
        code = [
            ln for ln in lines
            if ln.strip() and not ln.strip().upper().startswith(("REM", "::"))
        ]
        body = "\n".join(code)
        self.assertNotIn("taskkill", body.lower(), f"stop-dev.bat 不得再直接 taskkill：\n{body}")
        self.assertNotIn("netstat", body.lower(), f"stop-dev.bat 不得再按端口找进程：\n{body}")
        self.assertIn("dev.py", body, "stop-dev.bat 必须是 dev.py stop 的薄包装")
        self.assertIn("stop", body)

    def test_devpy_error_hint_points_to_safe_stop(self):
        """端口占用时的报错文案不得再引导用户去跑无差别强杀的脚本。"""
        source = DEV_PY.read_text(encoding="utf-8")
        idx = source.index("Port already in use")
        window = source[idx: idx + 700]
        self.assertIn("dev.py stop", window, f"应引导到安全入口，实际 {window!r}")
        self.assertNotIn("stop-dev.bat, then retry", window, "旧的误导文案必须删除")

    # ---------- PID 记录与身份校验 ----------

    def test_pid_record_contains_identity_fields(self):
        with _TmpPidFile(self.mod) as path:
            self.mod._process_info = lambda pid: {"image": "python.exe", "created": "20260913223000"}
            self.mod._write_pid_file(4242, [])
            raw = path.read_text(encoding="utf-8").strip()
        record = json.loads(raw.splitlines()[0])
        self.assertEqual(record["pid"], 4242)
        self.assertEqual(record["image"], "python.exe")
        self.assertEqual(record["created"], "20260913223000")
        self.assertTrue(record["root"].startswith("gipfel-dev:"))
        self.assertTrue(record["nonce"], "必须带 nonce，便于区分同一次记录")

    def test_identity_match_accepts_own_process(self):
        record = {"pid": 1, "root": self.mod.PROJECT_ID, "created": "T", "image": "python.exe"}
        matched, why = self.mod.pid_record_matches(record, {"image": "python.exe", "created": "T"})
        self.assertTrue(matched, why)

    def test_identity_rejects_recycled_pid(self):
        """PID 被回收（创建时间变了）⇒ 不可信（改前会直接强杀）。"""
        record = {"pid": 1, "root": self.mod.PROJECT_ID, "created": "T1", "image": "python.exe"}
        matched, why = self.mod.pid_record_matches(record, {"image": "python.exe", "created": "T2"})
        self.assertFalse(matched)
        self.assertIn("回收", why)

    def test_identity_rejects_other_image(self):
        """端口/命令行指向的是别的程序（如 docker、chrome）⇒ 不可信。"""
        record = {"pid": 1, "root": self.mod.PROJECT_ID, "created": "T", "image": "python.exe"}
        matched, why = self.mod.pid_record_matches(
            record, {"image": "com.docker.backend", "created": "T"}
        )
        self.assertFalse(matched)
        self.assertIn("映像名", why)

    def test_identity_rejects_foreign_project(self):
        record = {"pid": 1, "root": "gipfel-dev:deadbeef", "created": "T", "image": "python.exe"}
        matched, why = self.mod.pid_record_matches(record, {"image": "python.exe", "created": "T"})
        self.assertFalse(matched)
        self.assertIn("本仓库", why)

    def test_identity_rejects_dead_or_unknown(self):
        record = {"pid": 1, "root": self.mod.PROJECT_ID, "created": "T", "image": "python.exe"}
        matched, why = self.mod.pid_record_matches(record, None)
        self.assertFalse(matched)
        self.assertIn("已退出", why)

    def test_legacy_format_is_read_but_untrusted(self):
        """旧格式（每行裸 PID）必须能读出来，但一律不可信。"""
        with _TmpPidFile(self.mod) as path:
            path.write_text("111\n222\n", encoding="utf-8")
            records = self.mod.read_pid_records()
        self.assertEqual([r["pid"] for r in records], [111, 222])
        self.assertTrue(all(r.get("legacy") for r in records))

    # ---------- stop_command 行为 ----------

    def test_stop_kills_only_verifiable_processes(self):
        killed: list[int] = []
        self.mod._force_kill_tree = lambda pid: killed.append(pid)
        self.mod._port_in_use = lambda host, port, timeout=0.5: False
        self.mod._process_info = lambda pid: {
            1: {"image": "python.exe", "created": "T1"},
            2: {"image": "node.exe", "created": "T2"},
            3: {"image": "com.docker.backend", "created": "T3"},
        }.get(pid)

        with _TmpPidFile(self.mod) as path:
            path.write_text(
                "\n".join(
                    json.dumps(r)
                    for r in (
                        {"pid": 1, "role": "django", "root": self.mod.PROJECT_ID,
                         "created": "T1", "image": "python.exe", "nonce": "a"},
                        {"pid": 2, "role": "vite", "root": self.mod.PROJECT_ID,
                         "created": "T2", "image": "node.exe", "nonce": "b"},
                        # 端口被 Docker 占用（不是本项目）⇒ 绝不能杀
                        {"pid": 3, "role": "?", "root": self.mod.PROJECT_ID,
                         "created": "T3", "image": "com.docker.backend", "nonce": "c"},
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.mod.stop_command()

        self.assertEqual(rc, 0)
        self.assertEqual(sorted(killed), [1, 2], f"只应停止身份可校验的进程，实际 {killed}")
        self.assertNotIn(3, killed, "外来的 Docker 进程绝不能被停")

    def test_stop_never_kills_legacy_records(self):
        killed: list[int] = []
        self.mod._force_kill_tree = lambda pid: killed.append(pid)
        self.mod._port_in_use = lambda host, port, timeout=0.5: False
        with _TmpPidFile(self.mod) as path:
            path.write_text("1234\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.mod.stop_command()
        self.assertEqual(killed, [], "旧格式记录没有身份信息，绝不能杀")
        self.assertIn("不杀", buf.getvalue())

    def test_stop_reports_busy_ports_without_killing(self):
        """端口占用只列候选（含 PID/映像名），绝不代杀。"""
        killed: list[int] = []
        self.mod._force_kill_tree = lambda pid: killed.append(pid)
        self.mod._process_info = lambda pid: {"image": "com.docker.backend", "created": "X"}
        self.mod._port_in_use = lambda host, port, timeout=0.5: port == 8000
        self.mod._listening_pid = lambda port: 999
        self.mod._process_cmdline = lambda pid: r'"C:\Program Files\Docker\com.docker.backend.exe"'
        with _TmpPidFile(self.mod) as path:
            path.write_text("", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.mod.stop_command()
        out = buf.getvalue()
        self.assertEqual(killed, [], "端口兜底必须彻底删除：不得杀任何监听者")
        self.assertIn("8000", out)
        self.assertIn("999", out, f"应列出占用者 PID 供人工确认，实际 {out!r}")

    def test_stop_without_pidfile_is_quiet_success(self):
        with _TmpPidFile(self.mod) as path:
            self.assertFalse(path.exists())
            self.mod._port_in_use = lambda host, port, timeout=0.5: False
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.mod.stop_command()
        self.assertEqual(rc, 0)
        self.assertIn("No PID file", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
