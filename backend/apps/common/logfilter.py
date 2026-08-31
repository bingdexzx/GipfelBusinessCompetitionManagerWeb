"""日志过滤器：把当前请求的操作员（来自 OperatorContextMiddleware 的 contextvars）注入每条日志记录。

使主服务日志能体现「发起请求的用户」，供日志查看器展示。配合 backend/settings.py 的
verbose formatter（[{asctime}] {levelname} {name} [{operator}] {message}）使用。
"""
from __future__ import annotations

import logging

from apps.common.middleware import get_current_operator


class OperatorFilter(logging.Filter):
    """为日志记录附加 operator 字段（当前 JWT 用户），无请求上下文时为 '-'。

    Django 的 dictConfig 通过 ``"()": "apps.common.logfilter.OperatorFilter"`` 实例化，
    过滤器在每条记录经过 handler 时执行，确保 %(operator)s 总有值。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        op = get_current_operator()
        if op:
            # 优先用用户名，缺失时退回 id，仍缺失则占位 '-'
            record.operator = op.get("username") or op.get("id") or "-"
        else:
            record.operator = "-"
        return True
