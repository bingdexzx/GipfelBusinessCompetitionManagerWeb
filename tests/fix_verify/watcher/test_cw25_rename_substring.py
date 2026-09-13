# -*- coding: utf-8 -*-
"""CW-25 验证：类型改名只能改自己那一个函数，不得用子串替换误伤别的 key。

缺陷（改前）：`rename_handler_key` 用 `line.replace(old_func, new_func)` 做**子串替换**。
当一个 key 的函数名把另一个 key 的函数名作为前缀时就出事：key `a` → `handle_a_passed`、
key `a_passed` → `handle_a_passed_passed`。把 `a` 改名为 `b` 时，第二个函数的 def 行也被改成
`handle_b_passed_passed`，而它的标注行仍是 `a_passed` ⇒ `load_handlers` 按标注行找不到函数，
**该 key 的处理逻辑静默失效**（退化为默认存档），日志里没有任何异常。

改后：只替换「`def <old_func>(`」这一处（正则 + 完整函数名 + count=1），其余文本不动。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw25_rename_substring.py
"""
from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import TempDir, load_watcher  # noqa: E402

TEMPLATE = (
    "# 合同类型处理函数文件（自动维护）。\n"
    "\n"
    "{marker_a}\n"
    "def handle_a_passed(contract: dict, ctx: dict) -> None:\n"
    "    ctx['marker'] = 'A'\n"
    "\n"
    "{marker_ap}\n"
    "def handle_a_passed_passed(contract: dict, ctx: dict) -> None:\n"
    "    ctx['marker'] = 'A_PASSED'\n"
)


class RenameSubstringTests(unittest.TestCase):
    def _write(self, mod):
        text = TEMPLATE.format(
            marker_a=mod.marker_line("a"), marker_ap=mod.marker_line("a_passed")
        )
        mod.HANDLERS_FILE.write_text(text, encoding="utf-8")
        return text

    def test_rename_does_not_touch_prefixed_sibling(self):
        with TempDir() as td:
            mod = load_watcher(td)
            self._write(mod)

            self.assertTrue(mod.rename_handler_key("a", "b"))
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")

            self.assertIn("def handle_b_passed(", text, "目标函数应改名")
            self.assertIn(
                "def handle_a_passed_passed(", text,
                "前缀同名的另一个函数**不得**被连带改名（改前会变成 handle_b_passed_passed）",
            )
            self.assertIn(mod.marker_line("a_passed"), text, "另一个 key 的标注行应保持不变")

    def test_registry_keeps_both_keys_after_rename(self):
        with TempDir() as td:
            mod = load_watcher(td)
            self._write(mod)
            mod.rename_handler_key("a", "b")
            registry = mod.load_handlers()

            self.assertIn("b", registry, "改名后的 key 应可加载")
            self.assertIn(
                "a_passed", registry,
                "另一个 key 的 handler 改名后仍必须可加载（改前因函数名被误改而静默失效）",
            )

    def test_docstring_mention_is_not_rewritten(self):
        """回归：函数体/注释里出现的函数名不应被替换成新名字。"""
        with TempDir() as td:
            mod = load_watcher(td)
            text = TEMPLATE.format(
                marker_a=mod.marker_line("a"), marker_ap=mod.marker_line("a_passed")
            ) + "    # 说明：handle_a_passed 由 a 类型使用\n"
            mod.HANDLERS_FILE.write_text(text, encoding="utf-8")
            mod.rename_handler_key("a", "b")
            new_text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertIn("# 说明：handle_a_passed 由 a 类型使用", new_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
