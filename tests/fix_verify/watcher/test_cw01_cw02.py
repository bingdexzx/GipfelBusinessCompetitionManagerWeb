# -*- coding: utf-8 -*-
"""CW-01 / CW-02 验证：合同监听程序的水位线与失败重试。

CW-01（改前）：首次运行时 `fetch_executed_ids` 抛异常 → 把 `lastExecutedAt=""` 写进 state.json
→ 下一轮所有历史 EXECUTED 合同都被判为「新通过」而全量重放（重复记账、无幂等键）。
CW-02（改前）：`dispatch` 吞异常且无返回值，主循环按列表 max 推进水位 → 处理失败（或详情状态
不符）的合同被水位越过，永久静默漏记、永不重试、无告警。

本文件在进程内加载**真实的 contract_watcher.py**（把落盘路径重定向到临时目录、
Backend 换成假实现、time.sleep 在跑到指定轮数后抛出停止信号），因此改前/改后跑的是同一套断言。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw01_cw02.py
"""
from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import sys
import unittest
import uuid
import warnings
from pathlib import Path

# main() 的单实例互斥 socket 在进程内不会关闭，屏蔽资源告警噪声
warnings.filterwarnings("ignore", category=ResourceWarning)

REPO = Path(__file__).resolve().parents[3]
WATCHER_PY = REPO / "contract_watcher" / "contract_watcher.py"
# 临时目录放在仓库内（系统 temp 目录在本机沙箱下不可清理）
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


class TempDir:
    """仓库内的临时目录。

    与本机环境有关的两个坑：系统 temp 目录在沙箱下不可清理；`tempfile.mkdtemp` 建出的目录
    在沙箱下不允许再写入子文件，故这里自己用 uuid 命名 + `mkdir`。
    """

    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"cw_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False

T1 = "2026-01-01T00:00:00Z"
T2 = "2026-01-02T00:00:00Z"


class StopLoop(Exception):
    """达到指定轮数后中断 main() 的无限循环。"""


class FakeBackend:
    """假后端：可配置 executed 列表、详情状态、异常注入。

    审计 CW-12 之后监听程序默认走**增量协议**（`updatedAfter` + 服务端游标不分页），
    所以这里也如实返回 `incremental=True` 与 `serverTime`，并按游标过滤，便于用例覆盖
    「每轮只拉变更」的行为。
    """

    def __init__(self, rows, details=None, fail_ids_times=0, incremental=True):
        self.rows = list(rows)
        self.details = details or {}
        self.fail_ids_times = fail_ids_times
        # 审计 CW-12：记录每次拉取用的游标与「本轮实际返回的条数」，供用例断言流量特征
        self.incremental = incremental
        self.ids_calls = 0
        self.detail_calls = []
        self.cursors: list = []
        self.returned_counts: list[int] = []
        self.last_server_time: str | None = None

    def login(self):
        pass

    def fetch_contract_types(self):
        return []

    def fetch_executed_ids(self, competition_id=None, updated_after=None):
        self.ids_calls += 1
        self.cursors.append(updated_after)
        if self.ids_calls <= self.fail_ids_times:
            raise RuntimeError("模拟网络抖动：拉取已执行合同列表失败")
        if self.incremental:
            # 增量模式：只回「比游标新」的行，并给出服务端时间
            rows = [
                (cid, et) for cid, et in self.rows
                if updated_after is None or (et or "") > str(updated_after)
            ]
            self.last_server_time = f"2026-01-01T00:00:{self.ids_calls:02d}Z"
            self.returned_counts.append(len(rows))
            return rows
        self.returned_counts.append(len(self.rows))
        return list(self.rows)

    def fetch_contract_detail(self, contract_id):
        self.detail_calls.append(contract_id)
        if contract_id in self.details:
            return self.details[contract_id]
        return {
            "id": contract_id,
            "status": "EXECUTED",
            "competitionId": 1,
            "contractType": {"key": "demo"},
            "executedAt": dict(self.rows).get(contract_id, T1),
        }


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def load_watcher(tmpdir: Path):
    """加载真实的 contract_watcher.py 并把可写路径重定向到 tmpdir。"""
    spec = importlib.util.spec_from_file_location("cw_under_test", WATCHER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.WATCHER_DIR = tmpdir
    mod.HANDLERS_FILE = tmpdir / "handlers.py"
    mod.STATE_FILE = tmpdir / "data" / "state.json"
    mod.LOG_FILE = tmpdir / "watcher.log"
    mod.RECORDS_DIR = tmpdir / "records"
    mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
    (tmpdir / "data").mkdir(parents=True, exist_ok=True)
    return mod


def run_watcher(mod, backend, handler, rounds, argv_extra=None):
    """跑 rounds 轮主循环；返回 (handler_calls, logs)。"""
    handler_calls: list[int] = []

    def fake_handler(contract, ctx):
        handler_calls.append(contract["id"])
        return handler(contract, ctx)

    mod.Backend = lambda server, username, password: backend
    mod.ensure_handlers_file = lambda: None
    mod.load_handlers = lambda: {"demo": fake_handler}
    mod.sync_catalog = lambda *a, **k: False
    mod.default_archive = lambda contract, ctx: f"archived#{contract['id']}"

    capture = LogCapture()
    root = logging.getLogger()
    root.addHandler(capture)

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] >= rounds:
            raise StopLoop()

    mod.time.sleep = fake_sleep

    argv = [
        "contract_watcher.py",
        "--server", "http://fake",
        "--username", "u",
        "--password", "p",
        "--interval", "0.001",
        # 审计 CW-12：类型目录默认 60s 才同步一次；用例里 sync_catalog 已被替换，
        # 这里显式关掉节流，保持「每轮都走到」的语义
        "--catalog-interval", "0",
        "--port", "0",
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
    return handler_calls, capture.messages


def read_state(mod):
    if not mod.STATE_FILE.exists():
        return {}
    return json.loads(mod.STATE_FILE.read_text(encoding="utf-8"))


class Cw01BaselineTests(unittest.TestCase):
    """首次基线拉取失败时不得重放历史合同。"""

    def test_failed_baseline_does_not_write_empty_watermark(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            # 两次都失败：启动时一次 + 本轮重试一次（否则本轮就恢复并建立基线了）
            backend = FakeBackend([(1, T1), (2, T2)], fail_ids_times=2)
            run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            state = read_state(mod)
            self.assertNotIn(
                "lastExecutedAt", state,
                f"基线拉取失败时不得落空水位（改前写入 lastExecutedAt={state.get('lastExecutedAt')!r}）",
            )

    def test_no_replay_after_baseline_recovers(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = FakeBackend([(1, T1), (2, T2)], fail_ids_times=1)
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=3)
            self.assertEqual(
                calls, [],
                f"基线恢复后历史合同不得被当作新通过而重放，实际处理了 {calls}",
            )
            self.assertEqual(read_state(mod).get("lastExecutedAt"), T2)

    def test_backfill_still_replays_on_purpose(self):
        """--backfill 是显式要求回填存量，仍应处理全部历史合同（行为不回归）。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = FakeBackend([(1, T1), (2, T2)])
            calls, _logs = run_watcher(
                mod, backend, handler=lambda c, ctx: None, rounds=1, argv_extra=["--backfill"]
            )
            self.assertEqual(calls, [1, 2])

    def test_baseline_success_processes_only_later_contracts(self):
        """基线成功建立后，只有「比水位更新」的合同会被处理。"""
        with TempDir() as td:
            mod = load_watcher(Path(td))
            backend = FakeBackend([(1, T1), (2, T2)])
            # 第一轮建立基线（不处理），随后出现一条更新的合同 → 第二轮应只处理它
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=2)
            self.assertEqual(calls, [])

            backend.rows.append((3, "2026-01-03T00:00:00Z"))
            calls2, _logs2 = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            self.assertEqual(calls2, [3])


class Cw02RetryTests(unittest.TestCase):
    """处理失败的合同必须重试、不得被水位越过。"""

    def _seed_state(self, mod):
        mod.STATE_FILE.write_text(
            json.dumps({"baselineAt": "2025-12-31T00:00:00Z", "lastExecutedAt": ""}),
            encoding="utf-8",
        )

    def test_failed_contract_is_retried_and_kept_pending(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            self._seed_state(mod)
            backend = FakeBackend([(1, T1), (2, T2)])

            def handler(contract, ctx):
                if contract["id"] == 1:
                    raise RuntimeError("模拟处理失败（如 Excel 被占用）")

            calls, logs = run_watcher(mod, backend, handler=handler, rounds=3)

            self.assertEqual(
                calls.count(1), 3,
                f"失败合同每轮都应重试（改前只尝试一次即被水位越过），实际尝试 {calls.count(1)} 次",
            )
            self.assertEqual(calls.count(2), 1, "成功合同不得重复处理")
            state = read_state(mod)
            self.assertEqual(
                [p["id"] for p in state.get("pendingExecuted", [])], [1],
                f"失败合同必须留在待处理队列，实际 {state.get('pendingExecuted')}",
            )
            self.assertEqual(state.get("lastExecutedAt"), T2)
            self.assertTrue(
                any("待处理" in m for m in logs),
                f"必须有告警日志，实际日志：{logs}",
            )

    def test_pending_is_cleared_after_success(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            self._seed_state(mod)
            backend = FakeBackend([(1, T1)])
            flag = {"fail": True}

            def handler(contract, ctx):
                if flag["fail"]:
                    raise RuntimeError("先失败一次")

            calls, _logs = run_watcher(mod, backend, handler=handler, rounds=1)
            self.assertEqual(calls, [1])
            self.assertEqual([p["id"] for p in read_state(mod).get("pendingExecuted", [])], [1])

            flag["fail"] = False
            calls2, _logs2 = run_watcher(mod, backend, handler=handler, rounds=1)
            self.assertEqual(calls2, [1], "下一轮必须重试待处理合同")
            self.assertEqual(
                read_state(mod).get("pendingExecuted"), [],
                "重试成功后必须移出待处理队列",
            )

    def test_detail_status_mismatch_is_not_silently_skipped(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            self._seed_state(mod)
            backend = FakeBackend(
                [(1, T1), (2, T2)],
                details={2: {"id": 2, "status": "PENDING_EXEC", "contractType": {"key": "demo"}}},
            )
            calls, logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=2)

            self.assertEqual(calls, [1], "状态不符的合同不处理，但也不能静默丢弃")
            self.assertEqual(
                sorted(p["id"] for p in read_state(mod).get("pendingExecuted", [])), [2],
                "状态不符的合同应留在待处理队列并告警",
            )
            self.assertTrue(
                any("详情状态" in m for m in logs),
                f"状态不符必须有告警日志，实际日志：{logs}",
            )

    def test_detail_fetch_failure_is_retried(self):
        with TempDir() as td:
            mod = load_watcher(Path(td))
            self._seed_state(mod)

            class FlakyDetail(FakeBackend):
                def fetch_contract_detail(self, contract_id):
                    if contract_id == 1 and self.ids_calls < 3:
                        raise RuntimeError("模拟拉详情失败")
                    return super().fetch_contract_detail(contract_id)

            backend = FlakyDetail([(1, T1)])
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=4)
            self.assertIn(1, calls, "拉详情失败后必须在后续轮次重试并最终处理")


if __name__ == "__main__":
    unittest.main(verbosity=2)
