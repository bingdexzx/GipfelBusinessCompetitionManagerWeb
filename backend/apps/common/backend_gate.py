"""后端管理后台防直连网关：仅「按钮点击携带一次性令牌」可进入 /admin/，直连重定向回前端。

与日志查看器网关（backend/logviewer）同构：
- 主后端签发一次性签名令牌：POST /api/auth/backend-token（仅 SUPER_ADMIN，默认 120s 有效）；
- 前端「系统设置 → 后端管理界面」按钮点击时取令牌拼入 /admin/?token=... 打开；
- 本中间件校验令牌，缺失/无效/过期则 302 重定向到 /（前端 SPA 根路径），实现「不能直连」；
- 校验通过写入会话标记 bk_gate，后续 /admin/*（含后台自身登录/登出/改密）凭标记放行，无需每次带令牌。

受控路径仅 /admin/（前缀匹配）。/api、/socket.io、/static、/uploads 等前端运行必需的入口不受影响。
"""
from __future__ import annotations

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponseRedirect
from django.utils.deprecation import MiddlewareMixin

# 会话标记键：通过网关后置位，后续 /admin/* 请求凭此放行（含 Django 后台自身的登录/登出/改密等子请求）
BACKEND_GATE_SESSION_KEY = "bk_gate"
# 直连（无令牌/无效令牌）时重定向回前端 SPA 根路径
BACKEND_GATE_REDIRECT_TO = "/"
# 令牌作用路径前缀（仅管理后台入口受控）
BACKEND_GATE_PREFIX = "/admin/"
# 令牌签名盐（与主后端 LOGVIEWER_SECRET_KEY 共用同一 .env 共享密钥，盐区分以隔离日志查看器令牌）
BACKEND_GATE_SALT = "backend-gate"


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


class BackendGateMiddleware(MiddlewareMixin):
    """仅对 /admin/* 生效的防直连网关。"""

    def process_request(self, request):
        # 仅拦截管理后台入口；其余路径（/api、/socket.io、/static、/uploads 等）原样放行
        if not request.path.startswith(BACKEND_GATE_PREFIX):
            return None

        # 已通过网关：会话标记存在即放行（含 Django 后台自身的登录/登出/改密等子请求）
        if request.session.get(BACKEND_GATE_SESSION_KEY):
            return None

        # 携带一次性令牌：校验通过 → 写入会话标记并 302 重定向到干净地址（去除 token 防泄漏）
        token = request.GET.get("token")
        if _verify_token(token):
            request.session[BACKEND_GATE_SESSION_KEY] = True
            request.session.modified = True
            clean = request.path  # request.path 不含查询串
            return HttpResponseRedirect(clean)

        # 无令牌/令牌无效：直连视为非法，重定向回前端 SPA 根路径
        return HttpResponseRedirect(BACKEND_GATE_REDIRECT_TO)
