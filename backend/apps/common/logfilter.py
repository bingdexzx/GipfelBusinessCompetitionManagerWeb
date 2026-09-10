"""日志过滤器：把当前请求的操作员、客户端 IP 和设备信息（来自 OperatorContextMiddleware）
注入每条日志记录。

使主服务日志能体现「发起请求的用户」「来源 IP」「设备信息」，供日志查看器展示。
配合 backend/settings.py 的 verbose formatter 使用。

使用 contextvars（而非 threading.local）以兼容 Daphne ASGI 异步环境。
"""
from __future__ import annotations

import contextvars
import logging

from apps.common.middleware import get_current_operator

# 请求级别的上下文存储（中间件写入，过滤器读取）
# 使用 contextvars 兼容 ASGI 异步环境
_ip_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_ip", default="-")
_device_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_device", default="-")


def set_request_ip(ip: str) -> None:
    """由中间件调用，设置当前请求的客户端 IP。"""
    _ip_ctx.set(ip)


def get_request_ip() -> str:
    """获取当前请求的客户端 IP，无上下文时返回 '-'。"""
    return _ip_ctx.get()


def set_request_device(device: str) -> None:
    """由中间件调用，设置当前请求的设备信息（User-Agent 精简版）。"""
    _device_ctx.set(device)


def get_request_device() -> str:
    """获取当前请求的设备信息，无上下文时返回 '-'。"""
    return _device_ctx.get()


class OperatorFilter(logging.Filter):
    """为日志记录附加 operator、client_ip、device 字段。

    Django 的 dictConfig 通过 ``"()": "apps.common.logfilter.OperatorFilter"`` 实例化，
    过滤器在每条记录经过 handler 时执行，确保 %(operator)s、%(client_ip)s、%(device)s 总有值。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        op = get_current_operator()
        if op:
            record.operator = op.get("username") or op.get("id") or "-"
        else:
            record.operator = "-"
        record.client_ip = get_request_ip()
        record.device = get_request_device()
        return True
