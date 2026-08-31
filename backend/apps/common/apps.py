from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    label = "common"

    def ready(self):
        # 等全部 app populate 完，再对已注册模型统一 connect 写操作信号
        # （审计落库 + 实时广播）
        from .signals import connect_all_signals

        connect_all_signals()
