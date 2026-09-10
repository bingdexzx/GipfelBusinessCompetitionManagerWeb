"""仪表盘自定义控件包模型。

控件包为 zip 文件，内含 manifest.json（元数据）+ component.js（Vue 组件）。
上传后由前端动态加载注册到仪表盘。
"""
from django.db import models


class WidgetPackage(models.Model):
    name = models.CharField(max_length=128, help_text="控件名称（来自 manifest.json）")
    widget_type = models.CharField(max_length=128, unique=True, help_text="控件类型标识（来自 manifest.json type）")
    description = models.TextField(blank=True, default="", help_text="控件说明")
    version = models.CharField(max_length=32, default="1.0.0", help_text="版本号")
    # manifest.json 原始内容（存数据库便于查询，无需每次读文件）
    manifest = models.JSONField(default=dict, help_text="manifest.json 原始内容")
    # zip 文件相对 MEDIA_ROOT 的路径
    file_path = models.CharField(max_length=512, help_text="zip 文件相对路径")
    # 解压后的目录相对路径（前端从此目录加载 component.js）
    extract_dir = models.CharField(max_length=512, help_text="解压目录相对路径")
    is_active = models.BooleanField(default=True, help_text="是否启用")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "widget_packages"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.widget_type})"
