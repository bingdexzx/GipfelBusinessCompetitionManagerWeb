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

    def handle(self, *args, **options):
        bind = options["bind"]
        port = options["port"] or settings.PORT
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
