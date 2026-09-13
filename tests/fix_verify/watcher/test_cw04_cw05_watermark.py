# -*- coding: utf-8 -*-
"""CW-04 / CW-05 验证：水位线比较按时间、列表按合同 id 去重。

CW-05（永久漏账）：改前水位线用字符串比较（`t > last_seen`）。后端 timezone.now() 的序列化形态
不固定，`2026-01-02T00:00:00Z` 与 `2026-01-02T00:00:00.500000Z` 字符串比较会得出后者**更小**
（'.' < 'Z'）→ 同秒内后通过的合同被判为「不新」，永久不会被处理。
CW-04（重复记账）：`fetch_executed_ids` 按 offset 分页拼接，数据变动导致分页漂移时同一条合同
可能出现在两页 → 同一轮重复分发。

跑的是真实 contract_watcher.py（进程内加载，落盘路径重定向 / Backend 换假实现）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw04_cw05_watermark.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
import uuid
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

REPO = Path(__file__).resolve().parents[3]
WATCHER_PY = REPO / "contract_watcher" / "contract_watcher.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import FakeBackend, LogCapture, load_watcher, read_state, run_watcher  # noqa: E402

BASE = "2026-01-02T00:00:00Z"
MICRO = "2026-01-02T00:00:00.500000Z"


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"cw_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def seed_watermark(mod, watermark: str):
    mod.STATE_FILE.write_text(
        json.dumps({"baselineAt": "2025-12-31T00:00:00Z", "lastExecutedAt": watermark}),
        encoding="utf-8",
    )


class Cw05WatermarkTests(unittest.TestCase):
    def test_microsecond_later_contract_is_processed(self):
        """水位 00:00:00Z、合同 00:00:00.500000Z：按时间更新 → 必须处理（改前字符串比较漏掉）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            seed_watermark(mod, BASE)
            backend = FakeBackend([(1, MICRO)])
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            self.assertEqual(
                calls, [1],
                f"同秒内更晚的合同不得被漏掉（改前字符串比较判为不新），实际处理 {calls}",
            )
            self.assertEqual(read_state(mod).get("lastExecutedAt"), MICRO)

    def test_older_contract_is_not_reprocessed(self):
        """反向：水位 00:00:00.500000Z、合同 00:00:00Z → 不得重复处理。"""
        with TempDir() as td:
            mod = load_watcher(td)
            seed_watermark(mod, MICRO)
            backend = FakeBackend([(1, BASE)])
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            self.assertEqual(calls, [], "比水位更早的合同不得被重复处理")
            self.assertEqual(read_state(mod).get("lastExecutedAt"), MICRO)

    def test_baseline_uses_time_order_not_string_order(self):
        """建立基线时也按时间取最大：列表里含小数秒时间戳时水位应取真正最新的那条。"""
        with TempDir() as td:
            mod = load_watcher(td)
            backend = FakeBackend([(1, BASE), (2, MICRO)])
            run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            self.assertEqual(
                read_state(mod).get("lastExecutedAt"), MICRO,
                "基线应取时间上最新的 executedAt（字符串比较会取到 BASE）",
            )

    def test_seconds_precision_watermark_from_old_version_still_works(self):
        """兼容旧 state：水位是秒级 'Z' 形态时，带 +00:00 形态的新合同也要被识别为更新。"""
        with TempDir() as td:
            mod = load_watcher(td)
            seed_watermark(mod, BASE)
            backend = FakeBackend([(1, "2026-01-03T00:00:00+00:00")])
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            self.assertEqual(calls, [1])


class Cw04DedupTests(unittest.TestCase):
    def _backend_with_pages(self, pages):
        """用真实 Backend.fetch_executed_ids，只替换其 self.api（模拟分页返回）。"""
        mod = load_watcher_isolated()
        backend = mod.Backend("http://fake", "u", "p")
        backend.token = "t"
        calls = {"n": 0}

        def fake_api(path):
            page = int(path.split("page=")[1].split("&")[0])
            calls["n"] += 1
            return pages.get(page, {"items": [], "total": 0})

        backend.api = fake_api
        return backend, calls

    def test_duplicate_id_across_pages_is_deduped(self):
        """分页漂移：同一合同 id 出现在两页 → 结果只保留一条（避免同轮重复分发）。"""
        pages = {
            1: {"items": [{"id": 7, "executedAt": BASE}, {"id": 8, "executedAt": BASE}], "total": 3},
            2: {"items": [{"id": 7, "executedAt": MICRO}], "total": 3},
        }
        backend, _calls = self._backend_with_pages(pages)
        rows = backend.fetch_executed_ids(None)
        ids = [cid for cid, _ in rows]
        self.assertEqual(sorted(ids), [7, 8], f"同一 id 不得重复出现，实际 {ids}")
        self.assertEqual(
            dict(rows)[7], MICRO,
            "同 id 重复出现时应保留更新的 executedAt",
        )

    def test_full_round_processes_duplicate_once(self):
        """即使列表里同一条合同出现两次，本轮也只处理一次。"""
        with TempDir() as td:
            mod = load_watcher(td)
            seed_watermark(mod, "")
            backend = FakeBackend([(1, BASE), (1, BASE)])  # 模拟分页重复返回
            calls, _logs = run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            self.assertEqual(calls, [1], f"重复条目只应处理一次，实际 {calls}")


def load_watcher_isolated():
    """只加载模块（不重定向路径），用于直接测 Backend.fetch_executed_ids。"""
    spec = importlib.util.spec_from_file_location("cw_backend_under_test", WATCHER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    unittest.main(verbosity=2)
