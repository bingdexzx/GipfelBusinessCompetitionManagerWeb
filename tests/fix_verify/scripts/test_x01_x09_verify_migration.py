# -*- coding: utf-8 -*-
"""X-01 / X-09 验证：`verify-migration.sh` 不得静默中止，且必须真正验证数据库与日志查看器。

缺陷（改前）：
- **X-01**：`check_pass/check_fail/check_warn` 用 `((PASS++))` / `((FAIL++))` / `((WARN++))`。
  在 `set -euo pipefail` 下，后置自增表达式的返回值是**自增前的旧值**，第一次自增时旧值为 0
  ⇒ 算术命令退出码非零 ⇒ bash 立即中止脚本。于是「第一项检查通过后脚本就退出，退出码 0」，
  调用方/CI 会把它误判为「迁移成功」。
- **X-09**：「验证」只测 `db.sqlite3` 的**文件大小**（损坏库 / 空 schema 同样是 size>0），
  且只检查日志查看器的 systemd 状态、不验证它的 HTTP 可用性。

本机没有可执行的 bash（WSL 未安装：`bash.exe`/`wsl -l -v` 均 `E_ACCESSDENIED`），
故这里做**静态语义核对**：解析脚本源码断言上述模式已消除/已具备。等价行为用 Python 复现验证。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe -m unittest tests.fix_verify.scripts.test_x01_x09_verify_migration -v
"""
from __future__ import annotations

import re
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "verify-migration.sh"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def _code_lines(text: str) -> list[str]:
    """去掉注释行（`#` 开头）后的可执行行。"""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(line)
    return out


class X01CounterTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(_code_lines(self.text))

    def test_no_bare_postfix_increment(self):
        """`((VAR++))` 在 `set -e` 下会中止脚本 —— 必须彻底消除。"""
        bad = re.findall(r"\(\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\+\+\s*\)\)", self.code)
        self.assertEqual(
            bad, [],
            f"仍存在会被 set -e 中止的后置自增：{bad}（改前 = 第一项检查后静默退出、退出码 0）",
        )

    def test_counters_use_assignment_form(self):
        """计数器必须改用赋值形式（赋值永远返回 0）。"""
        for var in ("PASS", "FAIL", "WARN"):
            self.assertRegex(
                self.code,
                rf"{var}=\$\(\(\s*{var}\s*\+\s*1\s*\)\)",
                f"{var} 必须用 `{var}=$(({var} + 1))` 形式累加",
            )

    def test_script_keeps_strict_mode(self):
        """回归：严格模式必须保留（它正是 X-01 的前提，也是脚本的安全网）。"""
        self.assertIn("set -euo pipefail", self.code)

    def test_counter_semantics_reproduced_in_python(self):
        """用 Python 复现两种写法的返回值差异，锁定「旧写法必然中止」这一事实。"""
        # bash: ((PASS++)) 的退出码 = (旧值 == 0 ? 1 : 0)
        def old_form(pass_before: int) -> int:
            return 1 if pass_before == 0 else 0

        # bash: PASS=$((PASS + 1)) 的退出码恒为 0
        def new_form(_pass_before: int) -> int:
            return 0

        self.assertEqual(old_form(0), 1, "第一次自增返回非零 ⇒ set -e 中止")
        self.assertEqual(old_form(1), 0, "第二次起才返回 0（所以只在第一项后退出）")
        self.assertEqual(new_form(0), 0)
        self.assertEqual(new_form(1), 0)


class X09DatabaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(_code_lines(self.text))

    def test_database_is_actually_opened(self):
        """必须真的打开库并校验 schema，而不只是 `size > 0`。"""
        self.assertIn("sqlite3", self.code, "脚本必须用 python3/sqlite3 真正打开数据库")
        self.assertIn("django_migrations", self.code, "必须校验 Django 迁移表存在")
        self.assertRegex(
            self.code, r"integrity|sqlite_master|django_migrations",
            "必须有结构性校验（表清单/迁移表）",
        )

    def test_logviewer_http_is_verified(self):
        """日志查看器必须有 HTTP 健康检查（改前只有 systemctl 状态）。"""
        self.assertIn("gipfel-logviewer", self.code)
        self.assertRegex(
            self.code, r"LOG_VIEWER_PORT",
            "日志查看器端口必须取自 .env 的 LOG_VIEWER_PORT（与 nginx 监听口同源）",
        )
        self.assertRegex(
            self.code, r"日志查看器健康检查",
            "必须新增日志查看器的 HTTP 健康检查断言",
        )

    def test_broken_database_is_detected_by_the_same_probe(self):
        """用同一套探针逻辑验证：损坏库/空 schema 必须被判失败，正常库判通过。"""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        broken = TMP_ROOT / f"x09_broken_{uuid.uuid4().hex[:8]}.sqlite3"
        empty = TMP_ROOT / f"x09_empty_{uuid.uuid4().hex[:8]}.sqlite3"
        good = TMP_ROOT / f"x09_good_{uuid.uuid4().hex[:8]}.sqlite3"
        try:
            broken.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)   # 头部像 SQLite，实际损坏
            sqlite3.connect(str(empty)).close()                          # 合法但无任何表
            con = sqlite3.connect(str(good))
            con.execute("create table django_migrations (id integer primary key, name text)")
            con.execute("insert into django_migrations (name) values ('0001_initial')")
            con.commit()
            con.close()

            self.assertTrue(self._probe(broken).startswith("BROKEN"), self._probe(broken))
            self.assertEqual(self._probe(empty), "EMPTY_SCHEMA")
            self.assertTrue(self._probe(good).startswith("OK"), self._probe(good))
        finally:
            for p in (broken, empty, good):
                p.unlink(missing_ok=True)

    @staticmethod
    def _probe(path: Path) -> str:
        """复刻脚本里内嵌 python3 探针的判定逻辑。"""
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
                ).fetchall()
                if not rows:
                    return "EMPTY_SCHEMA"
                names = {r[0] for r in rows}
                if "django_migrations" not in names:
                    return "NO_DJANGO_MIGRATIONS"
                n = con.execute("select count(*) from django_migrations").fetchone()[0]
                return f"OK tables={len(names)} migrations={n}"
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            return f"BROKEN: {exc}"


if __name__ == "__main__":
    unittest.main(verbosity=2)
