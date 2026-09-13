# -*- coding: utf-8 -*-
"""CW-23 验证：同一秒内重复处理不得静默覆盖上一份存档。

缺陷（改前）：默认存档的文件名是 `contract_<id>_<YYYYmmdd_HHMMSS>.json`（秒级时间戳）。
同一秒内处理同一份合同两次（正是 CW-03/CW-04 的重复路径，或同一秒内启动两次浸泡测试）
第二份会**静默覆盖**第一份 —— 重复处理不留任何痕迹，恰好把「重复记账」的现场掩盖掉，
而记录目录正是事后唯一能证明「同一合同被记了两次」的证据。

改后：目标文件已存在时自动加序号（`_2`、`_3`…），两次处理各留一份存档。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw23_archive_name_collision.py
"""
from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import TempDir, load_watcher  # noqa: E402

CONTRACT = {
    "id": 77,
    "competitionId": 1,
    "name": "CW23 合同",
    "status": "EXECUTED",
    "contractType": {"key": "cw23-type", "name": "CW23 类型"},
    "parties": [],
    "inputs": {"amount": "1"},
}


class ArchiveNameCollisionTests(unittest.TestCase):
    def test_second_dispatch_in_same_second_does_not_overwrite(self):
        with TempDir() as td:
            mod = load_watcher(td)
            out = td / "records_out"
            ctx = {"out_dir": str(out), "typeKey": "cw23-type"}

            first = mod.default_archive(dict(CONTRACT), ctx)
            second = mod.default_archive(dict(CONTRACT), ctx)

            self.assertNotEqual(
                first.name, second.name,
                f"同一秒内两次存档必须是两个文件（改前同名 → 第二份静默覆盖第一份）",
            )
            self.assertTrue(first.exists() and second.exists(), "两份存档都必须保留")
            self.assertEqual(
                len(list(first.parent.glob("contract_77_*.json"))), 2,
                "两次处理应各留一份存档，便于事后核对重复记账",
            )

    def test_first_archive_name_format_unchanged(self):
        """回归：首次存档仍沿用 `contract_<id>_<时间戳>.json` 形态。"""
        with TempDir() as td:
            mod = load_watcher(td)
            out = td / "records_out"
            f = mod.default_archive(dict(CONTRACT), {"out_dir": str(out), "typeKey": "cw23-type"})
            self.assertRegex(f.name, r"^contract_77_\d{8}_\d{6}\.json$")


if __name__ == "__main__":
    unittest.main(verbosity=2)

