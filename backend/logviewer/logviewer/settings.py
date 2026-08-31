"""日志查看器服务配置。

刻意保持精简独立：
- 复用同一 db.sqlite3（读取 django.contrib.auth.User，校验 is_superuser）
- 不接入主服务的 JWT / 业务 users 表，仅认「Django 后台超级管理员」
- 会话使用 signed_cookies，无需 django_session 表，也无需自身 migrate
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/logviewer/

# 主服务所在目录（backend/），日志与数据库均在此处
MAIN_DIR = BASE_DIR.parent

SECRET_KEY = os.environ.get("LOGVIEWER_SECRET_KEY", "logviewer-dev-insecure-key-change-me")

DEBUG = os.environ.get("LOGVIEWER_DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = ["*"]  # 内部工具，允许任意主机；生产可改为具体域名

# 端口：由 .env 的 LOG_VIEWER_PORT 决定（默认 8120）；Windows 开发由 scripts/start-dev.bat 拉起
LOG_VIEWER_PORT = int(os.environ.get("LOG_VIEWER_PORT", "8120"))

# 复用主服务数据库（含 django.contrib.auth_user）
DB_PATH = MAIN_DIR / "db.sqlite3"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DB_PATH),
    }
}

# 日志目录：默认指向主服务写入的 backend/logs（与主服务 LOG_DIR 默认一致）
LOG_DIR = Path(os.environ.get("LOG_DIR", str(MAIN_DIR / "logs")))
LOG_FILE_NAME = os.environ.get("LOG_FILE_NAME", "gipfel.log")

# 关闭这些内置 app 的迁移追踪，避免「未应用迁移」警告，直接复用主服务已建好的表
MIGRATION_MODULES = {
    "auth": None,
    "contenttypes": None,
    "sessions": None,
    "admin": None,
    "staticfiles": None,
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# 会话存于签名 cookie，不写库，无需迁移 django_session
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

ROOT_URLCONF = "logviewer.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": False,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "logviewer.wsgi.application"

# 静态资源：开发期由 staticfiles 直接托管（DEBUG=True）
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 仅允许本地读取日志目录内的文件，杜绝路径穿越
LOG_ALLOW_DIR = str(LOG_DIR)
