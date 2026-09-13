# -*- coding: utf-8 -*-
"""CW-20 验证：单实例互斥必须覆盖跨机器场景。

缺陷（改前）：互斥只用 `socket.bind(("127.0.0.1", --port))` —— 它**只在当前主机有效**。
`README.md:175-179` 鼓励用 Windows 任务计划 / `crontab @reboot` 自启，"多机部署"是常态；
两台机器（或本机换 `--port` 起的第二个实例）会各自拉取同一批合同、各自记账：
  - 账本路径相同 ⇒ 两个 Excel 实例交错写同一文件，后保存者覆盖前者（丢掉另一实例的分录）；
  - 各用一份副本 ⇒ 会话账本分叉。
而文档「单实例：重复启动会被端口锁拒绝」给出了过强的安全感。

改后：新增 `SharedLock`（`--lock-file`，默认 `data/watcher.lock`）—— 互斥点落在**共享资源**上：
  - 独占创建（`open("x")`，原子）+ 心跳（每轮刷新 mtime）+ 过期接管（心跳超过 90 秒视为
    持有者已停止，避免 kill -9/断电把锁永久占住）；
  - 正常退出/异常退出都释放锁。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw20_shared_lock.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import T1, TempDir, load_watcher  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
WATCHER_PY = REPO / "contract_watcher" / "contract_watcher.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("cw20_mod", WATCHER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cw20SharedLockTests(unittest.TestCase):
    def test_second_acquire_is_rejected(self):
        """同一路径的第二次 acquire 必须失败（改前端口锁跨机器无效）。"""
        mod = load_mod()
        with TempDir() as td:
            lock_a = mod.SharedLock(td / "watcher.lock")
            lock_b = mod.SharedLock(td / "watcher.lock", owner="other-host:1234")
            ok_a, why_a = lock_a.acquire()
            self.assertTrue(ok_a, why_a)
            ok_b, why_b = lock_b.acquire()
            self.assertFalse(
                ok_b,
                "第二个实例必须被共享锁挡住（这是跨机器的唯一互斥点）",
            )
            self.assertIn("另一个监听实例", why_b)
            self.assertIn(
                lock_a.owner, why_b,
                f"告警里必须写明当前持有者，便于多机排查，实际 {why_b!r}",
            )
            self.assertIn("心跳", why_b)
            lock_a.release()

    def test_release_allows_takeover(self):
        """正常退出后必须能立刻被接管（不能把锁永久占住）。"""
        mod = load_mod()
        with TempDir() as td:
            path = td / "watcher.lock"
            lock_a = mod.SharedLock(path)
            self.assertTrue(lock_a.acquire()[0])
            lock_a.release()
            self.assertFalse(path.exists(), "release 应删除锁文件")
            lock_b = mod.SharedLock(path)
            self.assertTrue(lock_b.acquire()[0], "释放后新的实例必须能启动")
            lock_b.release()

    def test_stale_lock_is_taken_over_with_warning(self):
        """心跳过期（进程被 kill -9 / 断电）⇒ 接管并明确告警，避免死锁。"""
        mod = load_mod()
        with TempDir() as td:
            path = td / "watcher.lock"
            path.write_text("dead-host:999", encoding="utf-8")
            old = time.time() - (mod.LOCK_STALE_SECONDS + 30)
            os.utime(path, (old, old))

            lock = mod.SharedLock(path)
            ok, why = lock.acquire()
            self.assertTrue(ok, "心跳过期的锁必须能接管，否则故障后永远起不来")
            self.assertIn("接管", why)
            self.assertIn("dead-host", why)
            self.assertEqual(path.read_text(encoding="utf-8"), lock.owner)

    def test_fresh_lock_is_not_taken_over(self):
        """心跳新鲜时不得接管（否则互斥形同虚设）。"""
        mod = load_mod()
        with TempDir() as td:
            path = td / "watcher.lock"
            path.write_text("live-host:1", encoding="utf-8")
            lock = mod.SharedLock(path)
            ok, why = lock.acquire()
            self.assertFalse(ok, why)
            self.assertIn("live-host", why)

    def test_heartbeat_refreshes_age(self):
        mod = load_mod()
        with TempDir() as td:
            path = td / "watcher.lock"
            lock = mod.SharedLock(path)
            self.assertTrue(lock.acquire()[0])
            old = time.time() - 60
            os.utime(path, (old, old))
            self.assertGreater(lock.age(), 30)
            lock.heartbeat()
            self.assertLess(
                lock.age(), 5.0,
                "心跳必须刷新 mtime，否则别的实例会误判本实例已死",
            )

    def test_release_does_not_delete_someone_elses_lock(self):
        """接管后旧实例再 release 不得删掉新持有者的锁。"""
        mod = load_mod()
        with TempDir() as td:
            path = td / "watcher.lock"
            old_holder = mod.SharedLock(path, owner="old:1")
            self.assertTrue(old_holder.acquire()[0])
            path.write_text("new:2", encoding="utf-8")   # 模拟已被别的实例接管
            old_holder.release()
            self.assertTrue(path.exists(), "旧持有者不得删除别人的锁文件")


class _Backend:
    def __init__(self, rows=((1, T1),)):
        self.rows = list(rows)
        self.calls = 0
        self.types_calls = 0
        self.last_server_time = None

    def login(self):
        pass

    def fetch_contract_types(self):
        self.types_calls += 1
        return []

    def fetch_executed_ids(self, competition_id=None, updated_after=None):
        self.calls += 1
        self.last_server_time = f"2026-09-10T12:00:{self.calls:02d}Z"
        return list(self.rows)

    def fetch_contract_detail(self, contract_id):
        return {
            "id": contract_id, "status": "EXECUTED", "competitionId": 1,
            "contractType": {"key": "demo"}, "executedAt": dict(self.rows)[contract_id],
        }


class Cw20MainLockTests(unittest.TestCase):
    def _run(self, mod, backend, rounds=1, argv_extra=None, lock_path=None):
        """跑主循环 rounds 轮（复用 CW-01/02 的假后端与 sleep 中断方式）。"""
        import logging

        from test_cw01_cw02 import LogCapture, StopLoop

        calls: list[int] = []

        def fake_handler(contract, ctx):
            calls.append(contract["id"])

        mod.Backend = lambda s, u, p: backend
        mod.ensure_handlers_file = lambda: None
        mod.load_handlers = lambda: {"demo": fake_handler}
        mod.sync_catalog = lambda *a, **k: False
        mod.default_archive = lambda contract, ctx: f"archived#{contract['id']}"

        capture = LogCapture()
        root = logging.getLogger()
        root.addHandler(capture)
        sleeps: list[float] = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= rounds + 1:
                raise StopLoop()

        mod.time.sleep = fake_sleep

        argv = [
            "contract_watcher.py", "--server", "http://fake", "--username", "u",
            "--password", "p", "--interval", "3", "--port", "0", "--catalog-interval", "0",
            "--out-dir", str(mod.WATCHER_DIR / "records_out"),
        ]
        if lock_path is not None:
            argv += ["--lock-file", str(lock_path)]
        argv += list(argv_extra or [])
        old_argv = sys.argv
        sys.argv = argv
        try:
            try:
                mod.main()
            except StopLoop:
                pass
        finally:
            sys.argv = old_argv
            root.removeHandler(capture)
        return calls, capture.messages
    def test_main_refuses_to_start_when_lock_is_held(self):
        """已有实例持锁时，`main()` 必须直接退出（返回 1）且不处理任何合同。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            lock_path = Path(td) / "shared.lock"
            holder = mod.SharedLock(lock_path, owner="other-machine:777")
            self.assertTrue(holder.acquire()[0])

            calls, logs = self._run(mod, _Backend(), rounds=1, lock_path=lock_path)
            self.assertEqual(calls, [], "被锁挡住时不得处理任何合同")
            self.assertFalse(
                any("拦截" in m for m in logs),
                "不应出现合同处理日志",
            )

    def test_main_releases_lock_on_interrupt(self):
        """主循环被中断（StopLoop/KeyboardInterrupt）时必须释放共享锁。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            lock_path = Path(td) / "shared.lock"
            self._run(mod, _Backend(), rounds=1, lock_path=lock_path)
            self.assertFalse(
                lock_path.exists(),
                "异常退出后锁必须被释放，否则别的机器要等心跳过期（90 秒）才能接管",
            )

    def test_main_stale_lock_is_taken_over_and_starts(self):
        """锁文件心跳过期（上次被强杀）⇒ 本次必须能正常启动并处理合同。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            lock_path = Path(td) / "shared.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text("dead:1", encoding="utf-8")
            old = time.time() - (mod.LOCK_STALE_SECONDS + 60)
            os.utime(lock_path, (old, old))

            calls, logs = self._run(
                mod, _Backend(), rounds=1, lock_path=lock_path,
                argv_extra=["--backfill"],   # 让既有合同本轮就被处理（否则只是建基线）
            )
            self.assertEqual(calls, [1], "接管锁后必须照常处理合同")
            self.assertTrue(
                any("接管" in m for m in logs),
                f"接管过期锁必须留下告警日志，实际 {logs}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
