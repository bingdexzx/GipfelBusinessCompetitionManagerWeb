"""X-23 回归：gipfel.service 不再监听没人用的 daphne Unix socket，且 X-13 的收权仍在。

改前状态（`deploy/gipfel.service`）：
    ExecStart=…/daphne \\
        -u /run/gipfel/gipfel.sock \\      ← 全仓库没有任何消费方
        -b 127.0.0.1 \\
        -p 8000 \\
    RuntimeDirectoryMode=0755             ← 运行目录对同机任意用户可遍历
    （无 UMask）

daphne 对 Unix socket **不校验对端 UID**：同机任意用户只要能进入 `/run/gipfel` 就能绕过
nginx 直连后端，而且因为来源被判为回环，还能自造 `X-Real-IP` 绕过按 IP 的登录限速。
`deploy/nginx-gipfel.conf` 走的是 `127.0.0.1:8000`，脚本/测试/文档里也没有引用该 socket。

改后：
  * `-u /run/gipfel/gipfel.sock` 已从 ExecStart 移除（nginx 反代路径不变）；
  * X-13 的纵深防御保留：`RuntimeDirectoryMode=0750`、`LogsDirectoryMode=0750`、`UMask=0027`。

运行：backend/.venv/Scripts/python.exe tests/fix_verify/scripts/test_x23_daphne_socket.py
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GIPFEL_UNIT = REPO / "deploy" / "gipfel.service"
NGINX = REPO / "deploy" / "nginx-gipfel.conf"

# 允许出现 "gipfel.sock" 字样的地方：说明性注释 + 审计报告 +
# 回归用例自身（X-13 的用例会断言 nginx 不用这个 socket，用例里必须写出这个名字）
_SELF = {Path(__file__).name, "test_x13_x14_units_diag.py"}
_SKIP_PARTS = {"node_modules", ".tmp", ".venv", "dist", ".git", "__pycache__"}


def _strip_comments(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", ";", "REM", "//"))
    )


class X23SocketRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = GIPFEL_UNIT.read_bytes().decode("utf-8")
        cls.code = _strip_comments(cls.raw)

    def test_execstart_no_longer_listens_on_unix_socket(self):
        execstart = self.code.split("ExecStart=", 1)[1].split("\n\n", 1)[0]
        self.assertNotRegex(execstart, r"(?m)^\s*-u\s", "ExecStart 仍在监听 Unix socket")
        self.assertNotIn("gipfel.sock", execstart)

    def test_still_binds_loopback_http(self):
        self.assertIn("-b 127.0.0.1", self.code)
        self.assertIn("-p 8000", self.code)
        self.assertIn("backend.asgi:application", self.code)

    def test_x13_hardening_still_present(self):
        self.assertIn("RuntimeDirectory=gipfel", self.code)
        self.assertIn("RuntimeDirectoryMode=0750", self.code)
        self.assertIn("LogsDirectoryMode=0750", self.code)
        self.assertIn("UMask=0027", self.code)

    def test_address_families_keep_ip(self):
        m = re.search(r"RestrictAddressFamilies=(.*)", self.code)
        self.assertIsNotNone(m)
        fams = m.group(1).split()
        for need in ("AF_INET", "AF_INET6"):
            self.assertIn(need, fams, f"RestrictAddressFamilies 缺少 {need}")

    def test_nginx_does_not_use_the_socket(self):
        nginx = NGINX.read_bytes().decode("utf-8", errors="replace")
        self.assertNotIn("gipfel.sock", nginx)
        self.assertIn("127.0.0.1:8000", nginx)


class X23NoConsumerTests(unittest.TestCase):
    """确认整个仓库里没有别的东西依赖这个 socket（否则删掉会打断它）。"""

    SCAN_DIRS = ("scripts", "tests", "backend", "frontend", "deploy", "docs")
    SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".xlsx", ".ico", ".woff", ".woff2"}

    def test_no_other_reference(self):
        hits: list[str] = []
        for d in self.SCAN_DIRS:
            root = REPO / d
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix.lower() in self.SKIP_SUFFIX:
                    continue
                if p.name in _SELF or p == GIPFEL_UNIT:
                    continue
                if _SKIP_PARTS & set(p.parts):
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "gipfel.sock" in text:
                    hits.append(str(p.relative_to(REPO)))
        self.assertEqual(hits, [], f"仍有文件引用 gipfel.sock：{hits}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
