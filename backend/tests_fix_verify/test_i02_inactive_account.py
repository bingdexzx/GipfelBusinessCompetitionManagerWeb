# -*- coding: utf-8 -*-
"""I-02 验证：账号被禁用后，已签发的 JWT 与 WebSocket 连接必须立即失效。

缺陷（改前）：
- `apps/auth/authentication.py::JWTAuthentication.authenticate()` 只校验
  `token_version` 与「强制改密」，**从不校验 `is_active`**（唯一的检查在
  `auth/views.py:153` 的登录流程里）；
- `apps/realtime/gateway.py::_resolve_user()` 同样不校验 `is_active`；
- 而 `PATCH /api/users/:id {"isActive": false}` 也不递增 `token_version`。
→ 管理员禁用账号后，该账号仍可继续用旧 token 调用全部接口、并保持 WebSocket
在线（JWT 默认 24h，socket 无限期），直到 token 自然过期。

改后：HTTP 认证与 Socket.IO 握手都校验 `is_active`，禁用立即生效。
"""
from __future__ import annotations

from asgiref.sync import async_to_sync
from django.test import Client, TestCase

from apps.auth.authentication import create_jwt
from apps.realtime import gateway
from apps.users.models import User


class InactiveAccountTests(TestCase):
    def setUp(self):
        self.user = User(username="i02-user", role="PLAYER", is_active=True)
        self.user.set_password("Passw0rd!x")
        self.user.save()
        self.client = Client()

    def _me(self, token: str):
        return self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")

    # ---------- 缺陷场景 ----------
    def test_disabled_account_token_is_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        token = create_jwt(self.user)  # 禁用之后签发的 token：只能靠 is_active 拦住
        resp = self._me(token)
        self.assertEqual(resp.status_code, 401, "禁用账号的 token 必须被拒绝")

    def test_token_issued_before_disable_stops_working(self):
        token = create_jwt(self.user)
        self.assertEqual(self._me(token).status_code, 200)  # 禁用前可用
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self._me(token).status_code, 401, "禁用后旧 token 必须立即失效")

    def test_disabled_account_websocket_resolution_returns_none(self):
        payload = {"sub": str(self.user.pk), "tv": self.user.token_version}
        self.assertIsNotNone(async_to_sync(gateway._resolve_user)(payload))
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        payload["tv"] = self.user.token_version
        self.assertIsNone(
            async_to_sync(gateway._resolve_user)(payload),
            "禁用账号不得通过 Socket.IO 握手校验",
        )

    # ---------- 功能不变 ----------
    def test_active_account_still_works(self):
        token = create_jwt(self.user)
        resp = self._me(token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["username"], "i02-user")

    def test_active_account_websocket_resolution_ok(self):
        payload = {"sub": str(self.user.pk), "tv": self.user.token_version}
        user = async_to_sync(gateway._resolve_user)(payload)
        self.assertIsNotNone(user)
        self.assertEqual(user.pk, self.user.pk)

    def test_re_enabled_account_recovers(self):
        token = create_jwt(self.user)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self._me(token).status_code, 401)
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self._me(token).status_code, 200, "重新启用后旧 token 恢复可用")
