"""审计日志。

- 写操作审计：通过 Django signals（post_save/post_delete）触发
- 异常上下文审计：exception_handler 调用 log_exception
- changes 脱敏（密码/令牌等字段）
"""
from __future__ import annotations

import json
import logging
from typing import Any
from apps.common.helpers import client_ip as _client_ip

logger = logging.getLogger("gipfel")


# ==================== 脱敏 ====================
_SENSITIVE_KEYS = {
    "password",
    "passwordhash",
    "password_hash",  # User 模型真实字段名（bcrypt 哈希），不可明文入审计库
    "token",
    "authorization",
    "secret",
    "jwt",
    "accesstoken",
    "refreshtoken",
}


def sanitize_changes(data: Any) -> Any:
    """递归脱敏敏感字段（值替换为 ***REDACTED***）。"""
    if isinstance(data, dict):
        return {
            k: (
                "***REDACTED***"
                if k.lower() in _SENSITIVE_KEYS
                else sanitize_changes(v)
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [sanitize_changes(x) for x in data]
    return data


# ==================== 审计写入 ====================
def log_write(
    *,
    model: str,
    action: str,
    record_id: str | None = None,
    changes: Any = None,
    competition_id: int | None = None,
) -> None:
    """写操作审计落库。"""
    operator = get_current_operator_safe()
    try:
        from apps.audit.models import AuditLog

        AuditLog.objects.create(
            kind="write",
            operator_id=operator.get("id") if operator else None,
            operator_name=operator.get("username") if operator else None,
            action=action,  # 如 "Material:create"
            model=model,
            record_id=str(record_id) if record_id is not None else None,
            competition_id=competition_id,
            changes=json.dumps(sanitize_changes(changes), ensure_ascii=False)
            if changes is not None
            else None,
        )
    except Exception:  # noqa: BLE001 - 审计失败不阻断主流程
        logger.debug("写操作审计写入失败", exc_info=True)


def log_exception(request, exc, response) -> None:
    """异常上下文审计落库。"""
    try:
        from apps.audit.models import AuditLog

        operator = get_current_operator_safe()
        status_code = getattr(response, "status_code", 500) if response else 500
        ip = _client_ip(request)
        request_id = (
            request.headers.get("X-Request-Id") if request else None
        )
        error_summary = str(exc)[:500]
        AuditLog.objects.create(
            kind="error",
            operator_id=operator.get("id") if operator else None,
            operator_name=operator.get("username") if operator else None,
            action=request.method if request else "UNKNOWN",
            model=None,
            record_id=None,
            competition_id=operator.get("competitionId") if operator else None,
            changes=None,
            status_code=status_code,
            error_summary=error_summary,
            ip=ip,
            request_id=request_id,
        )
    except Exception:  # noqa: BLE001
        logger.debug("异常审计写入失败", exc_info=True)


def get_current_operator_safe() -> dict | None:
    try:
        from .middleware import get_current_operator

        return get_current_operator()
    except Exception:  # noqa: BLE001
        return None


