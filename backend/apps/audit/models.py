"""审计日志模型：对应原 Prisma AuditLog。"""
from django.db import models


class AuditLog(models.Model):
    KIND_CHOICES = [("write", "write"), ("error", "error")]

    kind = models.CharField(max_length=16, default="write", choices=KIND_CHOICES)
    operator_id = models.IntegerField(null=True, blank=True)
    operator_name = models.CharField(max_length=128, null=True, blank=True)
    action = models.CharField(max_length=128)  # <Model>:<op> 或 HTTP 方法
    model = models.CharField(max_length=64, null=True, blank=True)
    record_id = models.CharField(max_length=64, null=True, blank=True)
    competition_id = models.IntegerField(null=True, blank=True)
    changes = models.TextField(null=True, blank=True)  # JSON 脱敏
    status_code = models.IntegerField(null=True, blank=True)
    error_summary = models.CharField(max_length=512, null=True, blank=True)
    ip = models.CharField(max_length=64, null=True, blank=True)
    request_id = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        indexes = [
            models.Index(fields=["kind", "created_at"]),
            models.Index(fields=["operator_id", "created_at"]),
            models.Index(fields=["model", "created_at"]),
            models.Index(fields=["request_id"]),
        ]

    def __str__(self):
        return f"[{self.kind}] {self.action} @ {self.created_at}"
