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

# ---------------- 防直连网关（与主后端共享 LOGVIEWER_SECRET_KEY 签发） ----------------
# index 视图据此校验前端按钮拼入 URL 的一次性令牌；缺失/无效/过期则拒绝访问。
# 盐必须与被签方（主后端 LogViewerTokenView）一致。
LOGVIEWER_GATE_SALT = "logviewer-gate"
# 令牌最长有效秒数（默认 120s，足够完成一次按钮跳转）
LOGVIEWER_GATE_MAX_AGE = int(os.environ.get("LOGVIEWER_GATE_MAX_AGE", "120"))
# 网关通过后写入会话的键名（signed_cookies 会话，无需数据库）
LOGVIEWER_GATE_SESSION_KEY = "lv_gate"

# ---------------- 反向代理（nginx 整站代理到 127.0.0.1:8121；公网 8120 由 nginx 监听反代） ----------------
# 让日志查看器正确识别 HTTPS（nginx 终止 TLS 后转发 X-Forwarded-Proto）
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# 会话/CSRF cookie 是否标记 Secure：默认 False（兼容当前 HTTP 部署，避免网关会话 cookie
# 在 HTTP 下不被浏览器存储导致反复要求令牌）；启用 HTTPS 后请将 LOGVIEWER_SECURE_COOKIES=true。
_SECURE_COOKIES = os.environ.get("LOGVIEWER_SECURE_COOKIES", "false").lower()
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = (_SECURE_COOKIES == "true")

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

# 与主服务(backend)使用不同的 cookie 名称，避免同主机(localhost)下的命名冲突：
# 主服务把 csrftoken 设为 HttpOnly，会覆盖本服务前端需要读取的可读 csrftoken，
# 导致前端读不到 token → 登录 403「CSRF token ... incorrect length」；
# 同理 sessionid 也会互相覆盖，导致登录成功后会话立即丢失。
CSRF_COOKIE_NAME = "lv_csrftoken"
SESSION_COOKIE_NAME = "lv_sessionid"
CSRF_COOKIE_HTTPONLY = False  # 显式：前端 JS 需读取 csrftoken 再写入 X-CSRFToken 头

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
