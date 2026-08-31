from django.apps import AppConfig


class MessagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messages"
    # label 显式取 "gipfel_messages"：避免与 django.contrib.messages（label="messages"）冲突，
    # 二者同时存在于 INSTALLED_APPS 时默认 label 重复会导致启动报错。
    label = "gipfel_messages"
