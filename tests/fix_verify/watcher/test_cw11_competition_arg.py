# -*- coding: utf-8 -*-
"""CW-11 验证：`--competition` 的 0/负数不得被静默当成「不筛选」。

缺陷（改前）：`args.competition` 直接透传到下游，而下游写的是 `if competition_id:` ——
传 `--competition 0`（脚本里变量没取到值的典型形态）时该判断为假，筛选条件被**静默丢弃**：
监听程序会把**所有比赛**的已执行合同都拉回来并按当前比赛的账套记账（跨比赛混记），
日志里看不出任何异常。`fetch_executed_ids` 里同样的 `if competition_id:` 也是这个坑。

改后：启动时校验 `--competition`，非正整数直接报错退出（退出码 2）；
`fetch_executed_ids` 改用 `is not None` 判断，0 不再被当成「不筛选」。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw11_competition_arg.py
"""
from __future__ import annotations

import io
import sys
import unittest
import warnings
from contextlib import redirect_stderr
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import FakeBackend, StopLoop, TempDir, load_watcher  # noqa: E402


def run_main(mod, argv_extra):
    mod.Backend = lambda server, username, password: FakeBackend([(1, "2026-01-01T00:00:00Z")])
    mod.ensure_handlers_file = lambda: None
    mod.load_handlers = lambda: {}
    mod.sync_catalog = lambda *a, **k: False

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= 2:
            raise StopLoop()

    mod.time.sleep = fake_sleep
    old_argv = sys.argv
    sys.argv = [
        "contract_watcher.py", "--server", "http://fake", "--username", "u",
        "--password", "p", "--interval", "0.001", "--port", "0",
        "--out-dir", str(mod.WATCHER_DIR / "out"),
    ] + list(argv_extra)
    err = io.StringIO()
    try:
        with redirect_stderr(err):
            return mod.main(), err.getvalue()
    except StopLoop:
        return None, err.getvalue()      # 改前：没有校验，直接跑进主循环
    finally:
        sys.argv = old_argv


class CompetitionArgTests(unittest.TestCase):
    def test_zero_competition_is_rejected(self):
        with TempDir() as td:
            mod = load_watcher(td)
            code, stderr = run_main(mod, ["--competition", "0"])
        self.assertEqual(
            code, 2,
            f"--competition 0 必须被拒绝并给出退出码 2（改前会一路跑进主循环，跨比赛混记）；"
            f"stderr={stderr!r}",
        )
        self.assertIn("正整数", stderr, f"应给出中文提示：{stderr!r}")

    def test_negative_competition_is_rejected(self):
        with TempDir() as td:
            mod = load_watcher(td)
            code, stderr = run_main(mod, ["--competition", "-3"])
        self.assertEqual(code, 2, stderr)

    def test_fetch_executed_ids_keeps_zero_filter(self):
        """0 不再被当成「不筛选」：必须把 competitionId=0 带进查询串。"""
        with TempDir() as td:
            mod = load_watcher(td)
            backend = mod.Backend("http://fake", "u", "p")
            backend.token = "t"
            seen: list[str] = []

            def fake_api(path):
                seen.append(path)
                return {"items": [], "total": 0}

            backend.api = fake_api
            backend.fetch_executed_ids(0)
            self.assertTrue(seen, "应发起一次查询")
            self.assertIn(
                "competitionId=0", seen[0],
                f"competitionId=0 必须出现在查询串里（改前会被静默丢掉）：{seen[0]}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
