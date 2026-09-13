# -*- coding: utf-8 -*-
"""I-03 验证：管理员重置密码 / 禁用账号必须吊销已签发 token 并断开在线 socket。

缺陷（改前）：
- `users/views.py::UserPasswordView.patch`（管理员重置密码）只写
  password_hash/must_change_password/updated_at，**不递增 token_version**；
  而自助改密（`auth/views.py::ChangePasswordView`）与登录都会递增。
  → 被怀疑失窃或已在线的会话在"重置密码"后仍然有效（JWT 默认 24h）。
- 禁用账号（`PATCH /api/users/:id {"isActive": false}`）同样只改字段，既不吊销
  token 也不断开 socket（已建立的 Socket.IO 连接只在握手时校验 is_active）。

改后：两条管理动作都递增 token_version 并调用 kick_user_sessions()
（先发 auth:required 通知、再逐个 sio.disconnect）。
"""
from __future__ import annotations

import asyncio
from unittest import mock

from django.test import Client, TestCase

from apps.auth.authentication import create_jwt
from apps.realtime import emit as emit_mod
from apps.users.models import User


class _FakeSio:
    """记录 emit / disconnect 调用的假 sio。"""

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


class AdminActionRevokesSessionTests(TestCase):
    def setUp(self):
        self.admin = User(username="i03-admin", role="SUPER_ADMIN", is_active=True)
        self.admin.set_password("AdminPw!123")
        self.admin.save()
        self.target = User(username="i03-target", role="PLAYER", is_active=True)
        self.target.set_password("TargetPw!123")
        self.target.save()
        self.client = Client()
        self.admin_token = create_jwt(self.admin)
        self.target_token = create_jwt(self.target)

    def _me(self, token):
        return self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")

    # ---------- 缺陷场景 1：重置密码必须吊销旧 token ----------
    def test_admin_password_reset_revokes_existing_token(self):
        """关键实证：显式 mustChangePassword=false 时，旧 token 必须失效。

        为什么必须显式传 false：`UserPasswordView` 默认把目标账号置
        mustChangePassword=true，认证层会把旧 token 的**所有非改密请求**拦成 401 ——
        这个 401 会掩盖「token 未吊销」的真实缺陷（token 本身仍有效，且一旦
        must_change_password 被清掉就恢复全量访问）。
        """
        self.assertEqual(self._me(self.target_token).status_code, 200)
        before_tv = self.target.token_version
        resp = self.client.patch(
            f"/api/users/{self.target.pk}/password",
            data={"password": "BrandNew!123", "mustChangePassword": False},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.target.refresh_from_db()
        self.assertGreater(
            self.target.token_version, before_tv, "重置密码必须递增 token_version"
        )
        self.assertEqual(
            self._me(self.target_token).status_code, 401, "重置密码后旧 token 必须失效"
        )

    def test_admin_password_reset_kicks_socket_sessions(self):
        fake = _FakeSio(["sid-a", "sid-b"])
        with mock.patch("apps.users.views.kick_user_sessions") as kick:
            self.client.patch(
                f"/api/users/{self.target.pk}/password",
                data={"password": "BrandNew!123"},
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
            )
        kick.assert_called_once()
        self.assertEqual(kick.call_args[0][0], self.target.pk)
        # 同时验证底层实现确实「断开」而不只是通知
        with mock.patch("apps.realtime.gateway.sio", fake):
            asyncio.run(emit_mod.kick_user_sessions_async(self.target.pk, "password_reset"))
        self.assertEqual(sorted(fake.disconnected), ["sid-a", "sid-b"])
        self.assertEqual(fake.emitted[0][0], "auth:required")
        self.assertEqual(fake.emitted[0][2], f"user-{self.target.pk}")

    # ---------- 缺陷场景 2：禁用账号必须吊销 token ----------
    def test_disabling_account_revokes_token_and_kicks(self):
        with mock.patch("apps.users.views.kick_user_sessions") as kick:
            resp = self.client.patch(
                f"/api/users/{self.target.pk}",
                data={"isActive": False},
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertGreater(self.target.token_version, 0, "禁用必须递增 token_version")
        kick.assert_called_once_with(self.target.pk, reason="inactive")
        self.assertEqual(self._me(self.target_token).status_code, 401)

    # ---------- 功能不变 ----------
    def test_normal_patch_does_not_revoke_session(self):
        """普通资料修改（如改显示名）不该把人踢下线。"""
        before = self.target.token_version
        resp = self.client.patch(
            f"/api/users/{self.target.pk}",
            data={"displayName": "改名不改会话"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.target.refresh_from_db()
        self.assertEqual(self.target.token_version, before)
        self.assertEqual(self._me(self.target_token).status_code, 200)

    def test_admin_self_reset_still_returns_ok(self):
        """管理员重置自己的密码：接口照常返回成功（会话被吊销由前端重新登录承担）。"""
        resp = self.client.patch(
            f"/api/users/{self.admin.pk}/password",
            data={"password": "AdminNew!123"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.must_change_password)

    def test_kick_without_loop_is_silent(self):
        """无实时 loop（脚本/测试/migrate）时踢人必须静默降级，不影响主流程。"""
        emit_mod.kick_user_sessions(999999, reason="test")
        emit_mod.kick_user_sessions(None, reason="test")
