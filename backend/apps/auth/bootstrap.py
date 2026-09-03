"""默认超管种子写入。

首次 migrate 后自动写入两类超级管理员，均从 .env（SEED_ADMIN_*）读取凭据：
1. 业务超管 —— apps.users.User（表 `users`），前端 JWT 登录用，role=SUPER_ADMIN。
2. 后台超管 —— django.contrib.auth.User（表 `auth_user`，因 AUTH_USER_MODEL 未自定义），
   即 Django 管理后台 /admin 登录用的账号，必须 is_staff=True / is_superuser=True。

幂等：各自按「是否已有用户 / 指定用户名是否已存在」守卫跳过，重复 migrate 不会报错或覆盖。
post_migrate 在全部迁移应用完毕后对每个 app 各触发一次，故不限定 sender。
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("gipfel")


def _seed_vars():
    username = getattr(settings, "SEED_ADMIN_USERNAME", "admin") or "admin"
    email = getattr(settings, "SEED_ADMIN_EMAIL", "admin@example.com") or "admin@example.com"
    password = getattr(settings, "SEED_ADMIN_PASSWORD", "admin23") or "admin23"
    return username, email, password


def seed_default_admin(sender, **kwargs):
    """迁移完成后写入默认超管（业务 + 后台）。"""
    username, email, password = _seed_vars()

    # 1) 业务超管（前端 JWT 登录用）
    try:
        from apps.users.models import User as BizUser

        if not BizUser.objects.exists():
            BizUser.objects.create_user(
                username=username,
                password=password,
                role="SUPER_ADMIN",
                display_name="超级管理员",
                must_change_password=True,
            )
            logger.info("已创建业务默认超管 %s（前端登录用）", username)
    except Exception:  # noqa: BLE001 - 种子写入失败不阻断 migrate
        logger.debug("业务默认超管创建失败", exc_info=True)

    # 2) 后台超级管理员（Django 管理后台 /admin 登录用）
    try:
        from django.contrib.auth import get_user_model

        AuthUser = get_user_model()  # 未自定义 AUTH_USER_MODEL 时为 contrib.auth.User
        if not AuthUser.objects.filter(username=username).exists():
            AuthUser.objects.create_superuser(username, email, password)
            logger.info("已创建 Django 后台超级管理员 %s（/admin 登录用）", username)
    except Exception:  # noqa: BLE001 - 种子写入失败不阻断 migrate
        logger.debug("Django 后台超级管理员创建失败", exc_info=True)
