#!/usr/bin/env python
"""日志查看器独立服务入口。

与主线 Django 服务（端口 8000）完全解耦：复用同一份 db.sqlite3 中的
django.contrib.auth.User，以 is_superuser 校验「Django 后台超级管理员」账号密码，
从而与 /admin 登录凭据保持一致。日志文件读取主服务写入的 backend/logs/gipfel.log。

启动：python manage.py runserver 8120  （端口由 scripts/start_logviewer.py 从 .env 读取）
"""
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "logviewer.settings")
    # 将本目录加入 sys.path，使 logviewer 包可被导入
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
