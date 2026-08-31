"""科技树应用配置。"""
from django.apps import AppConfig


class TechTreeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tech_tree"
    label = "tech_tree"
