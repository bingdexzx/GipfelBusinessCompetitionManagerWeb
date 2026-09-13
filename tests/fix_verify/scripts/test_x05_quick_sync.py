# -*- coding: utf-8 -*-
"""X-05 验证：`quick-sync.sh` 不得直接 rsync 活库 `db.sqlite3`。

缺陷（改前）：`SYNC_ITEMS` 直接 rsync `backend/db.sqlite3`（没有 WAL/SHM、没有锁、也不停服）。
SQLite 正在被服务写入时，磁盘上的主库文件可能处于"半写"状态：目标端拿到的可能是缺页的文件，
打开时报 `database disk image is malformed`，或者静默丢掉最近的事务（回滚到旧快照）。
脚本却把这次传输报告为「同步完成」。

改后：
- push 方向：先用 SQLite 的 `VACUUM INTO` 做**一致性快照**（无需停服），校验快照后再推送；
- pull 方向：落盘后校验「非空 + SQLite 文件头 + `pragma integrity_check`」，失败即中止并明确
  提示"不要在此状态下启动后端（会新建空库）"；
- `.env`（含全部密钥）同步时强制 600。

本机没有可执行的 bash，故用**静态语义核对 + Python 等价行为复现**验证。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe -m unittest tests.fix_verify.scripts.test_x05_quick_sync -v
"""
from __future__ import annotations

import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "quick-sync.sh"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def _code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


class X05QuickSyncTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.code = "\n".join(_code_lines(self.text))

    def test_database_push_uses_snapshot(self):
        """push 数据库前必须做一致性快照（VACUUM INTO），不得直接发活库。"""
        self.assertIn("VACUUM INTO", self.code, "必须用 VACUUM INTO 生成一致性快照")
        self.assertRegex(
            self.code, r'snapshot_sqlite "\$src" "\$snap"',
            "push 分支必须对活库做快照",
        )
        # rsync 的参数跨行（`\` 续行），故这里只断言「推送参数里出现的是 $snap」且不含活库
        i = self.text.find('log_info "推送: $item（快照）"')
        self.assertGreater(i, 0, "push 数据库分支必须明确标注是推送快照")
        push_block = self.text[i: i + 400]
        self.assertIn('"$snap"', push_block, f"必须推送快照文件，实际 {push_block!r}")
        self.assertNotIn('"$src"', push_block, f"不得再推送活库 $src，实际 {push_block!r}")

    def test_snapshot_is_cleaned_up(self):
        """快照目录必须用 mktemp -d 并在退出时清理（含密钥/业务数据）。"""
        self.assertRegex(self.code, r'SNAP_DIR="\$\(mktemp -d')
        self.assertRegex(self.code, r"trap\s+cleanup_snapshot\s+EXIT")

    def test_database_is_validated_both_directions(self):
        """两侧都要校验：非空 + SQLite 文件头 + integrity_check。"""
        self.assertIn("SQLite format 3", self.code, "必须校验 SQLite 文件头")
        self.assertIn("integrity_check", self.code, "必须做 pragma integrity_check")
        self.assertRegex(
            self.code, r"check_sqlite_file \"\$src\" \|\|",
            "pull 分支落盘后必须校验数据库",
        )
        self.assertIn("请勿在此状态下启动后端", self.code, "校验失败必须给出明确风险提示")

    def test_env_forces_600(self):
        """`.env` 含全部密钥，必须强制 600（与 X-02 同类）。"""
        self.assertRegex(self.code, r"--chmod=F600")

    def test_vacuum_into_gives_consistent_snapshot_of_a_live_db(self):
        """等价行为复现：活库（有未 checkpoint 的 WAL 写入）经 VACUUM INTO 后，
        快照包含全部已提交数据，且 `integrity_check` 为 ok。"""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        base = TMP_ROOT / f"x05_{uuid.uuid4().hex[:8]}"
        base.mkdir(parents=True, exist_ok=True)
        live = base / "live.sqlite3"
        snap = base / "snap.sqlite3"
        try:
            con = sqlite3.connect(str(live))
            con.execute("pragma journal_mode=wal")     # 模拟线上（WAL 模式）
            con.execute("create table t (id integer primary key, v text)")
            con.executemany("insert into t (v) values (?)", [(f"row{i}",) for i in range(50)])
            con.commit()
            # 关键：**不关闭连接**（服务仍在运行）时就做快照
            con.execute("VACUUM INTO ?", (str(snap),))
            n_live = con.execute("select count(*) from t").fetchone()[0]
            con.close()

            self.assertEqual(n_live, 50)
            self.assertTrue(snap.exists(), "快照文件必须生成")
            with snap.open("rb") as fh:
                self.assertEqual(fh.read(15), b"SQLite format 3")
            snap_con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            try:
                self.assertEqual(snap_con.execute("pragma integrity_check").fetchone()[0], "ok")
                self.assertEqual(snap_con.execute("select count(*) from t").fetchone()[0], 50)
            finally:
                snap_con.close()
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_truncated_copy_would_fail_the_new_check(self):
        """等价行为复现：半写/截断的库在**新校验**下必然被判失败（改前会被当成成功）。"""
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        base = TMP_ROOT / f"x05b_{uuid.uuid4().hex[:8]}"
        base.mkdir(parents=True, exist_ok=True)
        good = base / "good.sqlite3"
        bad = base / "bad.sqlite3"
        try:
            con = sqlite3.connect(str(good))
            con.execute("create table t (id integer primary key)")
            con.executemany("insert into t default values", [() for _ in range(200)])
            con.commit()
            con.close()
            data = good.read_bytes()
            bad.write_bytes(data[: len(data) // 2])          # 截断一半

            self.assertEqual(self._check(good), "OK")
            self.assertNotEqual(self._check(bad), "OK")
            self.assertNotEqual(self._check(base / "missing.sqlite3"), "OK")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    @staticmethod
    def _check(path: Path) -> str:
        """复刻脚本 `check_sqlite_file` 的判定。"""
        if not path.exists() or path.stat().st_size == 0:
            return "EMPTY"
        with path.open("rb") as fh:
            if fh.read(15) != b"SQLite format 3":
                return "NOT_SQLITE"
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                row = con.execute("pragma integrity_check").fetchone()
            finally:
                con.close()
        except sqlite3.Error as exc:
            return f"OPEN_FAILED: {exc}"
        return "OK" if row and row[0] == "ok" else f"INTEGRITY: {row}"


if __name__ == "__main__":
    unittest.main(verbosity=2)
