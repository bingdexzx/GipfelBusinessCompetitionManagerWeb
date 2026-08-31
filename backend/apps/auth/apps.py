"""认证应用配置：对应原 NestJS auth.module + AuthController + JwtStrategy。

ready() 中连接 post_migrate 信号以在迁移完成后种子写入默认超管，
避免在表结构尚未就绪时访问数据库（原 NestJS 在 onModuleInit 种子写入）。
"""
from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.auth"
    # label 显式取 "gipfel_auth"：避免与 django.contrib.auth（label="auth"）冲突，
    # 二者同时存在于 INSTALLED_APPS 时默认 label 重复会导致启动报错。
    label = "gipfel_auth"

    def ready(self):
        # 延迟导入，避免在应用注册阶段触发模型加载
        from .bootstrap import seed_default_admin

        # 不限定 sender：post_migrate 在全部迁移应用完毕后对每个 app 触发，
        # 首次触发即建默认超管，后续被 exists() 守卫幂等跳过。
        post_migrate.connect(seed_default_admin)
