# -*- coding: utf-8 -*-
"""CW-13 验证：进度文件必须原子写，损坏时必须留证并告警。

缺陷（改前）：
  - `save_state` 直接 `write_text`：写一半被中断（断电/被杀/磁盘满）会留下**截断的 JSON**；
  - 启动时 `except Exception: state = {}` **静默**把进度当空对象 → 水位、待处理队列、类型目录
    缓存一起丢失，而且没有任何日志，坏文件随后被下一轮覆盖，事后无法诊断。

改后：`save_state` 走「临时文件 + os.replace」原子替换并保留 .bak；启动时读取失败记 error 日志
并把坏文件改名为 `state.json.corrupt` 留证。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw13_state_atomic.py
"""
from __future__ import annotations

import json
import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import FakeBackend, LogCapture, StopLoop, TempDir, load_watcher, run_watcher  # noqa: E402


class StateAtomicTests(unittest.TestCase):
    def test_save_state_is_atomic_and_keeps_backup(self):
        with TempDir() as td:
            mod = load_watcher(td)
            mod.save_state({"lastExecutedAt": "T1"})
            mod.save_state({"lastExecutedAt": "T2"})

            self.assertEqual(
                json.loads(mod.STATE_FILE.read_text(encoding="utf-8"))["lastExecutedAt"], "T2"
            )
            self.assertFalse(
                mod.STATE_FILE.with_name(mod.STATE_FILE.name + ".tmp").exists(),
                "原子写不得残留 .tmp",
            )
            bak = mod.STATE_FILE.with_name(mod.STATE_FILE.name + ".bak")
            self.assertTrue(bak.exists(), "应保留 .bak 便于事后诊断")
            self.assertEqual(json.loads(bak.read_text(encoding="utf-8"))["lastExecutedAt"], "T1")

    def test_corrupted_state_is_reported_and_preserved(self):
        """损坏的 state.json：必须记 error 且把坏文件改名留证（改前静默当空对象）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            mod.STATE_FILE.write_text('{"lastExecutedAt": "T1"', encoding="utf-8")  # 截断的 JSON

            backend = FakeBackend([(1, "2026-01-01T00:00:00Z")])
            import logging

            cap = LogCapture()
            logging.getLogger().addHandler(cap)
            try:
                run_watcher(mod, backend, handler=lambda c, ctx: None, rounds=1)
            except StopLoop:
                pass
            finally:
                logging.getLogger().removeHandler(cap)

            self.assertTrue(
                any("进度文件损坏" in m for m in cap.messages),
                f"损坏时必须记 error 日志（改前静默）：{cap.messages}",
            )
            corrupt = mod.STATE_FILE.with_name(mod.STATE_FILE.name + ".corrupt")
            self.assertTrue(corrupt.exists(), "坏文件应改名留证，而不是被覆盖")
            self.assertTrue(corrupt.read_text(encoding="utf-8").startswith('{"lastExecutedAt"'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
