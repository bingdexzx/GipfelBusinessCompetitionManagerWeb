# -*- coding: utf-8 -*-
"""X-11 / X-12 验证：`.env` 必须保持「每个键唯一一行」，且编码容错。

- **X-11**（`deploy-linux.sh` / `update-from-github.sh`）：改前用
  `sed -i "s|^DJANGO_ALLOWED_HOSTS=.*|&,${AH_ENTRY}|"` 追加公网入口 —— `&` 代表**整个匹配文本**，
  探测到的公网 IP 变化时会反复追加（历史 IP 永久留在 Host 白名单里，等于扩大 Host 校验来源）；
  同名键多行时 `sed` 会同时改写多行，而 `os.environ` 只认**第一条**，脚本输出与实际生效值不一致。
- **X-12**（`gen_logviewer_key.py`）：改前写死 `encoding="utf-8"` 读取 ⇒ `.env` 是 GBK 时
  `UnicodeDecodeError` 冒泡（bootstrap 只看到 "failed to ensure …" 与裸 traceback）；
  带 UTF-8 BOM 时正则匹配不到 ⇒ 新键被**追加**成第二条，`settings.py` 读到前面那条空值 ⇒
  「bootstrap 成功但 8120 起不来」。

本机没有可执行的 bash，故用**静态语义核对 + Python 等价行为复现**验证。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe -m unittest tests.fix_verify.scripts.test_x11_x12_env_integrity -v
"""
from __future__ import annotations

import base64
import importlib.util
import io
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "scripts" / "deploy-linux.sh"
UPDATE = REPO / "scripts" / "update-from-github.sh"
COMMON = REPO / "scripts" / "lib" / "deploy-common.sh"
GEN_KEY = REPO / "scripts" / "gen_logviewer_key.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def _code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


class X11EnvIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.common = COMMON.read_text(encoding="utf-8")
        self.deploy_code = "\n".join(_code_lines(DEPLOY.read_text(encoding="utf-8")))
        self.update_code = "\n".join(_code_lines(UPDATE.read_text(encoding="utf-8")))

    def test_no_ampersand_append_sed(self):
        """改前的 `sed …|&,${…}|` 追加必须彻底消失（`&` 会反复吞整行）。"""
        for code, name in ((self.deploy_code, "deploy-linux.sh"), (self.update_code, "update-from-github.sh")):
            bad = [ln for ln in code.splitlines() if "DJANGO_ALLOWED_HOSTS=" in ln and "|&," in ln]
            self.assertEqual(bad, [], f"{name} 仍在用 `&` 追加：{bad}")

    def test_helpers_exist_and_are_used(self):
        self.assertIn("set_env_single()", self.common, "公共库必须提供 set_env_single")
        self.assertIn("append_env_entry()", self.common, "公共库必须提供 append_env_entry")
        for code, name in ((self.deploy_code, "deploy-linux.sh"), (self.update_code, "update-from-github.sh")):
            self.assertIn("append_env_entry", code, f"{name} 必须改用 append_env_entry")

    def test_helper_checks_uniqueness(self):
        """写入后必须回读断言「只剩一条」。"""
        self.assertRegex(
            self.common, r"grep -cE", "必须回读统计同名键条数",
        )
        self.assertRegex(self.common, r'!= "1"', "条数不为 1 时必须告警")

    # ---------- 等价行为复现 ----------

    def _write(self, base: Path, name: str, text: str) -> Path:
        p = base / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_sed_ampersand_would_duplicate_but_helper_does_not(self):
        """对照：旧写法会累积历史 IP；新 helper 保证唯一一行且去重。"""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        base = TMP_ROOT / f"x11_{uuid.uuid4().hex[:8]}"
        base.mkdir(parents=True, exist_ok=True)
        try:
            env = self._write(base, ".env", "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n")
            # 模拟改前语义：`&` = 整行匹配文本，直接拼在行尾
            legacy = env.read_text(encoding="utf-8").strip()
            for ip in ("1.2.3.4", "1.2.3.5", "1.2.3.6"):
                legacy = f"{legacy},{ip}"
            self.assertIn("1.2.3.4,1.2.3.5,1.2.3.6", legacy, "旧写法确实会累积历史 IP")

            # 新语义：去重合并 + 唯一一行
            for ip in ("1.2.3.4", "1.2.3.5", "1.2.3.4"):
                self._append_env_entry(env, ip)
            lines = [ln for ln in env.read_text(encoding="utf-8").splitlines()
                     if ln.startswith("DJANGO_ALLOWED_HOSTS=")]
            self.assertEqual(len(lines), 1, f"必须只有一行，实际 {lines}")
            value = lines[0].split("=", 1)[1]
            self.assertEqual(value.count("1.2.3.4"), 1, f"重复入口必须去重：{value}")
            self.assertIn("localhost", value, "原有条目必须保留")
            self.assertIn("1.2.3.5", value)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_duplicate_lines_are_collapsed(self):
        """同名键已有多行时，写入后必须只剩一条（os.environ 只认第一条）。"""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        base = TMP_ROOT / f"x11b_{uuid.uuid4().hex[:8]}"
        base.mkdir(parents=True, exist_ok=True)
        try:
            env = self._write(
                base, ".env",
                "DJANGO_ALLOWED_HOSTS=keep,localhost\nOTHER=1\nDJANGO_ALLOWED_HOSTS=stale2\n",
            )
            self._append_env_entry(env, "9.9.9.9")
            text = env.read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.startswith("DJANGO_ALLOWED_HOSTS=")]
            self.assertEqual(len(lines), 1, f"必须折叠为一行，实际 {lines}")
            self.assertNotIn("stale2", lines[0], f"后续重复行必须被丢弃：{lines[0]}")
            self.assertIn("9.9.9.9", lines[0])
            self.assertIn("OTHER=1", text, "其它键不得受影响")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    @staticmethod
    def _append_env_entry(env: Path, entry: str) -> str:
        """复刻 `append_env_entry` 的语义（去重 + 唯一行）。"""
        lines = env.read_text(encoding="utf-8").splitlines()
        cur = ""
        for ln in lines:
            if ln.startswith("DJANGO_ALLOWED_HOSTS="):
                cur = ln.split("=", 1)[1]
                break
        cur = cur or "localhost,127.0.0.1"
        out: list[str] = []
        for item in [x.strip() for x in cur.split(",") if x.strip()]:
            if item not in out:
                out.append(item)
        if entry not in out:
            out.append(entry)
        value = ",".join(out)
        kept = [ln for ln in lines if not ln.startswith("DJANGO_ALLOWED_HOSTS=")]
        kept.append(f"DJANGO_ALLOWED_HOSTS={value}")
        env.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return value


class X12GenKeyTests(unittest.TestCase):
    def _load(self):
        spec = importlib.util.spec_from_file_location("genkey_under_test", GEN_KEY)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["genkey_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def setUp(self):
        self.mod = self._load()
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.base = TMP_ROOT / f"x12_{uuid.uuid4().hex[:8]}"
        self.base.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _run(self, raw: bytes) -> tuple[int, str]:
        env = self.base / ".env"
        env.write_bytes(raw)
        self.mod.ENV_PATH = str(env)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            code = self.mod.main()
        finally:
            sys.stdout = old
        return code, buf.getvalue()

    def test_gbk_env_does_not_crash(self):
        """改前：GBK 文件 → UnicodeDecodeError 冒泡（bootstrap 只看到裸堆栈）。"""
        code, out = self._run("LOGVIEWER_SECRET_KEY=\n中文注释\n".encode("gbk"))
        self.assertEqual(code, 0, f"不得崩溃，输出：{out}")
        self.assertIn("non-valid UTF-8".replace("non-valid", "not valid"), out.replace("\n", " "))
        text = (self.base / ".env").read_text(encoding="utf-8")
        self.assertIn("LOGVIEWER_SECRET_KEY=", text)
        value = [ln for ln in text.splitlines() if ln.startswith("LOGVIEWER_SECRET_KEY=")][0]
        self.assertGreater(len(value.split("=", 1)[1]), 32, "必须生成强随机键")

    def test_bom_env_matches_existing_key(self):
        """改前：BOM 导致正则匹配不到 ⇒ 追加第二条键，读到的是前面那条空值。"""
        raw = ("\ufeff" + "LOGVIEWER_SECRET_KEY=" + "A" * 44 + "\n").encode("utf-8")
        code, out = self._run(raw)
        self.assertEqual(code, 0)
        self.assertIn("already set", out)
        text = (self.base / ".env").read_text(encoding="utf-8")
        keys = [ln for ln in text.splitlines() if "LOGVIEWER_SECRET_KEY=" in ln]
        self.assertEqual(len(keys), 1, f"不得出现两条同名键，实际 {keys}")

    def test_duplicate_keys_collapse_to_one(self):
        """已有两条（第一条为空、第二条弱值）时必须折叠为一条，且不再生成第二条。"""
        code, out = self._run(b"LOGVIEWER_SECRET_KEY=\nLOGVIEWER_SECRET_KEY=short\n")
        self.assertEqual(code, 0)
        keys = [ln for ln in (self.base / ".env").read_text(encoding="utf-8").splitlines()
                if ln.startswith("LOGVIEWER_SECRET_KEY=")]
        self.assertEqual(len(keys), 1, f"必须折叠为一条，实际 {keys}")
        self.assertEqual(keys[0], "LOGVIEWER_SECRET_KEY=short", "保留最后一条（与 settings 读取语义一致）")
        self.assertIn("collapsing to one", out, f"折叠动作必须可见：{out!r}")

    def test_empty_last_key_regenerates(self):
        """最后一条为空时必须生成强随机键（并保证只有一条）。"""
        code, _out = self._run(b"LOGVIEWER_SECRET_KEY=short\nLOGVIEWER_SECRET_KEY=\n")
        self.assertEqual(code, 0)
        keys = [ln for ln in (self.base / ".env").read_text(encoding="utf-8").splitlines()
                if ln.startswith("LOGVIEWER_SECRET_KEY=")]
        self.assertEqual(len(keys), 1, f"必须只有一条，实际 {keys}")
        self.assertGreater(len(keys[0].split("=", 1)[1]), 32, "必须重新生成强随机键")

    def test_weak_value_warns_but_keeps(self):
        """弱值不再被默默放过（改前 `x` 会被当成 already set 且无任何提示）。"""
        code, out = self._run(b"LOGVIEWER_SECRET_KEY=x\n")
        self.assertEqual(code, 0)
        self.assertIn("weak", out, f"应告警弱值，实际 {out!r}")
        self.assertIn("LOGVIEWER_SECRET_KEY=x", (self.base / ".env").read_text(encoding="utf-8"))

    def test_strong_value_is_kept_untouched(self):
        strong = base64.b64encode(b"z" * 32).decode("ascii")
        before = ("LOGVIEWER_SECRET_KEY=" + strong + "\n").encode("utf-8")
        code, out = self._run(before)
        self.assertEqual(code, 0)
        self.assertIn("already set", out)
        self.assertEqual((self.base / ".env").read_bytes(), before, "内容不得被改写")

    def test_missing_env_reports_clearly(self):
        self.mod.ENV_PATH = str(self.base / "nope.env")
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            code = self.mod.main()
        finally:
            sys.stdout = old
        self.assertEqual(code, 1)
        self.assertIn("[ERROR] missing", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
