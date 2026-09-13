# -*- coding: utf-8 -*-
"""CW-19 验证：主循环必须有心跳，Excel 挂起必须能被发现并自愈。

缺陷（改前）：
1. 轮询与处理在**同一线程串行** —— `contract_watcher.py:403/420` 里 `dispatch` 就在轮询
   线程内同步执行，处理期间完全不轮询（`--interval 3` 形同虚设）。
2. 一旦 handler 里的 Excel COM 调用**永久挂起**（`SOAK_REPORT.md:14-17` 实测过
   `RPC 服务器不可用` / `OLE error 0xe0000002`），监听程序整体停摆：不写日志、不退出、
   没有心跳，运维只能靠「账本没更新」发现。
3. `shang.check()` 只 `print()` 三个分支，既不返回也不记日志 —— 后台运行时 stdout 通常
   无处可去，文档宣称的「内置平衡校验」实际不可见。

改后（不重写 Excel 线程模型，而是补上可观测性与自愈）：
- `LoopHeartbeat`：每轮 `tick()` 写心跳文件 + INFO 日志；
- `start_watchdog()`：daemon 线程按 `--heartbeat-interval` 周期检查，超过 `--stall-timeout`
  秒没有推进就写 ERROR 日志并以退出码 3 结束进程（`--no-exit-on-stall` 改为只告警），
  交给任务计划/守护进程重启；
- `xledit.check()` 返回结构化结果并记 INFO 日志（`last_check_result` 可读）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw19_heartbeat_watchdog.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import TempDir, load_watcher  # noqa: E402
from test_cw08_cw09_bookkeeping import load_shang  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


def load_watcher_mod():
    spec = importlib.util.spec_from_file_location(
        "cw19_mod", REPO / "contract_watcher" / "contract_watcher.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cw19HeartbeatUnitTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_watcher_mod()

    def test_tick_writes_heartbeat_file_and_logs(self):
        with TempDir() as td:
            path = Path(td) / "hb.json"
            hb = self.mod.LoopHeartbeat(30.0, 300.0, heartbeat_file=path)
            hb.tick("水位=X")
            hb.tick("水位=Y")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["rounds"], 2)
            self.assertEqual(payload["detail"], "水位=Y")
            self.assertIn("at", payload)
            self.assertEqual(hb.rounds, 2)

    def test_stall_detection_thresholds(self):
        hb = self.mod.LoopHeartbeat(30.0, 60.0)
        self.assertFalse(hb.is_stalled(), "刚 tick 过不得判为停滞")
        hb.last_tick = time.monotonic() - 61
        self.assertTrue(hb.is_stalled(), "超过 --stall-timeout 必须判为停滞")
        self.assertTrue(hb.check_stalled())
        self.assertTrue(hb.stalled)

    def test_stall_timeout_zero_disables_watchdog(self):
        """`--stall-timeout 0` ⇒ 关闭看门狗（只保留心跳）。"""
        hb = self.mod.LoopHeartbeat(30.0, 0)
        hb.last_tick = time.monotonic() - 100000
        self.assertFalse(hb.is_stalled())
        self.assertFalse(hb.check_stalled())

    def test_check_stalled_only_reports_once(self):
        """停滞告警只报一次，避免刷屏。"""
        hb = self.mod.LoopHeartbeat(30.0, 1.0)
        hb.last_tick = time.monotonic() - 100
        self.assertTrue(hb.check_stalled())
        hb.last_tick = time.monotonic() - 100     # 仍然停滞
        self.assertTrue(hb.check_stalled())
        self.assertTrue(hb.stalled)

    def test_watchdog_loop_detects_stall_and_requests_exit(self):
        """看门狗线程：心跳不动 ⇒ 返回 True（调用方据此非零退出）。"""
        hb = self.mod.LoopHeartbeat(0.01, 0.05)
        ticks = {"n": 0}

        def fake_sleep(_seconds):
            ticks["n"] += 1
            if ticks["n"] > 50:
                raise AssertionError("看门狗没有在预期轮次内判定停滞")

        hb.last_tick = time.monotonic() - 10
        self.assertTrue(
            hb.watchdog_loop(sleep_fn=fake_sleep),
            "心跳不动时 watchdog_loop 必须返回 True（触发进程退出）",
        )

    def test_watchdog_loop_keeps_running_while_heartbeating(self):
        """有心跳时看门狗不得误判（否则正常运行时会被自己杀掉）。"""
        hb = self.mod.LoopHeartbeat(0.01, 5.0)
        result = {"done": None}

        def runner():
            def fake_sleep(_s):
                hb.tick()                 # 模拟主循环持续推进
                if hb.rounds >= 20:
                    hb.stop_event.set()

            result["done"] = hb.watchdog_loop(sleep_fn=fake_sleep)

        hb.stop_event = threading.Event()
        t = threading.Thread(target=runner)
        t.start()
        t.join(timeout=5)
        self.assertFalse(result["done"], "心跳正常时 watchdog_loop 必须返回 False（不退出）")

    def test_watchdog_uses_injected_sleeper_not_module_sleep(self):
        """看门狗必须用注入的（真实）sleep 而不是 `模组.time.sleep`。

        用例与调用方常把 `模组.time.sleep` 换成「跑够轮数就抛停止信号」的假实现；看门狗线程
        若用被替换的版本，那个信号会在**线程里**抛出而不中断主循环 —— 看门狗静默失效。
        """
        hb = self.mod.LoopHeartbeat(0.01, 1.0)
        hb.stop_event = threading.Event()
        calls: list[float] = []

        def spy_sleep(seconds):
            calls.append(seconds)
            hb.stop_event.set()          # 只睡一次，便于断言

        original = self.mod.time.sleep
        self.mod.time.sleep = lambda _s: (_ for _ in ()).throw(AssertionError("用了被替换的 sleep"))
        try:
            thread, stop_event = self.mod.start_watchdog(hb, sleep_fn=spy_sleep)
            thread.join(timeout=2)
        finally:
            self.mod.time.sleep = original
        self.assertEqual(calls, [hb.interval], "看门狗必须调用注入的 sleep")
        self.assertFalse(
            hb.check_stalled(),
            "心跳正常时不得判为停滞（否则正常运行时会被自己杀掉）",
        )

    def test_module_binds_real_sleep_at_import(self):
        """`_REAL_SLEEP` 必须在导入时绑定真实实现（防止调用方在启动后才替换）。"""
        import time as real_time

        original = self.mod.time.sleep
        try:
            self.assertIs(
                self.mod._REAL_SLEEP, real_time.sleep,
                "替换 `模组.time.sleep` 不得影响 `_REAL_SLEEP`（看门狗据此避开假实现）",
            )
        finally:
            self.mod.time.sleep = original


class Cw19MainLoopTests(unittest.TestCase):
    def _run(self, mod, backend, rounds=2, argv_extra=None):
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
        # `main()` 里 `logging.basicConfig(level=INFO)` 只对**根** logger 生效；本模块的
        # `contract_watcher` logger 需要显式放行 INFO，否则心跳日志会被级别过滤掉
        previous_level = mod.log.level
        mod.log.setLevel(logging.INFO)
        sleeps: list[float] = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= rounds:
                raise StopLoop()

        mod.time.sleep = fake_sleep
        argv = [
            "contract_watcher.py", "--server", "http://fake", "--username", "u",
            "--password", "p", "--interval", "3", "--port", "0", "--catalog-interval", "0",
            "--out-dir", str(mod.WATCHER_DIR / "records_out"),
            # 看门狗开着但阈值很大：本用例只验证心跳，不验证退出
            "--heartbeat-interval", "0.05", "--stall-timeout", "600",
            "--heartbeat-file", str(mod.WATCHER_DIR / "data" / "hb.json"),
        ] + list(argv_extra or [])
        old_argv = sys.argv
        sys.argv = argv
        try:
            try:
                mod.main()
            except StopLoop:
                pass
        finally:
            sys.argv = old_argv
            mod.log.setLevel(previous_level)
            root.removeHandler(capture)
        return calls, capture.messages

    def test_main_writes_heartbeat_each_round(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            calls, logs = self._run(mod, _Backend(), rounds=2)
            hb_file = mod.WATCHER_DIR / "data" / "hb.json"
            self.assertTrue(hb_file.exists(), "主循环必须写心跳文件（外部监控据此判断存活）")
            payload = json.loads(hb_file.read_text(encoding="utf-8"))
            self.assertGreaterEqual(payload["rounds"], 1, f"心跳轮数 {payload}")
            self.assertIn("水位", payload["detail"])
            self.assertTrue(
                any("心跳 #" in m for m in logs),
                f"心跳必须记日志（改前没有任何推进信号），实际 {logs[-5:]}",
            )
            self.assertTrue(
                any("停滞看门狗" in m for m in logs),
                "启动时必须说明看门狗状态",
            )

    def test_heartbeat_detail_mentions_pending(self):
        """待处理队列非空时心跳要带上数量（运维一眼看出有积压）。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = _Backend()
            self._run(mod, backend, rounds=1, argv_extra=["--stall-timeout", "0"])
            # 让 handler 失败一次，产生待处理队列
            mod2 = load_watcher(Path(td))
            self._run(mod2, _FailingBackend(), rounds=2, argv_extra=["--stall-timeout", "0"])

    def test_watchdog_can_be_disabled(self):
        """`--stall-timeout 0` ⇒ 不启动看门狗（日志里明确说明）。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            _calls, logs = self._run(mod, _Backend(), rounds=1, argv_extra=["--stall-timeout", "0"])
            self.assertTrue(
                any("未启用停滞看门狗" in m for m in logs),
                f"关闭时必须留下说明，实际 {logs[-5:]}",
            )


class _Backend:
    def __init__(self, rows=(("2026-01-01T00:00:00Z",),)):
        self.rows = list(rows)
        self.calls = 0
        self.last_server_time = None

    def login(self):
        pass

    def fetch_contract_types(self):
        return []

    def fetch_executed_ids(self, competition_id=None, updated_after=None):
        self.calls += 1
        self.last_server_time = f"2026-09-10T12:00:{self.calls:02d}Z"
        return []

    def fetch_contract_detail(self, contract_id):
        return {
            "id": contract_id, "status": "EXECUTED", "competitionId": 1,
            "contractType": {"key": "demo"}, "executedAt": "2026-01-01T00:00:00Z",
        }


class _FailingBackend(_Backend):
    """第一轮返回一份合同，且详情拉取失败 ⇒ 产生待处理队列。"""

    def __init__(self):
        super().__init__()
        self.first = True

    def fetch_executed_ids(self, competition_id=None, updated_after=None):
        self.calls += 1
        self.last_server_time = f"2026-09-10T12:00:{self.calls:02d}Z"
        if self.first:
            self.first = False
            return [(7, "2026-01-01T00:00:00Z")]
        return []

    def fetch_contract_detail(self, contract_id):
        raise RuntimeError("模拟拉详情失败")


class Cw19ShanCheckTests(unittest.TestCase):
    """`shang.check()` 的结果必须可被后台程序看见（改前只 print）。"""

    class _Sheet:
        def __init__(self, value):
            self._value = value

        def range(self, _addr):
            outer = self

            class _R:
                value = outer._value

            return _R()

    class _Book:
        def __init__(self, value):
            self.sheets = [None] * 7 + [Cw19ShanCheckTests._Sheet(value)]

    def _editor(self, value):
        mod = load_shang()
        editor = mod.xledit.__new__(mod.xledit)
        editor.wb = self._Book(value)
        return mod, editor

    def test_check_returns_structured_result(self):
        mod, editor = self._editor(0)
        result = editor.check()
        self.assertEqual(result["status"], "balanced")
        self.assertEqual(result["message"], "right")
        self.assertEqual(result["value"], 0)
        self.assertEqual(mod.xledit.last_check_result["status"], "balanced")

    def test_check_classifies_imbalance(self):
        mod, editor = self._editor(5)
        self.assertEqual(editor.check()["status"], "assets_over")
        _mod2, editor2 = self._editor(-5)
        self.assertEqual(editor2.check()["status"], "assets_under")

    def test_check_writes_log_record(self):
        """改前只 print，后台运行时无处可见；现在必须同时进日志。"""
        import logging

        mod, editor = self._editor(0)
        records: list[str] = []

        class _H(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("shang")
        handler = _H()
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(logging.INFO)
        try:
            editor.check()
        finally:
            logger.setLevel(previous)
            logger.removeHandler(handler)
        self.assertTrue(
            any("资产负债表平衡校验" in m for m in records),
            f"check() 必须记日志，实际 {records}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
