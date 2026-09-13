# -*- coding: utf-8 -*-
"""CW-12 验证：增量拉取 + 失败退避 + 类型目录节流。

缺陷（改前）：
1. 每轮都 `status=EXECUTED&page=N&pageSize=200` 把**全部历史** EXECUTED 合同全量分页拉一遍，
   而列表接口对每行都返回完整合同（`contractType` 的 effects/conditions/graph +
   executionLog/executionResult + 逐行公司反查）。合同数 N ⇒ 每轮 `ceil(N/200)+1` 个重请求，
   开销只增不减 —— 后端已经有增量协议（`apps/common/sync.py` 的 `updatedAfter`）却没被用上。
2. 无论成功失败都固定 `time.sleep(max(0.5, --interval))`：后端不可用时仍以同一节奏持续打请求，
   永不衰减、无抖动。
3. 每轮都全量拉一次 `/api/contract-types`（含完整 DSL），而类型新建/改名是低频事件。

改后：
1. 有游标时走增量协议（服务端游标、不分页），每轮请求量只与「这轮新增/变更」成正比；
   服务端返回的 `serverTime` 存进 `state["lastUpdatedAt"]` 作为下一轮游标；
2. 失败时指数退避 + 抖动（上限 60 秒），成功后立刻恢复到 `--interval`；
3. `--catalog-interval`（默认 60 秒，0=每轮）节流类型目录同步。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw12_incremental_polling.py
"""
from __future__ import annotations

import logging
import random
import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import (  # noqa: E402
    T1, T2, LogCapture, StopLoop, TempDir, load_watcher, read_state,
)

T3 = "2026-01-03T00:00:00Z"


def run_rounds(mod, backend, rounds, argv_extra=None, handler=None, real_catalog=False):
    """跑 rounds 轮主循环；返回 dict(calls, logs, sleeps, catalog_calls)。

    注意：`main()` 启动时会先建一次基线（一次 `fetch_executed_ids`），随后每轮再拉一次；
    因此 rounds 轮的游标序列通常是 [None(启动), None(第1轮), 第2轮…]。
    `sync_catalog` 默认被替换成空实现；需要考察节流行为时传 `real_catalog=True`。
    """
    handler_calls: list[int] = []

    def fake_handler(contract, ctx):
        handler_calls.append(contract["id"])
        if handler:
            return handler(contract, ctx)

    catalog_calls = {"n": 0}
    loops = {"n": 0}
    real_sync = mod.sync_catalog
    real_process = mod.process_fresh_contracts

    def sync_wrapper(backend_, state, registry_ref, min_interval=None):
        catalog_calls["n"] += 1
        if not real_catalog:
            return False
        return real_sync(backend_, state, registry_ref, min_interval)

    def process_wrapper(*a, **k):
        loops["n"] += 1
        return real_process(*a, **k)

    mod.sync_catalog = sync_wrapper
    mod.process_fresh_contracts = process_wrapper

    mod.Backend = lambda server, username, password: backend
    mod.ensure_handlers_file = lambda: None
    mod.load_handlers = lambda: {"demo": fake_handler}
    mod.default_archive = lambda contract, ctx: f"archived#{contract['id']}"

    capture = LogCapture()
    root = logging.getLogger()
    root.addHandler(capture)

    sleeps: list[float] = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= rounds + 1:   # +1：启动阶段的基线拉取失败也会先 sleep 一次
            raise StopLoop()

    mod.time.sleep = fake_sleep

    argv = [
        "contract_watcher.py", "--server", "http://fake", "--username", "u",
        "--password", "p", "--interval", "3", "--port", "0",
        "--out-dir", str(mod.WATCHER_DIR / "records_out"),
    ] + list(argv_extra or [])
    old_argv = sys.argv
    sys.argv = argv
    try:
        with unittest.TestCase().assertRaises(StopLoop):
            mod.main()
    finally:
        sys.argv = old_argv
        root.removeHandler(capture)
    return {
        "calls": handler_calls, "logs": capture.messages,
        "sleeps": sleeps, "catalog_calls": catalog_calls["n"], "loops": loops["n"],
    }


class Cw12QueryBuilderTests(unittest.TestCase):
    """`build_executed_query` 的纯函数语义。"""

    def setUp(self):
        from test_cw01_cw02 import load_watcher as _lw  # noqa: F401
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cw12_mod", Path(__file__).resolve().parents[3] / "contract_watcher" / "contract_watcher.py"
        )
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_paged_query_when_no_cursor(self):
        q = self.mod.build_executed_query(1, None, 2)
        self.assertIn("status=EXECUTED", q)
        self.assertIn("competitionId=1", q)
        self.assertIn("page=2", q)
        self.assertIn("pageSize=200", q)
        self.assertNotIn("updatedAfter", q)

    def test_incremental_query_when_cursor_present(self):
        """有游标时必须走增量：带 updatedAfter、且**不带分页参数**。"""
        q = self.mod.build_executed_query(1, "2026-09-10T00:00:00Z", 3)
        self.assertIn("updatedAfter=", q)
        self.assertIn("2026-09-10", q)
        self.assertNotIn("page=", q, "增量协议是服务端游标，不应再带 page")
        self.assertNotIn("pageSize", q)

    def test_competition_zero_is_still_filtered(self):
        """CW-11 的回归：0 也必须出现在查询串里（不能被当成「不筛选」）。"""
        self.assertIn("competitionId=0", self.mod.build_executed_query(0, None, 1))


class Cw12BackoffTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cw12_mod2", Path(__file__).resolve().parents[3] / "contract_watcher" / "contract_watcher.py"
        )
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_backoff_doubles_and_is_capped(self):
        rng = lambda: 0.0  # noqa: E731 - 去掉抖动便于断言
        d = 3.0
        seen = []
        for _ in range(8):
            d = self.mod.next_backoff(d, 3.0, cap=60.0, rng=rng)
            seen.append(d)
        self.assertEqual(seen[:4], [6.0, 12.0, 24.0, 48.0])
        self.assertEqual(seen[-1], 60.0, f"必须封顶在 cap，实际 {seen}")

    def test_backoff_never_below_interval(self):
        """已是间隔值时不得退到更短（避免退避形同虚设）。"""
        self.assertEqual(self.mod.next_backoff(0.1, 3.0, rng=lambda: 0.0), 3.0)

    def test_backoff_has_jitter(self):
        """必须带抖动：否则多实例同频重试会形成惊群。"""
        vals = {self.mod.next_backoff(3.0, 3.0, rng=lambda: v) for v in (0.0, 0.5, 1.0)}
        self.assertEqual(len(vals), 3, f"抖动应随随机数变化，实际 {vals}")
        hi = self.mod.next_backoff(3.0, 3.0, rng=lambda: 0.999)
        self.assertLessEqual(hi, 6.0 * 1.25 + 1e-9, "抖动幅度不应超过 25%")


class Cw12CatalogThrottleTests(unittest.TestCase):
    """类型目录同步节流（通过假后端的 `fetch_contract_types` 计数观察）。"""

    def _run(self, rounds, argv_extra=None, tick=0.01):
        td = TempDir()
        self.addCleanup(td.__exit__, None, None, None)
        mod = load_watcher(Path(td.__enter__()))
        backend = _IncBackend([(1, T1)])
        clock = {"t": 1000.0}
        real_monotonic = mod.time.monotonic

        def fake_monotonic():
            clock["t"] += tick
            return clock["t"]

        mod.time.monotonic = fake_monotonic
        try:
            r = run_rounds(mod, backend, rounds=rounds, real_catalog=True, argv_extra=argv_extra)
        finally:
            mod.time.monotonic = real_monotonic
        return r, backend, mod

    def test_default_interval_syncs_once_per_launch(self):
        """默认 60 秒内只同步一次（启动那次）—— 改前每轮都全量拉一次目录。"""
        r, backend, mod = self._run(rounds=3)
        self.assertGreaterEqual(r["loops"], 1, "用例应至少跑到一轮主循环")
        self.assertEqual(
            backend.types_calls, 1,
            f"默认 60s 内只应同步一次类型目录，实际 {backend.types_calls} 次",
        )

    def test_syncs_again_after_interval_elapsed(self):
        """每次单调时钟推进 120 秒（> 默认 60 秒）→ 每轮都必须重新同步。"""
        r, backend, _mod = self._run(rounds=2, tick=120.0)
        self.assertEqual(
            backend.types_calls, 1 + r["loops"],
            f"超过间隔后必须重新同步（loops={r['loops']}），实际 {backend.types_calls} 次",
        )

    def test_interval_zero_restores_per_round_sync(self):
        """`--catalog-interval 0` 恢复每轮同步（旧行为，便于排障）。"""
        r, backend, _mod = self._run(rounds=2, argv_extra=["--catalog-interval", "0"])
        self.assertEqual(
            backend.types_calls, 1 + r["loops"],
            f"启动 + 每轮都应同步（loops={r['loops']}），实际 {backend.types_calls} 次",
        )


class Cw12IntegrationTests(unittest.TestCase):
    def test_first_round_has_no_cursor_then_reuses_one(self):
        """启动时无游标（全量建基线），之后每轮都带上一轮的服务端时间。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = _IncBackend([(1, T1)])
            run_rounds(mod, backend, rounds=3)
            self.assertIsNone(backend.cursors[0], "启动阶段尚无游标")
            self.assertIsNone(backend.cursors[1], "第一轮仍无游标（基线刚建立）")
            self.assertTrue(
                all(c for c in backend.cursors[2:]),
                f"之后每轮都必须带游标，实际 {backend.cursors}",
            )
            self.assertEqual(
                read_state(mod).get("lastUpdatedAt"), backend.last_server_time,
                "state 里必须记下服务端时间作为下一轮游标",
            )

    def test_later_rounds_only_return_changed_rows(self):
        """增量协议下，带游标的轮次只回「比游标新」的行 —— 请求量不再随历史线性增长。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = _IncBackend([(1, T1), (2, T2)])
            run_rounds(mod, backend, rounds=3)
            self.assertEqual(backend.returned_counts[0], 2, "启动阶段全量建基线")
            self.assertEqual(
                backend.returned_counts[-1], 0,
                f"带游标的轮次不应再拉历史合同，实际逐轮返回 {backend.returned_counts}",
            )

    def test_legacy_backend_without_incremental_still_works(self):
        """后端不支持 updatedAfter（仍按分页返回）时必须照常工作（向后兼容）。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = _IncBackend([(1, T1)], incremental=False)
            r1 = run_rounds(mod, backend, rounds=2)
            self.assertEqual(r1["calls"], [], "历史合同仍不得被当作新合同重放")

            backend.rows.append((2, T2))
            r2 = run_rounds(mod, backend, rounds=1)
            self.assertEqual(r2["calls"], [2], "分页模式下的新合同仍必须被处理")

    def test_failures_back_off_and_recover(self):
        """后端持续失败：sleep 不低于 --interval 且首轮就退避；全程失败时退到接近上限。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = _IncBackend([(1, T1)], fail_times=2)
            r = run_rounds(mod, backend, rounds=4)
            sleeps = r["sleeps"]

            self.assertGreater(
                sleeps[0], 3.0,
                f"首次失败就必须退避到 --interval 以上，实际 {sleeps}",
            )
            self.assertTrue(
                all(s >= 3.0 for s in sleeps),
                f"退避不得低于 --interval，实际 {sleeps}",
            )
            self.assertEqual(
                sleeps[-1], 3.0,
                f"后端恢复后必须回到 --interval=3，实际 {sleeps}",
            )

    def test_backoff_is_capped(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = _IncBackend([(1, T1)], fail_times=99)
            r = run_rounds(mod, backend, rounds=8)
            sleeps = r["sleeps"]
            self.assertLessEqual(
                max(sleeps), mod.MAX_BACKOFF_SECONDS * 1.25 + 1e-6,
                f"退避必须封顶，实际 {sleeps}",
            )
            self.assertGreater(
                max(sleeps), 30.0, f"持续失败应退到接近上限，实际 {sleeps}",
            )


class _IncBackend:
    """支持增量协议的假后端（记录游标与每轮返回条数）。"""

    def __init__(self, rows, fail_times=0, incremental=True):
        self.rows = list(rows)
        self.fail_times = fail_times
        self.incremental = incremental
        self.calls = 0
        self.types_calls = 0
        self.cursors: list = []
        self.returned_counts: list[int] = []
        self.last_server_time: str | None = None

    def login(self):
        pass

    def fetch_contract_types(self):
        self.types_calls += 1
        return []

    def fetch_executed_ids(self, competition_id=None, updated_after=None):
        self.calls += 1
        self.cursors.append(updated_after)
        if self.calls <= self.fail_times:
            raise RuntimeError("模拟后端不可用")
        if self.incremental:
            rows = [
                (cid, et) for cid, et in self.rows
                if updated_after is None or (et or "") > str(updated_after)
            ]
            self.last_server_time = f"2026-09-10T12:00:{self.calls:02d}Z"
            self.returned_counts.append(len(rows))
            return rows
        self.returned_counts.append(len(self.rows))
        return list(self.rows)

    def fetch_contract_detail(self, contract_id):
        return {
            "id": contract_id, "status": "EXECUTED", "competitionId": 1,
            "contractType": {"key": "demo"},
            "executedAt": dict(self.rows).get(contract_id, T1),
        }


if __name__ == "__main__":
    unittest.main(verbosity=2)
