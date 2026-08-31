"""异常处理器：对应原 NestJS HttpExceptionFilter。

- 5xx 返回通用中文提示，不暴露堆栈
- 异常上下文入 AuditLog（脱敏）
- 4xx 返回后端明确中文消息
"""
from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

from .response import error

logger = logging.getLogger("gipfel")


class FieldWriteConflictException(APIException):
    """乐观锁冲突（409）。对应原 common/exceptions/field-write-conflict.exception.ts。"""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "数据冲突，请刷新后重试"
    default_code = "field_write_conflict"


class BusinessError(APIException):
    """业务异常：携带中文 message 与自定义状态码。"""

    def __init__(self, message: str, code: int = 400, status_code: int = 400):
        self.message = message
        self.err_code = code
        self.status_code = status_code
        super().__init__(detail=message, code=str(code))


def exception_handler(exc, context):
    """DRF 异常处理器：统一脱敏 + 包装为 {code,message,data:null}。"""
    response = drf_exception_handler(exc, context)

    # 写审计日志（异常上下文），脱敏由 audit 模块负责
    try:
        from .audit import log_exception

        request = context.get("request")
        log_exception(request, exc, response)
    except Exception:  # noqa: BLE001 - 审计失败不影响主流程
        logger.debug("异常审计写入失败", exc_info=True)

    if response is None:
        # 未被 DRF 接住的异常（500）
        logger.error("未处理异常", exc_info=exc)
        return _wrap(status.HTTP_500_INTERNAL_SERVER_ERROR, "服务器内部错误，请稍后重试")

    # DRF 标准异常
    if isinstance(exc, BusinessError):
        return _wrap(exc.status_code, exc.message)
    if isinstance(exc, FieldWriteConflictException):
        return _wrap(status.HTTP_409_CONFLICT, str(exc.detail))

    # DRF 默认异常（权限/认证/校验）
    message = _drf_message(exc, response)
    return _wrap(response.status_code, message)


def _wrap(code: int, message: str):
    from rest_framework.response import Response

    return Response(error(code, message, None), status=_http_status(code))


def _http_status(code: int) -> int:
    # 业务码尽量与 HTTP 状态对齐；不在常见范围时按 400 返回
    if 100 <= code < 600:
        return code
    return 400


def _drf_message(exc, response) -> str:
    """DRF 默认异常 → 中文提示。对应原 request.ts 的 statusText 映射。"""
    status_code = response.status_code
    detail = getattr(exc, "detail", None)

    if status_code == 401:
        # 优先采用后端明确提示（顶号）
        if isinstance(detail, str) and detail != "Authentication credentials were not provided.":
            return detail
        return "登录已过期，请重新登录"
    if status_code == 403:
        return "没有权限执行此操作"
    if status_code == 404:
        return "请求的资源不存在"
    if status_code == 409:
        return "数据冲突，请刷新后重试"
    if status_code == 422:
        # 校验错误：取首个字段的错误
        return _first_validation(detail) or "请求参数校验失败"
    if status_code == 400:
        return _first_validation(detail) or "请求参数错误，请检查输入"
    if isinstance(detail, str):
        return detail
    return _first_validation(detail) or f"请求失败（错误码 {status_code}）"


def _first_validation(detail: Any) -> str | None:
    """从 DRF 校验错误结构提取首个中文可读消息。"""
    if detail is None:
        return None
    if isinstance(detail, list):
        for item in detail:
            msg = _first_validation(item)
            if msg:
                return msg
        return None
    if isinstance(detail, dict):
        for v in detail.values():
            msg = _first_validation(v)
            if msg:
                return msg
        return None
    if isinstance(detail, str):
        return detail
    return None
