"""以 .env 的 PORT 为监听端口启动 daphne（ASGI 服务器，承载 HTTP + Socket.IO）。

用法：
    python manage.py rundaphne                # 绑定 127.0.0.1:${PORT}（PORT 来自 .env，默认 8000）
    python manage.py rundaphne --bind 0.0.0.0  # 监听所有网卡（局域网/容器访问）
    python manage.py rundaphne --port 9000     # 临时覆盖端口

.env 的 PORT 是后端端口的单一真源：本命令据此绑定，/api/version 也把它下发给前端，
因此改端口只需改 .env PORT 并重启，前端「后端管理」跳转按钮自动跟随。
"""
from __future__ import annotations

import os
import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "以 settings.PORT（来自 .env 的 PORT）为监听端口启动 daphne"

    def add_arguments(self, parser):
        parser.add_argument(
            "--bind",
            default="127.0.0.1",
            help="绑定地址（默认 127.0.0.1，仅本机/经 nginx 反代可达；"
            "生产务必用 127.0.0.1 并置于 nginx 之后，仅在局域网/容器内联调时临时用 0.0.0.0）",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=None,
            help="临时覆盖端口（默认用 settings.PORT，即 .env 的 PORT）",
        )

    @staticmethod
    def _port_in_use(bind: str, port: int) -> bool:
        """探测端口是否已有服务在监听。

        用「连接探测」而不是「bind 探测」：SO_REUSEADDR 会让通配地址与具体地址
        之间的占用关系变得不可靠，而能否连上则精确反映「已经有人在服务」。
        通配地址（0.0.0.0/::）统一按回环连接判断——无论占用方绑的是通配还是回环，
        从 127.0.0.1 都能连上，两个方向都能覆盖。
        """
        import socket

        host = "127.0.0.1" if bind in ("0.0.0.0", "::", "") else bind
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        probe = socket.socket(family, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect((host, port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def handle(self, *args, **options):
        bind = options["bind"]
        port = options["port"] or settings.PORT

        # 快速失败：端口被占用时 daphne 只打印一行 "Address already in use"；
        # 若由 systemd/supervisor 托管，就变成无限重启，真实原因极难看出。
        # 这里提前探测并直接说明「谁最可能占着它、该怎么办」。
        if self._port_in_use(bind, port):
            self.stderr.write(
                self.style.ERROR(
                    f"端口 {port} 已被占用，无法绑定 {bind}:{port}。\n"
                    "最常见的原因：systemd 的 gipfel.service 已在运行（它绑 127.0.0.1:8000）。\n"
                    f"  · 查看占用者：  sudo ss -lntp | grep ':{port}'\n"
                    "  · 查看服务状态：sudo systemctl status gipfel --no-pager\n"
                    "  · 仅本地调试：  python manage.py rundaphne --port 9000\n"
                    "  · 或先停服务：  sudo systemctl stop gipfel"
                )
            )
            sys.exit(1)

        # 把实际绑定端口写入环境变量，使 daphne 子进程导入 settings 时读到该值，
        # 从而 /api/version 下发的 port 与真实监听端口一致（即使通过 --port 覆盖也成立）。
        os.environ["PORT"] = str(port)
        self.stdout.write(
            self.style.SUCCESS(
                f"启动 daphne：绑定 {bind}:{port}（PORT 取自 .env = {settings.PORT}）"
            )
        )
        # 直接以子进程方式启动 daphne，复用当前解释器与环境变量（含 .env 已加载的 DJANGO_SETTINGS_MODULE）
        subprocess.run(
            [
                sys.executable,
                "-m",
                "daphne",
                "-b",
                bind,
                "-p",
                str(port),
                "backend.asgi:application",
            ]
        )
