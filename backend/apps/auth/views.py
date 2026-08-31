"""认证与健康检查视图：对应原 NestJS Health/Version/AuthController。

响应经 apps.common.response.JSONRenderer 自动包装为 {code,message,data}：
视图返回 Response(data)，其中 data 为 dict/list/None 时渲染器自动包装为
{code:0, message:"成功", data}；如需自定义 message 用 success() 包成含 code 键的 dict。
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.middleware import (
    _client_ip,
    record_login_failure,
    record_login_success,
)

from .authentication import create_jwt

VERSION = "1.3.18"


# ==================== 用户资料序列化 ====================
def serialize_user(user) -> dict:
    """构造前端所需用户资料（与原 auth.controller login/me 返回结构一致）。"""
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "displayName": user.display_name,
        "mustChangePassword": getattr(user, "must_change_password", False),
        "permissions": user.permissions_list,
        "companyScopes": user.company_scopes_list,
        "viewCompanyScopes": user.view_company_scopes_list,
        "contractViewCompanyScopes": user.contract_view_company_scopes_list,
        "stockCompanyScopes": user.stock_company_scopes_list,
        "competitionId": getattr(user, "competition_id", None),
    }


# ==================== 健康检查 / 版本 ====================
class HealthView(APIView):
    """GET /api/health → {code:0, message:"成功", data:{status:"ok"}}"""

    permission_classes = (AllowAny,)

    def get(self, request):
        return Response({"status": "ok"})


class VersionView(APIView):
    """GET /api/version → {code:0, message:"成功", data:{version:"1.3.18"}}"""

    permission_classes = (AllowAny,)

    def get(self, request):
        return Response({"version": VERSION})


# ==================== 登录 ====================
class LoginView(APIView):
    """POST /api/auth/login {username, password} → {token, user}"""

    permission_classes = (AllowAny,)

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            raise BusinessError("用户名和密码不能为空", code=400, status_code=400)

        ip = _client_ip(request)

        from apps.users.models import User

        user = User.objects.filter(username=username).first()

        # 用户不存在或密码错误：统一提示，避免枚举用户
        if user is None or not user.check_password(password):
            record_login_failure(ip, username)
            raise BusinessError("用户名或密码错误", code=401, status_code=401)

        # 顶号下线：递增 token_version，旧 token 立即失效
        user.token_version = (user.token_version or 0) + 1
        user.save(update_fields=["token_version", "updated_at"])

        record_login_success(ip, username)

        token = create_jwt(user)
        return Response({"token": token, "user": serialize_user(user)})


# ==================== 当前用户 ====================
class MeView(APIView):
    """GET /api/auth/me → 当前登录用户资料"""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(serialize_user(request.user))


# ==================== 修改密码 ====================
class ChangePasswordView(APIView):
    """POST /api/auth/change-password {oldPassword, newPassword}

    标记 _allow_must_change_password=True：强制改密场景下放行（认证层据此豁免）。
    """

    permission_classes = (IsAuthenticated,)
    _allow_must_change_password = True

    def post(self, request):
        old_password = request.data.get("oldPassword") or ""
        new_password = request.data.get("newPassword") or ""
        if not old_password or not new_password:
            raise BusinessError("原密码和新密码不能为空", code=400, status_code=400)
        if len(new_password) < 6:
            raise BusinessError("新密码长度不能少于 6 位", code=400, status_code=400)

        user = request.user
        if not user.check_password(old_password):
            raise BusinessError("原密码不正确", code=400, status_code=400)
        if old_password == new_password:
            raise BusinessError("新密码不能与原密码相同", code=400, status_code=400)

        user.set_password(new_password)
        user.must_change_password = False
        # 不递增 token_version：改密后保留当前会话（与原行为一致）
        user.save(update_fields=["password_hash", "must_change_password", "updated_at"])

        return Response({"ok": True})
