# -*- coding: utf-8 -*-
"""C-01 / I-05 验证：登录失败限流不可绕过，且限流表不能无界增长。

缺陷（改前，实测）：
1. **键不一致**：中间件用**未 strip** 的 body `username` 查锁定，而
   `LoginView` 用 `strip()` 后的值记账 → 攻击者只要发 `"admin "`（尾随空格）
   就查不到锁定记录，10 次阈值形同虚设，可无限爆破。
2. **只认 JSON**：中间件只解析 `application/json`，改用
   `application/x-www-form-urlencoded`（DRF 同样接受）时中间件拿到的用户名恒为空串，
   锁定检查永远落在 `("", ip)` 这个永不存在的键上 → 同样可无限爆破。
3. **无容量上限**：`_locks` 以攻击者可控的用户名为键且只按时间清理，
   单个 IP 即可用海量唯一用户名把内存撑大。
4. **非字符串入参 500**：`{"username": ["a"]}` 会让视图 `.strip()` 抛
   AttributeError（中间件侧 `(ip, list)` 键也会 TypeError）→ 未认证 500。

改后：视图与中间件共用 `normalize_login_username()`；中间件兼容 JSON 与表单编码；
限流表加容量上限并按最早失败时间淘汰；非字符串一律归一为空串走 400。
"""
from __future__ import annotations

from django.test import Client, TestCase

from apps.common import middleware as mw
from apps.users.models import User

FAIL_THRESHOLD = mw._FAIL_THRESHOLD
NO_SUCH_USER = "c01-nobody"  # 不存在的账号：失败路径不跑 bcrypt，测试更快


class LoginThrottleTests(TestCase):
    def setUp(self):
        mw._locks.clear()
        mw._last_cleanup = 0.0
        self.client = Client()
        self.user = User(username="c01-user", role="PLAYER", is_active=True)
        self.user.set_password("RightPw!123")
        self.user.save()

    def _fail_json(self, username, ip="10.0.0.9"):
        return self.client.post(
            "/api/auth/login",
            data={"username": username, "password": "wrong-password"},
            content_type="application/json",
            REMOTE_ADDR=ip,
        )

    def _fail_form(self, username, ip="10.0.0.9"):
        return self.client.post(
            "/api/auth/login",
            data={"username": username, "password": "wrong-password"},
            REMOTE_ADDR=ip,
        )

    def _login_ok(self, username, password, ip="10.0.0.9"):
        return self.client.post(
            "/api/auth/login",
            data={"username": username, "password": password},
            content_type="application/json",
            REMOTE_ADDR=ip,
        )

    # ---------- 缺陷场景 1：尾随空格变体不得绕过锁定 ----------
    def test_trailing_space_variant_cannot_bypass_lock(self):
        for _ in range(FAIL_THRESHOLD):
            self._fail_json(NO_SUCH_USER)
        blocked = self._fail_json(f"{NO_SUCH_USER} ")
        self.assertEqual(blocked.status_code, 429, "同账号的尾随空格变体必须同样被锁")

    def test_leading_and_inner_padding_cannot_bypass_lock(self):
        for _ in range(FAIL_THRESHOLD):
            self._fail_json(NO_SUCH_USER)
        for variant in (f"  {NO_SUCH_USER}", f"{NO_SUCH_USER}\t", f" {NO_SUCH_USER} "):
            with self.subTest(variant=variant):
                self.assertEqual(self._fail_json(variant).status_code, 429)

    # ---------- 缺陷场景 2：表单编码不得绕过锁定 ----------
    def test_form_encoded_login_cannot_bypass_lock(self):
        for _ in range(FAIL_THRESHOLD):
            self._fail_form(NO_SUCH_USER)
        # 已锁定的账号再用表单方式尝试：中间件必须能解析表单体
        self.assertEqual(self._fail_form(NO_SUCH_USER).status_code, 429)
        # 换成 JSON 提交也必须同样被拦（两种编码共用同一把锁）
        self.assertEqual(self._fail_json(NO_SUCH_USER).status_code, 429)

    # ---------- 缺陷场景 3：限流表不得无界增长 ----------
    def test_lock_table_is_capped(self):
        for i in range(mw._MAX_LOCK_ENTRIES + 500):
            mw.record_login_failure("10.1.1.1", f"attacker-{i}")
        self.assertLessEqual(
            len(mw._locks), mw._MAX_LOCK_ENTRIES, "限流表必须受容量上限约束"
        )

    def test_capped_eviction_keeps_active_locks(self):
        """淘汰只清理最旧条目，正在锁定中的条目必须保留。"""
        mw.record_login_failure("10.2.2.2", "locked-user")
        for _ in range(FAIL_THRESHOLD - 1):
            mw.record_login_failure("10.2.2.2", "locked-user")
        self.assertTrue(mw.is_login_locked("10.2.2.2", "locked-user"))
        for i in range(mw._MAX_LOCK_ENTRIES + 500):
            mw.record_login_failure("10.3.3.3", f"flood-{i}")
        self.assertTrue(
            mw.is_login_locked("10.2.2.2", "locked-user"),
            "淘汰不得丢掉仍在锁定中的条目",
        )

    # ---------- 缺陷场景 4：非字符串入参不得 500 ----------
    def test_non_string_username_returns_400_not_500(self):
        resp = self.client.post(
            "/api/auth/login",
            data={"username": ["a"], "password": "x"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_non_string_password_returns_400_not_500(self):
        resp = self.client.post(
            "/api/auth/login",
            data={"username": "c01-user", "password": {"a": 1}},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    # ---------- 功能不变 ----------
    def test_below_threshold_still_allowed(self):
        for _ in range(FAIL_THRESHOLD - 1):
            self._fail_json(NO_SUCH_USER)
        resp = self._login_ok("c01-user", "RightPw!123")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_successful_login_clears_counter(self):
        for _ in range(FAIL_THRESHOLD - 1):
            self._fail_json("c01-user")
        self.assertEqual(self._login_ok("c01-user", "RightPw!123").status_code, 200)
        for _ in range(FAIL_THRESHOLD - 1):
            self._fail_json("c01-user")
        self.assertEqual(
            self._login_ok("c01-user", "RightPw!123").status_code,
            200,
            "成功登录必须清零计数，后续失败重新计数",
        )

    def test_lock_is_per_account_and_per_ip(self):
        for _ in range(FAIL_THRESHOLD):
            self._fail_json(NO_SUCH_USER)
        # 别的账号不受影响
        self.assertEqual(self._login_ok("c01-user", "RightPw!123").status_code, 200)
        # 别的 IP 不受影响
        self.assertEqual(
            self._fail_json(NO_SUCH_USER, ip="10.9.9.9").status_code, 401
        )

    def test_normalization_helper_matches_expected_shape(self):
        self.assertEqual(mw.normalize_login_username("  admin  "), "admin")
        self.assertEqual(mw.normalize_login_username(None), "")
        self.assertEqual(mw.normalize_login_username(["x"]), "")
        self.assertEqual(mw.normalize_login_username(123), "")
        self.assertEqual(
            len(mw.normalize_login_username("a" * 500)), mw._MAX_USERNAME_LEN
        )
