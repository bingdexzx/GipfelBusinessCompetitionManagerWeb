# -*- coding: utf-8 -*-
"""CW-24 验证：合同类型的 key 不能决定文件落到输出根目录之外。

缺陷（改前）：`safe_dirname` 只替换 `\\/:*?"<>|`，于是 `..`（合同类型 key 的合法取值）被原样返回：
`default_archive` 会 `mkdir(parents=True)` 到 `out_dir/..` 并把存档写到**输出根目录之外**的
上一层目录 —— 「合同类型的 key」实际决定了文件落点，且记录目录是记账证据链的一部分。

改后：`.` / `..` / 纯空白 / 空串一律中性化为 `unknown`；正常 key（含带点的 `auto.chain`、
带斜杠的 `a/b`）行为不变。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw24_safe_dirname.py
"""
from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import TempDir, load_watcher  # noqa: E402


class SafeDirnameTests(unittest.TestCase):
    def test_dot_names_are_neutralised(self):
        with TempDir() as td:
            mod = load_watcher(td)
            for bad in ["..", ".", "...", "", "   "]:
                self.assertEqual(
                    mod.safe_dirname(bad), "unknown",
                    f"`{bad}` 必须中性化（改前会越出 out_dir 或退化为 out_dir 本身）",
                )
            # 带分隔符的写法：分隔符先被替换成 _，结果不再含路径成分（安全）
            self.assertEqual(mod.safe_dirname("../.."), ".._..")

    def test_normal_keys_unchanged(self):
        with TempDir() as td:
            mod = load_watcher(td)
            self.assertEqual(mod.safe_dirname("auto.chain"), "auto.chain")
            self.assertEqual(mod.safe_dirname("material-procurement"), "material-procurement")
            self.assertEqual(mod.safe_dirname("a/b"), "a_b")
            self.assertEqual(mod.safe_dirname("a:b*c"), "a_b_c")

    def test_default_archive_stays_inside_out_dir(self):
        """端到端：typeKey 为 `..` 时存档必须落在 out_dir 之内。"""
        with TempDir() as td:
            mod = load_watcher(td)
            out = td / "records_out"
            contract = {
                "id": 88, "competitionId": 1, "name": "CW24", "status": "EXECUTED",
                "contractType": {"key": "..", "name": "穿越类型"},
                "parties": [], "inputs": {},
            }
            f = mod.default_archive(contract, {"out_dir": str(out), "typeKey": ".."})

            self.assertTrue(
                str(f.resolve()).startswith(str(out.resolve())),
                f"存档不得越出输出根目录：{f}（改前会写到 {out.parent}）",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
