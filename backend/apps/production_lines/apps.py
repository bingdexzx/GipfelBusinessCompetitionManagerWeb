from django.apps import AppConfig


class ProductionLinesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production_lines"
    label = "production_lines"
