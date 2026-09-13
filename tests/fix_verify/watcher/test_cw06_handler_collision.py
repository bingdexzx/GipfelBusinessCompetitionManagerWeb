# -*- coding: utf-8 -*-
"""CW-06 验证：自动生成的默认函数不得屏蔽用户自定义 handler。

改前 `upsert_handler_for_key` 只检查「标注行是否存在」：用户按 handlers.py 顶部说明删掉标注块、
自己写 `handle_<key>_passed` 后，标注行消失 → 下一轮 sync_catalog 会在文件**末尾**追加一个同名
默认函数 → Python 后者生效 ⇒ 用户实现被静默屏蔽（日志仍显示「已按类型处理」）。
另外两个 key 的 slug 相同时也会生成同名 def（互相覆盖），且改前不做任何告警。

跑的是真实 contract_watcher.py（进程内加载，handlers.py 路径重定向到仓库内临时目录）。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw06_handler_collision.py
"""
from __future__ import annotations

import importlib.util
import logging
import shutil
import unittest
import uuid
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

REPO = Path(__file__).resolve().parents[3]
WATCHER_PY = REPO / "contract_watcher" / "contract_watcher.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"

sys_path_inserted = False
import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cw01_cw02 import LogCapture  # noqa: E402


def load_watcher(td: Path):
    spec = importlib.util.spec_from_file_location("cw06_under_test", WATCHER_PY)
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


USER_HANDLER = (
    "# 合同类型处理函数文件（由 contract_watcher.py 自动维护）。\n"
    "\n"
    "def handle_demo_passed(contract: dict, ctx: dict) -> None:\n"
    '    """用户自己写的实现（删掉了自动生成的标注块）。"""\n'
    '    ctx["out_dir"].joinpath("user-ran.txt").write_text(str(contract["id"]), encoding="utf-8")\n'
)


def capture_logs():
    cap = LogCapture()
    logging.getLogger().addHandler(cap)
    return cap


class Cw06Tests(unittest.TestCase):
    def test_user_handler_is_not_shadowed_by_generated_default(self):
        """用户删掉标注块自己实现后：不得再追加同名默认块（改前追加 → 用户代码失效）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text(USER_HANDLER, encoding="utf-8")
            cap = capture_logs()
            added = mod.upsert_handler_for_key("demo")
            logging.getLogger().removeHandler(cap)

            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertFalse(added, "同名函数已存在时不得新增自动块")
            self.assertEqual(
                text.count("def handle_demo_passed("), 1,
                "不得出现第二个同名 def（后者会屏蔽用户实现）",
            )
            self.assertNotIn("[auto-default]", text, "不得追加自动生成的默认函数体")
            self.assertTrue(any("同名函数" in m for m in cap.messages), f"应有告警，实际 {cap.messages}")

    def test_loaded_registry_points_to_user_implementation(self):
        """注册表必须指向用户实现（改前指向文件末尾自动生成的默认函数）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text(USER_HANDLER, encoding="utf-8")
            mod.upsert_handler_for_key("demo")
            registry = mod.load_handlers()
            self.assertIn("demo", registry)
            out_dir = td / "records_out"
            out_dir.mkdir(exist_ok=True)
            registry["demo"]({"id": 42, "contractType": {"key": "demo"}}, {"out_dir": out_dir})
            self.assertTrue(
                (out_dir / "user-ran.txt").exists(),
                "用户实现必须真正被执行（改前被自动生成的默认函数屏蔽）",
            )

    def test_slug_collision_does_not_generate_second_def(self):
        """两个 key 的 slug 相同：不得再生成同名 def，且必须告警。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
            mod.upsert_handler_for_key("material-procurement")  # → handle_material_procurement_passed
            cap = capture_logs()
            added = mod.upsert_handler_for_key("material_procurement")
            logging.getLogger().removeHandler(cap)
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertFalse(added, "slug 冲突时不得生成第二个同名 def")
            self.assertEqual(text.count("def handle_material_procurement_passed("), 1)
            self.assertTrue(any("同名函数" in m for m in cap.messages), f"应有告警，实际 {cap.messages}")

    def test_loader_warns_about_slug_collision(self):
        """加载时发现两个 key 映射到同一函数名 → 必须告警（改前一条告警都没有）。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text(
                "# 空模板\n"
                "\n"
                "# ===== [auto] ContractType.key = material-procurement =====\n"
                "def handle_material_procurement_passed(contract: dict, ctx: dict) -> None:\n"
                "    pass\n"
                "\n"
                "# ===== [auto] ContractType.key = material_procurement =====\n"
                "def handle_material_procurement_passed(contract: dict, ctx: dict) -> None:\n"
                "    pass\n",
                encoding="utf-8",
            )
            cap = capture_logs()
            mod.load_handlers()
            logging.getLogger().removeHandler(cap)
            self.assertTrue(
                any("函数名冲突" in m for m in cap.messages),
                f"slug 冲突必须告警，实际日志 {cap.messages}",
            )

    def test_normal_key_still_generates_default_section(self):
        """回归：没有同名函数时仍正常生成默认块，并能被加载为注册表项。"""
        with TempDir() as td:
            mod = load_watcher(td)
            mod.HANDLERS_FILE.write_text("# 空模板\n", encoding="utf-8")
            self.assertTrue(mod.upsert_handler_for_key("brand-new"))
            text = mod.HANDLERS_FILE.read_text(encoding="utf-8")
            self.assertIn("[auto-default]", text)
            self.assertEqual(text.count("def handle_brand_new_passed("), 1)
            self.assertIn("brand-new", mod.load_handlers())


if __name__ == "__main__":
    unittest.main(verbosity=2)
