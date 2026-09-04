"""后端管理后台防直连网关：仅「按钮点击携带一次性令牌」可进入 /admin/，直连自动重定向回前端。

与日志查看器网关（backend/logviewer）同构：
- 主后端签发一次性签名令牌：POST /api/auth/backend-token（仅 SUPER_ADMIN，默认 120s 有效）；
- 前端「系统设置 → 后端管理界面」按钮点击时取令牌拼入 /admin/?token=... 打开；
- 本中间件校验令牌，缺失/无效/过期则 302 自动重定向回前端 SPA（/），实现「不能直连」；
- 校验通过写入带时间戳的会话标记并 302 重定向到干净地址（去除 token 防泄漏），
  随后进入 Django 后台登录流程；
- 已登录（Django 后台超级管理员会话）直接放行，由 Django 自身认证保护，
  不受网关标记 TTL 影响——避免「已登录管理员每 120s 被网关弹回」；
- 网关只负责拦截「未登录时的直接访问」，强制其必须经令牌进入登录页；
- 退出登录（/admin/logout/）时清除网关标记，使随后直接访问 /admin/ 必须重新经令牌网关，
  避免「已登录/曾进入过的会话」被直接复用而绕过令牌；
- 标记存在但既未登录也非登录流程（如会话过期后直连后台深层页面）则清除标记并重定向回前端，
  强制重新经令牌网关。
- 直连（无令牌/无效令牌/过期标记）重定向回前端，与日志查看器行为一致。

受控路径仅 /admin/（前缀匹配）。/api、/socket.io、/static、/uploads 等前端运行必需的入口不受影响。
"""
from __future__ import annotations

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponseRedirect
import os
import time
from django.utils.deprecation import MiddlewareMixin

# 会话标记键：通过网关后置位，后续 /admin/* 请求凭此放行（含 Django 后台自身的登录/登出/改密等子请求）
BACKEND_GATE_SESSION_KEY = "bk_gate"


def _resolve_gate_redirect_to() -> str:
    """弹回目标（前端 SPA 根路径）。

    生产：nginx 在主域名下服务 SPA，弹回 https://域名/ 即前端首页。
    本地开发：主后端 8000 的 / 是 404（前端跑在 vite :5173），弹回 / 会让
    浏览器落在 404 空白页（用户看到「样式不加载/什么都看不到」），
    故指向 vite dev 地址。

    生产判定：DJANGO_ALLOWED_HOSTS 配置了「非回环」主机才算部署到公网；
    .env 本地默认值（127.0.0.1/localhost/::1）不算。
    """
    extra = os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
    for host in (h.strip() for h in extra.split(",")):
        if not host:
            continue
        bare = host.removeprefix(".").lower()
        if bare not in ("127.0.0.1", "localhost", "::1", "[::1]"):
            return f"https://{host}/"
    return "http://127.0.0.1:5173/"


BACKEND_GATE_REDIRECT_TO = _resolve_gate_redirect_to()
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
    """仅对 /admin/* 生效的防直连网关（思路一：未登录直连需令牌，已登录放行，过期标记重定向回前端）。"""

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

        # 已登录（Django 后台超级管理员）：由 Django 自身认证保护，直接放行，
        # 不受网关标记 TTL 影响——避免「已登录管理员每 120s 被网关弹回」。
        # 网关只负责拦截「未登录时的直接访问」，强制其必须经令牌进入登录页。
        if request.session.get("_auth_user_id"):
            return None

        # 携带一次性令牌：校验通过 → 写入带时间戳的会话标记并 302 重定向到干净地址（去除 token 防泄漏）
        token = request.GET.get("token")
        if _verify_token(token):
            request.session[BACKEND_GATE_SESSION_KEY] = {"ts": time.time()}
            request.session.modified = True
            return HttpResponseRedirect(request.path)  # request.path 不含查询串

        # 未登录但持有有效网关标记：允许进入登录流程（/admin/ 根路径与 /admin/login/），
        # 保障本次后台访问可用；深层直连（如 /admin/auth/user/）则清除标记并重定向回前端。
        if _gate_set(request):
            if request.path in (BACKEND_GATE_PREFIX, "/admin/login/"):
                return None
            del request.session[BACKEND_GATE_SESSION_KEY]
            request.session.modified = True
            return HttpResponseRedirect(BACKEND_GATE_REDIRECT_TO)

        # 无令牌、无有效网关标记：直连（直接输网址/书签/过期链接）视为非法，重定向回前端 SPA。
        return HttpResponseRedirect(BACKEND_GATE_REDIRECT_TO)
