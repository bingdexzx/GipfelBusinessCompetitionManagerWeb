"""中间件集合：安全头 / 操作员上下文 / 登录限流 / CORS 来源校验。
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from urllib.parse import urlparse

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("gipfel")


# ==================== User-Agent 精简 ====================
import re as _re  # noqa: E402


def _simplify_ua(ua: str) -> str:
    """将完整 User-Agent 精简为「浏览器/系统 版本(型号)」短标识，便于日志展示。

    示例输出：
        Chrome/Win10 22H2
        Safari/iOS 17.0 (iPhone)
        Chrome/Android 14 (SM-S918B)
        Firefox/macOS 14.0
        Edge/Win11 23H2
    """
    if not ua:
        return "-"

    # ---- 浏览器识别（优先级从高到低） ----
    browser = "-"
    if "Edg/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera/" in ua:
        browser = "Opera"
    elif "Chrome/" in ua and "Safari/" in ua:
        browser = "Chrome"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua and "Chrome/" not in ua:
        browser = "Safari"
    elif "MSIE " in ua or "Trident/" in ua:
        browser = "IE"

    # ---- 操作系统 + 版本 + 设备型号 ----
    os_info = "-"

    # Windows：NT 10.0 可能是 Win10 或 Win11（UA 不区分），附带版本号如 22H2
    m = _re.search(r"Windows NT (\d+\.\d+)", ua)
    if m:
        nt_ver = m.group(1)
        if nt_ver == "10.0":
            os_name = "Win10/11"
        elif nt_ver == "6.3":
            os_name = "Win8.1"
        elif nt_ver == "6.1":
            os_name = "Win7"
        else:
            os_name = f"Win(NT{nt_ver})"
        os_info = os_name

    # iOS：iPhone/iPad + CPU iPhone OS 17_0 → iOS 17.0 (iPhone)
    # 必须在 macOS 之前检测：iOS UA 含 "like Mac OS X"，若 macOS 在前会被误判
    elif "iPhone" in ua or "iPad" in ua:
        device = "iPhone" if "iPhone" in ua else "iPad"
        m = _re.search(r"CPU (?:iPhone )?OS ([\d_]+)", ua)
        ver = m.group(1).replace("_", ".") if m else ""
        os_info = f"iOS {ver} ({device})".strip()

    # macOS：Mac OS X 10_15_7 → macOS 10.15.7
    elif "Mac OS X" in ua:
        m = _re.search(r"Mac OS X ([\d_]+)", ua)
        ver = m.group(1).replace("_", ".") if m else ""
        os_info = f"macOS {ver}".strip()

    # Android：Android 14; 型号 → Android 14 (型号)
    elif "Android" in ua:
        m = _re.search(r"Android ([\d.]+)", ua)
        ver = m.group(1) if m else ""
        # 提取 "Android N; <型号>" 中的型号：匹配到下一个 ")" 或 ";" 或 " Build" 为止。
        # 旧正则 (?:Build|[A-Z]{2}[-_])? 前缀跳过组会吞掉 SM-/RM- 等型号前缀，
        # 导致 SM-S918B 只提取到 S918B；改为直接匹配到分隔符，再排除 Build/ 开头的非型号串。
        m_model = _re.search(r"Android [\d.]+;\s*([^;)]+?)(?:\s*\)|;|\s+Build)", ua)
        model = m_model.group(1).strip() if m_model else ""
        # "Build/xxx" 是构建标识而非型号，清空
        if model.startswith("Build/"):
            model = ""
        # 清理型号末尾的多余标识（如 " w" 全球版、" v2" 版本号）
        model = _re.sub(r"\s+(?:w|v\d+)$", "", model).strip()
        os_info = f"Android {ver} ({model})".strip() if model else f"Android {ver}".strip()

    # Linux
    elif "Linux" in ua:
        os_info = "Linux"

    # ---- 拼接结果 ----
    return f"{browser}/{os_info}"


# ==================== 本地/私网来源判定（与 main.ts isLocalOrPrivateOrigin 一致） ====================
def is_local_or_private_origin(origin: str) -> bool:
    if not origin:
        return False
    try:
        u = urlparse(origin)
        h = u.hostname
        if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return True
        if u.scheme in ("file", "app"):
            return True
        if re.match(r"^192\.168\.\d{1,3}\.\d{1,3}$", h) or re.match(
            r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$", h
        ) or re.match(r"^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$", h):
            return True
        return False
    except Exception:  # noqa: BLE001
        return False


# ==================== 安全响应头（对应 securityHeaders 中间件） ====================
class SecurityHeadersMiddleware(MiddlewareMixin):
    """CSP default-src 'none' / XFO DENY / XCTO nosniff / Referrer no-referrer / CORP。"""

    def process_response(self, request, response):
        # 管理后台（/admin）使用 Django 自带会话鉴权与表单提交，必须放行安全头，
        # 否则 form-action 'none' 会拦截登录与所有表单提交、default-src 'none' 会禁掉后台样式与脚本。
        # 仅对 /admin 放行，/api 等业务接口的安全头保持不变。
        if request.path.startswith("/admin"):
            return response
        response["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "no-referrer"
        # /uploads 跨源加载（地图背景图等）放松 CORP；其余 same-origin
        if request.path.startswith("/uploads"):
            response["Cross-Origin-Resource-Policy"] = "cross-origin"
        else:
            response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


# ==================== 操作员上下文（对应 OperatorMiddleware + AsyncLocalStorage） ====================
# 用 contextvars 在整个请求生命周期内注入操作员，供审计/日志使用。
import contextvars  # noqa: E402
from apps.common.helpers import client_ip as _client_ip

_operator_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "operator_ctx", default=None
)


def get_current_operator() -> dict | None:
    return _operator_ctx.get()


def set_current_operator(operator: dict | None) -> contextvars.Token:
    return _operator_ctx.set(operator)


class OperatorContextMiddleware(MiddlewareMixin):
    """从 JWT（由 DRF authentication 解析）注入操作员到 contextvars，同时注入客户端 IP。

    DRF 的认证发生在视图派发阶段，中间件先于视图执行；此处从 Authorization
    头解析（与 JWT 认证独立、仅取上下文），失败不阻断（鉴权由视图层负责）。
    """

    def process_request(self, request):
        set_current_operator(None)
        # 注入客户端 IP 和设备信息到日志过滤器
        from apps.common.logfilter import set_request_device, set_request_ip
        set_request_ip(_client_ip(request))
        set_request_device(_simplify_ua(request.headers.get("User-Agent", "")))

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return
        token = auth[7:]
        try:
            from apps.auth.authentication import decode_jwt_payload

            payload = decode_jwt_payload(token)
            if payload:
                set_current_operator(
                    {
                        "id": payload.get("sub"),
                        "username": payload.get("username"),
                        "role": payload.get("role"),
                        "competitionId": payload.get("cid"),
                    }
                )
        except Exception:  # noqa: BLE001 - 上下文注入失败不影响鉴权
            return


# ==================== 登录限流（对应 login-throttle.ts） ====================
# 失败累计：10 次/5 分钟 → 锁定 15 分钟；成功时清零。
_locks: dict[tuple[str, str], dict] = defaultdict(
    lambda: {"fails": 0, "first_at": 0.0, "locked_until": 0.0}
)
_FAIL_WINDOW = 5 * 60  # 5 分钟
_FAIL_THRESHOLD = 10
_LOCK_DURATION = 15 * 60  # 15 分钟
_CLEANUP_INTERVAL = 10 * 60  # 10 分钟清理一次过期条目
_last_cleanup = 0.0


def _cleanup_locks() -> None:
    """清理过期的限流条目，防止内存无限增长。"""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    expired = [
        k for k, v in _locks.items()
        if now - v["first_at"] > _FAIL_WINDOW and now > v["locked_until"]
    ]
    for k in expired:
        _locks.pop(k, None)


def record_login_failure(ip: str, username: str) -> None:
    _cleanup_locks()
    key = (ip, username)
    state = _locks[key]
    now = time.time()
    if now - state["first_at"] > _FAIL_WINDOW:
        state["fails"] = 0
        state["first_at"] = now
    state["fails"] += 1
    if state["fails"] >= _FAIL_THRESHOLD:
        state["locked_until"] = now + _LOCK_DURATION


def record_login_success(ip: str, username: str) -> None:
    _locks.pop((ip, username), None)


def is_login_locked(ip: str, username: str) -> bool:
    state = _locks.get((ip, username))
    if not state:
        return False
    return time.time() < state["locked_until"]


class LoginRateLimitMiddleware(MiddlewareMixin):
    """仅拦截 POST /api/auth/login，锁定期间返回 429。"""

    def process_request(self, request):
        if request.method == "POST" and request.path == "/api/auth/login":
            ip = _client_ip(request)
            username = ""
            try:
                import json

                body = json.loads(request.body or b"{}")
                username = body.get("username", "")
            except Exception:  # noqa: BLE001
                pass
            if is_login_locked(ip, username):
                from django.http import JsonResponse

                return JsonResponse(
                    {"code": 429, "message": "登录尝试过于频繁，请 15 分钟后再试", "data": None},
                    status=429,
                )
        return None


