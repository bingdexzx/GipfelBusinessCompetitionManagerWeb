"""认证与健康检查视图：对应原 NestJS Health/Version/AuthController。

响应经 apps.common.response.JSONRenderer 自动包装为 {code,message,data}：
视图返回 Response(data)，其中 data 为 dict/list/None 时渲染器自动包装为
{code:0, message:"成功", data}；如需自定义 message 用 success() 包成含 code 键的 dict。
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.signing import TimestampSigner
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
    """GET /api/version → {code:0, message:"成功", data:{version:"1.3.18", port: <后端监听端口>, log_viewer_port: <日志查看器端口>}}

    port 来自 settings.PORT（即 .env 的 PORT），log_viewer_port 来自 settings.LOG_VIEWER_PORT
    （即 .env 的 LOG_VIEWER_PORT），供前端「后端管理」与「日志查看器」跳转按钮动态拼地址，
    避免后端改端口后按钮仍硬编码旧端口。
    """

    permission_classes = (AllowAny,)

    def get(self, request):
        # 日志查看器公网地址：优先 LOG_VIEWER_PUBLIC_URL 显式覆盖；
        # 否则由当前请求 Host 派生子域 log.<host>（部署需配套 DNS A 记录 + certbot -d log.<host>）；
        # 均无则回退本地 127.0.0.1（开发）。前端「日志查看器」按钮据此拼跳转地址。
        log_viewer_url = os.environ.get("LOG_VIEWER_PUBLIC_URL", "").strip()
        if not log_viewer_url:
            host = (request.get_host().split(":") or [""])[0]
            log_viewer_url = (
                f"https://log.{host}/"
                if host
                else f"http://127.0.0.1:{settings.LOG_VIEWER_PORT}/"
            )
        return Response(
            {
                "version": VERSION,
                "port": settings.PORT,
                "log_viewer_port": settings.LOG_VIEWER_PORT,
                "log_viewer_url": log_viewer_url,
            }
        )


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


# ==================== 日志查看器防直连令牌 ====================
class LogViewerTokenView(APIView):
    """POST /api/auth/logviewer-token → {token}

    签发一次性/短时（默认 120s）防直连令牌，供前端「系统设置 → 日志查看器」按钮点击后拼入跳转 URL。
    日志查看器 index 视图校验该令牌，缺失/无效/过期则拒绝访问，从而实现
    「仅按钮点击可跳转、直接输入网址无法跳转」。

    仅 SUPER_ADMIN 可获取（与前端按钮 v-if="isSuperAdmin" 一致）；令牌本身不替代日志查看器
    自身的超级管理员登录，仅作为「来源合法性」网关。
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可生成日志查看器访问令牌", code=403, status_code=403)
        # 用与主后端共用的 LOGVIEWER_SECRET_KEY 签名；盐固定以便日志查看器侧一致校验。
        signer = TimestampSigner(key=settings.LOGVIEWER_SECRET_KEY, salt="logviewer-gate")
        token = signer.sign(f"lv:{request.user.id}")
        return Response({"token": token})


# ==================== 后端管理后台防直连令牌 ====================
class BackendTokenView(APIView):
    """POST /api/auth/backend-token → {token}

    签发一次性/短时（默认 120s）防直连令牌，供前端「系统设置 → 后端管理界面」按钮点击后拼入
    /admin/?token=...。后端 BackendGateMiddleware 校验该令牌，缺失/无效/过期则 302 重定向回前端 SPA，
    从而实现「仅按钮点击可跳转、直接输入网址无法跳转」。

    仅 SUPER_ADMIN 可获取（与前端按钮 v-if="isSuperAdmin" 一致）；令牌本身不替代 Django 后台
    自身的超级管理员登录，仅作为「来源合法性」网关。
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可生成后端管理访问令牌", code=403, status_code=403)
        # 用与主后端/日志查看器共用的 LOGVIEWER_SECRET_KEY 签名；盐固定以便 BackendGateMiddleware 一致校验。
        signer = TimestampSigner(key=settings.LOGVIEWER_SECRET_KEY, salt="backend-gate")
        token = signer.sign(f"bk:{request.user.id}")
        return Response({"token": token})


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
