# -*- coding: utf-8 -*-
"""CW-27 验证：EXECUTED 但 executedAt 为空的合同必须告警，不能静默忽略。

缺陷（改前）：`fetch_executed_ids` 用 `if not it.get("executedAt"): continue` 静默跳过这类行
（文档还断言「EXECUTED 一定有 executedAt」），于是后端数据异常时这些合同**一份都不会被记账**，
而日志里没有任何痕迹 —— 事后再查只能看到「合同少了」，无法判断是被跳过还是从未执行。

改后：跳过时累计并在本轮结束时记 warning，列出合同 id（最多 10 个）与总数。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw27_missing_executed_at.py
"""
from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import LogCapture, TempDir, load_watcher  # noqa: E402


class MissingExecutedAtTests(unittest.TestCase):
    def _backend(self, mod, items):
        backend = mod.Backend("http://fake", "u", "p")
        backend.token = "t"
        backend.api = lambda path: {"items": items, "total": len(items)}
        return backend

    def test_missing_executed_at_is_reported(self):
        import logging

        with TempDir() as td:
            mod = load_watcher(td)
            backend = self._backend(
                mod,
                [
                    {"id": 1, "executedAt": "2026-01-01T00:00:00Z"},
                    {"id": 2, "executedAt": ""},
                    {"id": 3},                       # 完全没有该字段
                ],
            )
            cap = LogCapture()
            logging.getLogger().addHandler(cap)
            try:
                rows = backend.fetch_executed_ids(None)
            finally:
                logging.getLogger().removeHandler(cap)

            self.assertEqual([cid for cid, _ in rows], [1], "有 executedAt 的照常返回")
            self.assertTrue(
                any("没有 executedAt" in m and "2" in m for m in cap.messages),
                f"必须告警并列出被跳过的合同 id（改前静默）：{cap.messages}",
            )

    def test_no_warning_when_all_rows_have_executed_at(self):
        import logging

        with TempDir() as td:
            mod = load_watcher(td)
            backend = self._backend(mod, [{"id": 1, "executedAt": "2026-01-01T00:00:00Z"}])
            cap = LogCapture()
            logging.getLogger().addHandler(cap)
            try:
                rows = backend.fetch_executed_ids(None)
            finally:
                logging.getLogger().removeHandler(cap)

            self.assertEqual([cid for cid, _ in rows], [1])
            self.assertFalse(
                any("没有 executedAt" in m for m in cap.messages),
                f"数据正常时不应有告警：{cap.messages}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
