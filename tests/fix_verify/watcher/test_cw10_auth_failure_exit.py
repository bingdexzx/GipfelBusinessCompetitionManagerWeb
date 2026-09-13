# -*- coding: utf-8 -*-
"""CW-10 验证：凭据失效不能无限静默失败。

缺陷（改前）：`main()` 的循环里对 HTTP 401 只写一行 `log.warning("登录态失效，下一轮自动重登")`
就继续下一轮 —— 若账号被禁用/改密/密码变更（重登必然失败），进程**永不退出、不告警、状态不变**：
用户以为监听在正常工作，实际一条合同都不会再被处理，且没有任何外部信号（systemd 看到的仍是
running）。这正是「记账静默停摆」最难被发现的一类。

改后：连续 401 达 `MAX_CONSECUTIVE_AUTH_FAILURES`（5）轮即写 error 日志、向 stderr 打印中文提示
并 `return 1`（非零退出码让守护进程/运维能发现）；非 401 的错误重置计数。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw10_auth_failure_exit.py
"""
from __future__ import annotations

import io
import sys
import unittest
import urllib.error
import warnings
from contextlib import redirect_stderr
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import FakeBackend, LogCapture, StopLoop, TempDir, load_watcher  # noqa: E402


class UnauthorizedBackend(FakeBackend):
    """登录态恒失效：拉列表直接抛 401。"""

    def fetch_executed_ids(self, competition_id=None):
        self.ids_calls += 1
        raise urllib.error.HTTPError("http://fake/api/contracts", 401, "Unauthorized", {}, None)


def run_until_return(mod, backend, max_rounds=12):
    """跑主循环直到它自己 return（或达到 max_rounds 兜底中断）；返回 (退出码, stderr 文本)。"""
    mod.Backend = lambda server, username, password: backend
    mod.ensure_handlers_file = lambda: None
    mod.load_handlers = lambda: {}
    mod.sync_catalog = lambda *a, **k: False

    capture = LogCapture()
    import logging

    logging.getLogger().addHandler(capture)

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= max_rounds:
            raise StopLoop()

    mod.time.sleep = fake_sleep
    old_argv = sys.argv
    sys.argv = [
        "contract_watcher.py", "--server", "http://fake", "--username", "u",
        "--password", "p", "--interval", "0.001", "--port", "0",
        "--out-dir", str(mod.WATCHER_DIR / "out"),
    ]
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            code = mod.main()
    except StopLoop:
        code = None      # 改前：永远不退出，只能靠兜底中断
    finally:
        sys.argv = old_argv
        logging.getLogger().removeHandler(capture)
    return code, err.getvalue(), capture.messages, sleeps["n"]


class AuthFailureExitTests(unittest.TestCase):
    def test_process_exits_with_error_after_consecutive_401(self):
        with TempDir() as td:
            mod = load_watcher(td)
            backend = UnauthorizedBackend([], fail_ids_times=0)
            # 基线阶段就会 401，故基线也拿不到 → 主循环每轮重试基线
            code, stderr, _logs, rounds = run_until_return(mod, backend)

        self.assertEqual(
            code, 1,
            f"连续 401 后必须带非零退出码退出（改前永不退出，实际跑了 {rounds} 轮仍在循环）；"
            f"stderr={stderr!r}",
        )
        self.assertIn("停止监听", stderr, f"应给出中文可读提示：{stderr!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
