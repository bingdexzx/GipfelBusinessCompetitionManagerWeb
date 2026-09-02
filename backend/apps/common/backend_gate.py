"""后端管理后台防直连网关：仅「按钮点击携带一次性令牌」可进入 /admin/，直连展示拒绝页。

与日志查看器网关（backend/logviewer）同构：
- 主后端签发一次性签名令牌：POST /api/auth/backend-token（仅 SUPER_ADMIN，默认 120s 有效）；
- 前端「系统设置 → 后端管理界面」按钮点击时取令牌拼入 /admin/?token=... 打开；
- 本中间件校验令牌，缺失/无效/过期则展示「拒绝直接访问」403 页，实现「不能直连」；
- 校验通过写入带时间戳的会话标记并 302 重定向到干净地址（去除 token 防泄漏），
  随后进入 Django 后台登录流程；
- 已登录（Django 后台超级管理员会话）直接放行，由 Django 自身认证保护，
  不受网关标记 TTL 影响——避免「已登录管理员每 120s 被网关弹回」；
- 网关只负责拦截「未登录时的直接访问」，强制其必须经令牌进入登录页；
- 退出登录（/admin/logout/）时清除网关标记，使随后直接访问 /admin/ 必须重新经令牌网关，
  避免「已登录/曾进入过的会话」被直接复用而绕过令牌；
- 标记存在但既未登录也非登录流程（如会话过期后直连后台深层页面）则清除标记并展示拒绝页，
  强制重新经令牌网关。
- 直连（无令牌/无效令牌/过期标记）展示拒绝页，与日志查看器行为一致。

受控路径仅 /admin/（前缀匹配）。/api、/socket.io、/static、/uploads 等前端运行必需的入口不受影响。
"""
from __future__ import annotations

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse, HttpResponseRedirect
import time
from django.utils.deprecation import MiddlewareMixin

# 会话标记键：通过网关后置位，后续 /admin/* 请求凭此放行（含 Django 后台自身的登录/登出/改密等子请求）
BACKEND_GATE_SESSION_KEY = "bk_gate"
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


def _gate_denied() -> HttpResponse:
    """直接访问（无有效令牌、未通过网关）的拒绝页：实现「直接输入网址无法跳转」。"""
    html = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>拒绝访问</title></head><body style='font-family:system-ui,sans-serif;"
        "max-width:560px;margin:12vh auto;padding:0 16px;color:#333'>"
        "<h2 style='color:#c0392b'>拒绝直接访问</h2>"
        "<p>后端管理界面仅允许从「系统设置 → 后端管理界面」按钮跳转进入。</p>"
        "<p>直接输入网址、书签或复制链接均无法访问。请回到主系统，"
        "以超级管理员身份点击「后端管理界面」按钮后再次进入。</p>"
        "</body></html>"
    )
    return HttpResponse(html, status=403, content_type="text/html; charset=utf-8")


class BackendGateMiddleware(MiddlewareMixin):
    """仅对 /admin/* 生效的防直连网关（思路一：未登录直连需令牌，已登录放行，过期标记拒）。"""

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
        # 保障本次后台访问可用；深层直连（如 /admin/auth/user/）则拒绝。
        if _gate_set(request):
            if request.path in (BACKEND_GATE_PREFIX, "/admin/login/"):
                return None
            del request.session[BACKEND_GATE_SESSION_KEY]
            request.session.modified = True
            return _gate_denied()

        # 无令牌、无有效网关标记：直连（直接输网址/书签/过期链接）视为非法，展示拒绝页。
        return _gate_denied()
