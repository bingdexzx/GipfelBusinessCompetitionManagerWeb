"""WSGI 入口（仅同步 HTTP，WebSocket 由 ASGI 处理；生产用 daphne）。"""
import os

from django.core.wsgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
application = get_asgi_application()
