"""默认超管种子写入：对应原 NestJS onModuleInit 中的 ensureSeedAdmin。

- 仅当 users 表为空时创建 username="admin" 的 SUPER_ADMIN
- 密码取自环境变量 SEED_ADMIN_PASSWORD（默认 admin123）
- 默认标记 must_change_password=True，强制首登改密（与原行为一致）
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("gipfel")


def seed_default_admin(sender, **kwargs):
    """迁移完成后，若无任何用户则写入默认超管。

    幂等：已存在用户则直接返回。post_migrate 对每个 app 各触发一次，
    故不限定 sender——首次触发即在全部迁移应用完毕后建表，后续触发被
    exists() 守卫跳过。
    """
    from apps.users.models import User

    try:
        if User.objects.exists():
            return
    except Exception:  # noqa: BLE001 - 表未就绪等情况跳过种子写入
        logger.debug("种子写入前查询用户表失败，跳过默认超管创建")
        return

    password = getattr(settings, "SEED_ADMIN_PASSWORD", "admin123") or "admin123"
    try:
        User.objects.create_user(
            username="admin",
            password=password,
            role="SUPER_ADMIN",
            display_name="超级管理员",
            must_change_password=True,
        )
    except Exception:  # noqa: BLE001 - 种子写入失败不阻断 migrate
        logger.debug("默认超级管理员账号创建失败", exc_info=True)
        return
    logger.info("已创建默认超级管理员账号 admin（请尽快修改初始密码）")
