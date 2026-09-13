# -*- coding: utf-8 -*-
"""I-13 验证：扩展集权限可以被「超管显式放开」，而不是永久授不出去。

缺陷（改前）：`assert_grant_allowed()` 对扩展集（COMPETITION_ADMIN 模板的
`grantExtras`：`message:manage` / `contractType:manage` / `industryType:manage` /
`company:manage` / `data:region:edit`）**无条件记违规**：

    if perm not in ceiling:
        if perm in extras:
            violations.append(f"{perm} 在扩展集中，需超管显式放开")   # ← 永远走这里
        else:
            violations.append(...)

而全仓没有任何"显式放开"的入口，于是这 5 个权限实际上只有超管能用；
`permissions.py` 的注释与 `docs/合同可视化新建操作指南.md` 承诺的"超管可按需放开"
并不存在（U02 I-13）。

改后：授予接口支持 `allowExtras: true`（仅超管能调到该接口，故等价于"超管显式放开"）；
缺省仍不放开，行为与改前一致。
"""
from __future__ import annotations

import json

from django.test import Client, TestCase

from apps.auth.authentication import create_jwt
from apps.common.permissions import (
    SUPER_ADMIN_ONLY_PERMISSIONS,
    assert_grant_allowed,
    has_permission,
)
from apps.users.models import User

EXTRA_PERM = "company:manage"
EXTRA_PERMS = [
    "message:manage",
    "contractType:manage",
    "industryType:manage",
    "company:manage",
    "data:region:edit",
]


class GrantExtrasTests(TestCase):
    def setUp(self):
        self.admin = User(username="i13-admin", role="SUPER_ADMIN", is_active=True)
        self.admin.set_password("AdminPw!123")
        self.admin.save()
        self.target = User(
            username="i13-target", role="COMPETITION_ADMIN", is_active=True,
            permissions=json.dumps(["contract:manage"]),
        )
        self.target.set_password("TargetPw!123")
        self.target.save()
        self.client = Client()
        self.token = create_jwt(self.admin)
        self.url = f"/api/users/{self.target.pk}/permissions"

    def _grant(self, payload):
        return self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    # ---------- 缺陷场景 ----------
    def test_unit_default_still_rejects_extras(self):
        ok, violations = assert_grant_allowed("SUPER_ADMIN", "COMPETITION_ADMIN", [EXTRA_PERM])
        self.assertFalse(ok)
        self.assertTrue(any("扩展集" in v for v in violations))

    def test_unit_allow_extras_flag_permits_extras(self):
        """改前：本断言做不到（没有 allow_extras 参数，扩展集恒被拒）。"""
        for perm in EXTRA_PERMS:
            with self.subTest(perm=perm):
                ok, violations = assert_grant_allowed(
                    "SUPER_ADMIN", "COMPETITION_ADMIN", [perm], allow_extras=True
                )
                self.assertTrue(ok, violations)

    def test_api_grant_extra_with_explicit_flag(self):
        """改前：400「在扩展集中，需超管显式放开」（无入口）；改后：200。"""
        resp = self._grant({"permissions": [EXTRA_PERM], "allowExtras": True})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.target.refresh_from_db()
        self.assertEqual(self.target.permissions_list, [EXTRA_PERM])
        self.assertTrue(
            has_permission(self.target.role, self.target.permissions_list, EXTRA_PERM),
            "放开后该权限必须真正生效",
        )

    # ---------- 功能不变 ----------
    def test_api_without_flag_still_rejects_extras(self):
        resp = self._grant({"permissions": [EXTRA_PERM]})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("扩展集", resp.json()["message"])
        self.target.refresh_from_db()
        self.assertEqual(self.target.permissions_list, ["contract:manage"])

    def test_super_admin_only_permissions_still_blocked_even_with_flag(self):
        for perm in SUPER_ADMIN_ONLY_PERMISSIONS:
            with self.subTest(perm=perm):
                resp = self._grant({"permissions": [perm], "allowExtras": True})
                self.assertEqual(resp.status_code, 400, resp.content)

    def test_normal_ceiling_permissions_unaffected(self):
        resp = self._grant({"permissions": ["contract:manage", "stock:edit"]})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.target.refresh_from_db()
        self.assertEqual(sorted(self.target.permissions_list), ["contract:manage", "stock:edit"])

    def test_permission_outside_ceiling_still_rejected(self):
        """不在上限也不在扩展集的权限（如 data:material:edit）仍必须拒绝。"""
        resp = self._grant({"permissions": ["data:material:edit"], "allowExtras": True})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("超出", resp.json()["message"])

    def test_non_super_actor_cannot_grant(self):
        ok, violations = assert_grant_allowed(
            "COMPETITION_ADMIN", "COMPETITION_ADMIN", [EXTRA_PERM], allow_extras=True
        )
        self.assertFalse(ok)
        self.assertIn("仅超管可修改权限", violations)

    def test_super_admin_target_must_stay_empty(self):
        ok, violations = assert_grant_allowed(
            "SUPER_ADMIN", "SUPER_ADMIN", ["contract:view"], allow_extras=True
        )
        self.assertFalse(ok)
        self.assertIn("超管权限不落库，必须为空数组", violations)

    def test_flag_accepts_string_true(self):
        """表单/字符串提交 "true" 同样识别（避免只有 JSON 布尔可用）。"""
        resp = self._grant({"permissions": [EXTRA_PERM], "allowExtras": "true"})
        self.assertEqual(resp.status_code, 200, resp.content)
