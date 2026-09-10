"""更新公告模型。

仅超级管理员可增删改；所有登录用户可读取。
"""
from django.db import models


class Announcement(models.Model):
    version = models.CharField(max_length=32, help_text="版本号，如 1.4.0")
    title = models.CharField(max_length=255, help_text="公告标题")
    date = models.CharField(max_length=16, help_text="发布日期 YYYY-MM-DD（展示用）")
    content = models.TextField(help_text="公告正文，支持受信任 HTML 片段")
    is_active = models.BooleanField(default=True, help_text="是否启用（停用后前端不展示）")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "announcements"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} (v{self.version})"
