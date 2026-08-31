"""
ASGI 入口：Django HTTP + python-socketio（与 HTTP 同源同端口）。

对应原 NestJS main.ts：NestFactory.create 同时托管 REST + Socket.IO。
"""
import os

import django
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from apps.realtime.gateway import sio, application as socketio_app  # noqa: E402

django_asgi = get_asgi_application()


class ASGIApp:
    """
    路由分发：
      - /socket.io/*  → python-socketio ASGI 应用
      - 其余           → Django ASGI（含 /api/*、/uploads/*、/static/*）

    保持 REST 与 WebSocket **复用同一端口、同源**，与原 NestJS 行为一致。
    """

    def __init__(self):
        self.django = django_asgi
        self.socketio = socketio_app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if path.startswith("/socket.io"):
            await self.socketio(scope, receive, send)
        else:
            await self.django(scope, receive, send)


application = ASGIApp()
