# -*- coding: utf-8 -*-
"""CW-07 验证：自动生成的 handlers.py 代码必须安全且可自愈。

改前 `build_default_section(key)` 把 key 直接内插进标注行（python 注释）与 docstring：
  - key 含 `\"` → docstring 提前终止 → SyntaxError；
  - key 含换行 → 标注行被拆成两行 + docstring 断行 → SyntaxError，且 MARKER_RE 再也匹配不到，
    下一轮又会追加一次；
  - 生成后不校验、不备份、非原子写 → 文件被写成坏文件且不会自愈，load_handlers 返回 {}，
    所有合同类型一起退化为「只存档不记账」，用户自己写的代码永远不可达。
后端对 ContractType.key 只校验非空 + 长度（serializers.py），因此这些 key 是可达的。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw07_generated_code_safety.py
"""
from __future__ import annotations

import importlib.util
import logging
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
from test_cw01_cw02 import LogCapture  # noqa: E402


def load_watcher(td: Path):
    spec = importlib.util.spec_from_file_location("cw07_under_test", WATCHER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.WATCHER_DIR = td
    mod.HANDLERS_FILE = td / "handlers.py"
    mod.STATE_FILE = td / "data" / "state.json"
    mod.LOG_FILE = td / "watcher.log"
    mod.RECORDS_DIR = td / "records"
    (td / "data").mkdir(parents=True, exist_ok=True)
    return mod


class TempDir:
    def __enter__(self):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TMP_ROOT / f"cw_{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def capture_logs():
    cap = LogCapture()
    logging.getLogger().addHandler(cap)
    return cap


class Cw07GeneratedCodeTests(unittest.TestCase):
    def test_section_with_quotes_in_key_compiles(self):
        """key 含 \" 时生成的代码必须可编译（改前 SyntaxError）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            section = mod.build_default_section('bad"""key')
            compile(section, "handlers.py", "exec")  # 改前抛 SyntaxError

    def test_section_with_newline_in_key_stays_single_marker_line(self):
        """key 含换行：标注行必须仍是单行（否则 MARKER_RE 失配 → 每轮重复追加）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            section = mod.build_default_section("nl\nkey")
            compile(section, "handlers.py", "exec")
            marker_lines = [ln for ln in section.split("\n") if ln.startswith(mod.MARKER_PREFIX)]
            self.assertEqual(len(marker_lines), 1, f"标注行必须只有一行，实际 {marker_lines}")
            self.assertEqual(
                len(mod.MARKER_RE.findall(section)), 1,
                "MARKER_RE 必须能匹配到这条标注行",
            )

    def test_exotic_keys_round_trip_through_marker(self):
        """标注行转义后，load_handlers 必须还原出后端原始 key。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
            for key in ['bad"""key', "nl\nkey", "back\\slash", "普通中文key"]:
                self.assertTrue(mod.upsert_handler_for_key(key), f"应生成 {key!r} 的默认块")
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            compile(text, "handlers.py", "exec")  # 文件必须始终可编译
            reg = mod.load_handlers()
            for key in ['bad"""key', "nl\nkey", "back\\slash", "普通中文key"]:
                self.assertIn(key, reg, f"注册表应包含原始 key {key!r}，实际 {list(reg)}")

    def test_exotic_key_is_not_appended_twice(self):
        """幂等：同一（怪异）key 第二次调用不得重复追加（改前因标记行断行而每轮追加）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
            self.assertTrue(mod.upsert_handler_for_key("nl\nkey"))
            self.assertFalse(mod.upsert_handler_for_key("nl\nkey"), "第二次不得再追加")
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertEqual(text.count("key = nl\\nkey ====="), 1)

    def test_broken_generation_does_not_touch_file(self):
        """生成结果无法编译时必须放弃写入（改前直接 write_text 把文件写坏）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            broken = "def broken(:\n    pass\n"
            mod.HANDLERS_FILE.write_text(broken, encoding="utf-8")
            cap = capture_logs()
            ok = mod.upsert_handler_for_key("some-key")  # 追加到已损坏文件 → 仍不可编译
            logging.getLogger().removeHandler(cap)
            self.assertFalse(ok, "不可编译的结果不得写入")
            self.assertEqual(
                mod.HANDLERS_FILE.read_text(encoding="utf-8"), broken,
                "原文件必须保持不变",
            )
            self.assertTrue(any("语法校验" in m for m in cap.messages), f"应有错误日志，实际 {cap.messages}")

    def test_write_is_backed_up(self):
        """写入前保留 .bak，且不残留 .tmp（原子写）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            original = "# 空模板\n"
            mod.HANDLERS_FILE.write_text(original, encoding="utf-8")
            self.assertTrue(mod.upsert_handler_for_key("some-key"))
            bak = mod.HANDLERS_FILE.with_name("handlers.py.bak")
            self.assertTrue(bak.exists(), "应保留 handlers.py.bak")
            self.assertEqual(bak.read_text(encoding="utf-8"), original)
            self.assertFalse(
                mod.HANDLERS_FILE.with_name("handlers.py.tmp").exists(), "不得残留 .tmp"
            )

    def test_rename_still_works_with_escaping(self):
        """回归：改名仍更新标注行与函数名、保留函数体。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
            mod.upsert_handler_for_key("material-procurement")
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8").replace(
                '    ctx["default_archive"](contract, ctx)',
                '    ctx["default_archive"](contract, ctx)\n    # USER_CUSTOM',
            )
            mod.HANDLERS_FILE.write_text(text, encoding="utf-8")
            self.assertTrue(mod.rename_handler_key("material-procurement", "material-procurement-v2"))
            t2 = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertIn("ContractType.key = material-procurement-v2 =====", t2)
            self.assertIn("def handle_material_procurement_v2_passed(", t2)
            self.assertIn("USER_CUSTOM", t2)
            reg = mod.load_handlers()
            self.assertIn("material-procurement-v2", reg)

    def test_normal_key_generation_regression(self):
        """回归：普通 key 仍正常生成默认块。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
            self.assertTrue(mod.upsert_handler_for_key("brand-new"))
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertIn("[auto-default]", text)
            self.assertIn("ContractType.key = brand-new =====", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
