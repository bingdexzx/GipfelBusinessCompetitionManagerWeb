# -*- coding: utf-8 -*-
"""I-19 验证：`permissions=null` 必须按角色继承，而不是"零权限"。

缺陷（改前）：`User.permissions` 的字段注释写明「null 表示按 role 继承」，
但 `permissions_list` 对 null 直接返回 `[]`，而 `ROLE_TEMPLATES` 只被授予校验使用
→ 任何"未显式赋权"的账号（历史数据、归档导入、直接建库）都变成**零权限**，
连 `data:material:view` 这类基础查看都做不了（U02 I-19）。

改后：
- `permissions=null` → 返回该角色模板的默认权限（真正"按角色继承"）；
- `permissions="[]"`（显式空数组）→ 仍是零权限，语义与继承区分开；
- 授予接口支持 `permissions: null` 显式切回"按角色继承"，
  `permissions: []` 显式清空（改前 [] 会被落库成 NULL，从而无法表达"零权限"）。
"""
from __future__ import annotations

import json

from django.test import Client, TestCase

from apps.auth.authentication import create_jwt
from apps.common.permissions import BASE_VIEW_PERMISSIONS, role_default_permissions
from apps.competitions.models import Competition
from apps.users.models import User


class NullPermissionsSemanticsTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="I19 权限继承")
        self.admin = User(username="i19-admin", role="SUPER_ADMIN", is_active=True)
        self.admin.set_password("AdminPw!123")
        self.admin.save()
        self.client = Client()
        self.admin_token = create_jwt(self.admin)

    def _user(self, username, role, permissions):
        u = User(
            username=username, role=role, is_active=True,
            competition=self.comp, permissions=permissions,
        )
        u.set_password("Pw!123456")
        u.save()
        return u

    def _materials(self, user):
        return self.client.get(
            "/api/materials", HTTP_AUTHORIZATION=f"Bearer {create_jwt(user)}"
        )

    # ---------- 缺陷场景 ----------
    def test_null_permissions_inherit_role_defaults(self):
        """改前：permissions_list == []（零权限）→ 列表接口 403。"""
        u = self._user("i19-inherit", "COMPETITION_ADMIN", None)
        self.assertEqual(sorted(u.permissions_list), sorted(role_default_permissions("COMPETITION_ADMIN")))
        self.assertIn("data:material:view", u.permissions_list)
        self.assertEqual(self._materials(u).status_code, 200)

    def test_null_permissions_player_can_view_basics(self):
        u = self._user("i19-player", "PLAYER", None)
        self.assertEqual(sorted(u.permissions_list), sorted(BASE_VIEW_PERMISSIONS))
        self.assertEqual(self._materials(u).status_code, 200)

    def test_null_permissions_unknown_role_is_empty_not_crash(self):
        u = self._user("i19-unknown", "PLAYER", None)
        u.role = "NO_SUCH_ROLE"
        u.save(update_fields=["role"])
        u.refresh_from_db()
        self.assertEqual(u.permissions_list, [])

    def test_super_admin_null_permissions_still_all_powerful(self):
        u = self._user("i19-super", "SUPER_ADMIN", None)
        self.assertEqual(u.permissions_list, [], "超管权限不落库、也不继承（隐式全权）")
        self.assertEqual(self._materials(u).status_code, 200)

    # ---------- 显式空数组 = 零权限（必须保持可表达） ----------
    def test_explicit_empty_list_stays_zero_permission(self):
        u = self._user("i19-none", "COMPETITION_ADMIN", "[]")
        self.assertEqual(u.permissions_list, [])
        self.assertEqual(self._materials(u).status_code, 403)

    # ---------- 授予接口：null 与 [] 语义区分 ----------
    def _grant(self, user, payload):
        return self.client.post(
            f"/api/users/{user.pk}/permissions",
            data=payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.admin_token}",
        )

    def test_grant_null_switches_back_to_inheritance(self):
        u = self._user("i19-switch", "COMPETITION_ADMIN", json.dumps(["contract:view"]))
        self.assertEqual(self._materials(u).status_code, 403)
        resp = self._grant(u, {"permissions": None})
        self.assertEqual(resp.status_code, 200, resp.content)
        u.refresh_from_db()
        self.assertIsNone(u.permissions, "null 必须落库为 NULL")
        self.assertIn("data:material:view", u.permissions_list)
        self.assertEqual(self._materials(u).status_code, 200)

    def test_grant_empty_list_revokes_all(self):
        """改前：[] 会被落库成 NULL（等价于"按角色继承"），无法表达零权限。"""
        u = self._user("i19-revoke", "COMPETITION_ADMIN", None)
        self.assertEqual(self._materials(u).status_code, 200)
        resp = self._grant(u, {"permissions": []})
        self.assertEqual(resp.status_code, 200, resp.content)
        u.refresh_from_db()
        self.assertEqual(u.permissions, "[]", "显式空数组必须落库为 []，而不是 NULL")
        self.assertEqual(u.permissions_list, [])
        self.assertEqual(self._materials(u).status_code, 403)

    def test_grant_non_list_non_null_rejected(self):
        u = self._user("i19-bad", "COMPETITION_ADMIN", None)
        resp = self._grant(u, {"permissions": "contract:view"})
        self.assertEqual(resp.status_code, 400, resp.content)

    # ---------- 功能不变 ----------
    def test_explicit_permissions_unchanged(self):
        u = self._user("i19-explicit", "COMPETITION_ADMIN", json.dumps(["data:material:view"]))
        self.assertEqual(u.permissions_list, ["data:material:view"])
        self.assertEqual(self._materials(u).status_code, 200)

    def test_grant_version_bumped_for_frontend_refresh(self):
        u = self._user("i19-version", "COMPETITION_ADMIN", None)
        before = u.permission_version
        self._grant(u, {"permissions": None})
        u.refresh_from_db()
        self.assertEqual(u.permission_version, before + 1)
