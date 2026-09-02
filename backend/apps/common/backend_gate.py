"""后端管理后台防直连网关：仅「按钮点击携带一次性令牌」可进入 /admin/，直连重定向回前端。

与日志查看器网关（backend/logviewer）同构：
- 主后端签发一次性签名令牌：POST /api/auth/backend-token（仅 SUPER_ADMIN，默认 120s 有效）；
- 前端「系统设置 → 后端管理界面」按钮点击时取令牌拼入 /admin/?token=... 打开；
- 本中间件校验令牌，缺失/无效/过期则 302 重定向到 /（前端 SPA 根路径），实现「不能直连」；
- 校验通过写入会话标记 bk_gate，仅用于本次登录流程（/admin/ → /admin/login/ → 登录）放行；
- 已登录（Django 认证）后凭 bk_gate 标记 + Django 会话正常访问后台；
- 退出登录（/admin/logout/）时清除 bk_gate 标记，使随后直接访问 /admin/ 必须重新经令牌网关，
  避免「已登录/曾进入过的会话」被直接复用而绕过令牌；
- 标记存在但既未登录也非登录流程（如会话过期后直连后台深层页面）则清除标记并退回前端，
  强制重新经令牌网关。

受控路径仅 /admin/（前缀匹配）。/api、/socket.io、/static、/uploads 等前端运行必需的入口不受影响。
"""
from __future__ import annotations

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponseRedirect
import time
from django.utils.deprecation import MiddlewareMixin

# 会话标记键：通过网关后置位，后续 /admin/* 请求凭此放行（含 Django 后台自身的登录/登出/改密等子请求）
BACKEND_GATE_SESSION_KEY = "bk_gate"
# 直连（无令牌/无效令牌）时重定向回前端 SPA 根路径
BACKEND_GATE_REDIRECT_TO = "/"
# 令牌作用路径前缀（仅管理后台入口受控）
BACKEND_GATE_PREFIX = "/admin/"
# 令牌签名盐（与主后端 LOGVIEWER_SECRET_KEY 共用同一 .env 共享密钥，盐区分以隔离日志查看器令牌）
BACKEND_GATE_SALT = "backend-gate"
# 网关标记有效期（秒）：与令牌有效期一致。过期后直连 /admin/ 必须重新经令牌网关，
# 避免「点过一次按钮后会话 cookie 永久有效、随后直连总能进」的绕过（思路一）。
BACKEND_GATE_TTL = int(getattr(settings, "BACKEND_GATE_MAX_AGE", 120))


def _verify_token(token: str | None) -> bool:
    """校验一次性签名令牌；缺失/无效/过期返回 False。"""
    if not token:
        return False
    signer = TimestampSigner(key=settings.LOGVIEWER_SECRET_KEY, salt=BACKEND_GATE_SALT)
    try:
        signer.unsign(token, max_age=settings.BACKEND_GATE_MAX_AGE)
    except (BadSignature, SignatureExpired, ValueError):
        return False
    return True


def _gate_set(request) -> bool:
    """网关标记是否存在且未过期（思路一：标记带 TTL，过期即视为未通过）。"""
    data = request.session.get(BACKEND_GATE_SESSION_KEY)
    if not isinstance(data, dict) or "ts" not in data:
        return False
    if time.time() - float(data["ts"]) > BACKEND_GATE_TTL:
        del request.session[BACKEND_GATE_SESSION_KEY]
        request.session.modified = True
        return False
    return True


class BackendGateMiddleware(MiddlewareMixin):
    """仅对 /admin/* 生效的防直连网关（思路一：入口需令牌，标记带 TTL 不长期有效）。"""

    def process_request(self, request):
        # 仅拦截管理后台入口；其余路径（/api、/socket.io、/static、/uploads 等）原样放行
        if not request.path.startswith(BACKEND_GATE_PREFIX):
            return None

        # 退出登录：清除网关标记（本次登出请求仍放行，交由 Django 处理），
        # 使随后直接访问 /admin/ 必须重新经令牌网关，避免会话被直接复用绕过令牌。
        if request.path == "/admin/logout/":
            if request.session.get(BACKEND_GATE_SESSION_KEY):
                del request.session[BACKEND_GATE_SESSION_KEY]
                request.session.modified = True
            return None

        # 携带一次性令牌：校验通过 → 写入带时间戳的会话标记并 302 重定向到干净地址（去除 token 防泄漏）
        token = request.GET.get("token")
        if _verify_token(token):
            request.session[BACKEND_GATE_SESSION_KEY] = {"ts": time.time()}
            request.session.modified = True
            return HttpResponseRedirect(request.path)  # request.path 不含查询串

        # 已通过网关（会话标记存在且未过期）：
        if _gate_set(request):
            # 已登录（Django 认证）或处于登录流程（/admin/ 根路径与 /admin/login/ 由 Django 重定向衔接）
            # 均放行，保障本次后台访问可用。
            if request.session.get("_auth_user_id") or request.path in (
                BACKEND_GATE_PREFIX,
                "/admin/login/",
            ):
                return None
            # 标记存在但既未登录也非登录流程（如会话过期后直连后台深层页面）：
            # 清除标记并退回前端，强制重新经令牌网关。
            del request.session[BACKEND_GATE_SESSION_KEY]
            request.session.modified = True
            return HttpResponseRedirect(BACKEND_GATE_REDIRECT_TO)

        # 无令牌、无有效网关标记：直连视为非法，重定向回前端 SPA 根路径
        return HttpResponseRedirect(BACKEND_GATE_REDIRECT_TO)
