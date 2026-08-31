"""审计日志序列化器：camelCase 对齐前端契约。

AuditLog.changes 在 DB 以 JSON 字符串（TextField，已脱敏）存储，序列化
输出为对象（无法解析时返回 None）。本序列化器只读（审计日志由
apps.common.audit.log_write/log_exception 写入，不通过 REST 创建）。
"""
from __future__ import annotations

import json

from .models import AuditLog


def _parse_json(value):
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


class AuditLogSerializer:
    """轻量序列化器：直接映射为前端 camelCase 字典。"""

    def __init__(self, instance=None, many: bool = False):
        self.instance = instance
        self.many = many

    @property
    def data(self):
        if self.many:
            return [self._to_dict(item) for item in self.instance]
        return self._to_dict(self.instance)

    @staticmethod
    def _to_dict(instance: AuditLog) -> dict:
        return {
            "id": instance.id,
            "kind": instance.kind,
            "operatorId": instance.operator_id,
            "operatorName": instance.operator_name,
            "action": instance.action,
            "model": instance.model,
            "recordId": instance.record_id,
            "competitionId": instance.competition_id,
            "changes": _parse_json(instance.changes),
            "statusCode": instance.status_code,
            "errorSummary": instance.error_summary,
            "ip": instance.ip,
            "requestId": instance.request_id,
            "createdAt": instance.created_at,
        }
