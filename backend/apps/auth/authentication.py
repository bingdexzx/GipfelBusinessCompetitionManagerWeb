"""JWT 认证：对应原 NestJS JwtStrategy + AuthGuard。

- HS256 签名 + issuer/audience 校验（与原 jwt.module 配置一致）
- 校验 tokenVersion（顶号下线：payload.tv ≠ user.token_version → 401）
- 强制改密拦截：must_change_password=true 时除改密接口外全部拒绝
- 暴露 decode_jwt_payload（供 OperatorContextMiddleware 注入上下文，失败不阻断）
- 暴露 create_jwt（供 LoginView 签发）
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from rest_framework import authentication, exceptions

logger = logging.getLogger("gipfel")

_ALGORITHM = "HS256"

# 强制改密放行路径（仅改密接口允许在 must_change_password=true 时通过）
_CHANGE_PASSWORD_PATHS = ("/api/auth/change-password",)


# ==================== Token 编解码 ====================
def _expires_in() -> datetime:
    """根据 JWT_EXPIRES_IN（如 '24h'）计算过期时间。"""
    value = getattr(settings, "JWT_EXPIRES_IN", "24h")
    import re

    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", str(value))
    if not m:
        return datetime.now(timezone.utc) + timedelta(hours=24)
    n = int(m.group(1))
    unit = m.group(2)
    delta = {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]
    return datetime.now(timezone.utc) + delta


def create_jwt(user) -> str:
    """签发 JWT，payload 与原 NestJS 一致：{sub, username, role, tv, cid}。

    tv = token_version，用于顶号下线判定；cid = competitionId。
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.pk),
        "username": user.username,
        "role": user.role,
        "tv": user.token_version,
        "cid": getattr(user, "competition_id", None),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": _expires_in(),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)
    # PyJWT >=2 返回 str；兼容旧版返回 bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def decode_jwt_payload(token: str) -> dict | None:
    """解码并校验 JWT，失败返回 None（不抛异常，供上下文中间件安全调用）。"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
    except jwt.PyJWTError:
        return None
    except Exception:  # noqa: BLE001
        return None


# ==================== DRF 认证类 ====================
class JWTAuthentication(authentication.BaseAuthentication):
    """自定义 JWT 认证：复用 SimpleJWT 的 ALGORITHM/ISSUER/AUDIENCE 配置。"""

    keyword = "Bearer"

    def authenticate(self, request):
        token = self._extract_token(request)
        if token is None:
            # 无凭据：交给 IsAuthenticated 权限层处理（最终 401）
            return None

        payload = decode_jwt_payload(token)
        if payload is None:
            raise exceptions.AuthenticationFailed(
                "登录已过期，请重新登录", code="expired"
            )

        user = self._get_user(payload)
        if user is None:
            raise exceptions.AuthenticationFailed(
                "登录已过期，请重新登录", code="invalid_user"
            )

        # 顶号下线：token 中 tv 与用户当前 token_version 不一致
        if payload.get("tv") != user.token_version:
            raise exceptions.AuthenticationFailed(
                "账号已在其他设备登录", code="token_version_mismatch"
            )

        # 强制改密：除改密接口外全部拦截
        if getattr(user, "must_change_password", False) and not _is_change_password_endpoint(
            request
        ):
            raise exceptions.AuthenticationFailed(
                "账号需先修改初始密码", code="must_change_password"
            )

        return (user, token)

    def authenticate_header(self, request):
        return self.keyword

    # ---------- 辅助 ----------
    def _extract_token(self, request) -> str | None:
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        parts = header.split()
        if len(parts) == 2 and parts[0].lower() == self.keyword.lower():
            return parts[1].strip()
        return None

    def _get_user(self, payload: dict):
        sub = payload.get("sub")
        if not sub:
            return None
        from apps.users.models import User

        try:
            return User.objects.get(pk=sub)
        except User.DoesNotExist:
            return None
        except Exception:  # noqa: BLE001
            return None


def _is_change_password_endpoint(request) -> bool:
    """判断当前请求是否指向改密接口（路径尾匹配，兼容 include 前缀）。"""
    path = request.path or ""
    return path.endswith(_CHANGE_PASSWORD_PATHS)
