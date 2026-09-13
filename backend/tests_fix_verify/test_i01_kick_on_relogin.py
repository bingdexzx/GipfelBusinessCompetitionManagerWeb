# -*- coding: utf-8 -*-
"""I-01 验证：顶号（再次登录）必须**真正断开**旧设备的 Socket.IO 连接。

缺陷（改前）：`auth/views.py::LoginView` 顶号时只调用
`emit_to_users([user.id], "auth:required", ...)` —— 仅广播一条通知，
**从不断开**旧连接。旧设备（或恶意客户端）只要不理会该事件，就仍然是
`user-{id}` / `comp-{id}` 房间成员，继续收到 `resource:changed`、`message:new`
（含消息正文）等实时事件；HTTP 侧虽已因 token_version 失效被拦，但实时数据一直在漏。

改后：登录顶号走 `kick_user_sessions()` —— 先发 auth:required（前端据此清登录态），
再对房间内每个 sid 执行 `sio.disconnect()`。

本用例用一个真实运行的事件循环线程 + 假 sio，端到端验证「登录一次 → 旧会话被断开」。
"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest import mock

from django.test import Client, TestCase

from apps.realtime import emit as emit_mod
from apps.users.models import User


class _FakeSio:
    def __init__(self, sids):
        self.emitted: list[tuple[str, dict, str | None]] = []
        self.disconnected: list[str] = []
        self.manager = mock.Mock()
        self.manager.get_participants = lambda namespace, room: iter(
            [(sid, f"eio-{sid}") for sid in sids]
        )

    async def emit(self, event, data=None, room=None):
        self.emitted.append((event, data, room))

    async def disconnect(self, sid, namespace=None, ignore_queue=False):
        self.disconnected.append(sid)


class _LoopThread:
    """在后台线程跑一个真实 asyncio loop，供同步侧 run_coroutine_threadsafe 投递。"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        deadline = time.time() + 2
        while not self.loop.is_running() and time.time() < deadline:
            time.sleep(0.005)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


class KickOnReloginTests(TestCase):
    def setUp(self):
        self.user = User(username="i01-user", role="PLAYER", is_active=True)
        self.user.set_password("Passw0rd!x")
        self.user.save()
        self.client = Client()

    def _login(self):
        return self.client.post(
            "/api/auth/login",
            data={"username": "i01-user", "password": "Passw0rd!x"},
            content_type="application/json",
        )

    # ---------- 缺陷场景 ----------
    def test_relogin_disconnects_previous_sessions(self):
        fake = _FakeSio(["old-sid-1", "old-sid-2"])
        loop = _LoopThread()
        old_loop = emit_mod._loop
        emit_mod._loop = None  # 让 register_loop 接受测试 loop
        emit_mod.register_loop(loop.loop)
        try:
            with mock.patch("apps.realtime.gateway.sio", fake):
                resp = self._login()
                self.assertEqual(resp.status_code, 200, resp.content)
                # 踢人是「投递即返回」，等一小会儿让它执行完
                deadline = time.time() + 3
                while not fake.disconnected and time.time() < deadline:
                    time.sleep(0.02)
        finally:
            emit_mod._loop = old_loop
            loop.close()

        self.assertEqual(
            sorted(fake.disconnected),
            ["old-sid-1", "old-sid-2"],
            "顶号必须断开旧会话（改前只发通知、不断开）",
        )
        # 通知仍然要发：前端靠 auth:required 清登录态并跳登录页
        self.assertTrue(
            any(e[0] == "auth:required" for e in fake.emitted),
            "顶号仍需下发 auth:required 通知",
        )
        self.assertTrue(
            any(e[2] == f"user-{self.user.pk}" for e in fake.emitted),
            "通知与断开都必须针对该用户房间",
        )

    # ---------- 功能不变 ----------
    def test_relogin_still_returns_token_and_bumps_version(self):
        before = self.user.token_version
        resp = self._login()
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()["data"]
        self.assertTrue(body.get("token"))
        self.assertEqual(body["user"]["username"], "i01-user")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, before + 1, "顶号仍须递增 token_version")

    def test_login_without_realtime_loop_still_succeeds(self):
        """无 ASGI loop（未连过 socket 的部署形态）时，登录必须照常成功。"""
        old_loop = emit_mod._loop
        emit_mod._loop = None
        try:
            resp = self._login()
        finally:
            emit_mod._loop = old_loop
        self.assertEqual(resp.status_code, 200, resp.content)
