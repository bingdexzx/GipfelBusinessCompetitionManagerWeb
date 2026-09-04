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

# SECRET_KEY：日志查看器会话使用签名 cookie（signed_cookies），密钥一旦泄露即可伪造
# 管理员会话。故缺失/为空时直接拒绝启动（fail-fast），由部署脚本生成强随机
# LOGVIEWER_SECRET_KEY（与主后端共享同一值）。不再内置任何可用弱默认值（修复 C1 会话可伪造）。
# 本地开发：与主后端同源读 backend/.env（dotenv 默认不覆盖已存在的环境变量，
# 生产通过 systemd 注入的值仍优先）。
try:
    from dotenv import load_dotenv

    load_dotenv(MAIN_DIR / ".env")
except ImportError:
    pass
_LOGVIEWER_SECRET_KEY = (os.environ.get("LOGVIEWER_SECRET_KEY") or "").strip()
if not _LOGVIEWER_SECRET_KEY:
    raise RuntimeError(
        "环境变量 LOGVIEWER_SECRET_KEY 缺失：日志查看器会话基于签名 cookie，必须使用强随机密钥"
        "（与主后端共享同一值）。请通过 deploy-linux.sh 生成，或手动设置 "
        "LOGVIEWER_SECRET_KEY=$(openssl rand -base64 32)。"
    )
SECRET_KEY = _LOGVIEWER_SECRET_KEY

# DEBUG 默认 False（生产安全）；本地开发可设 LOGVIEWER_DEBUG=true
DEBUG = os.environ.get("LOGVIEWER_DEBUG", "false").lower() == "true"

# ---------------- 防直连网关（与主后端共享 LOGVIEWER_SECRET_KEY 签发） ----------------
# index 视图据此校验前端按钮拼入 URL 的一次性令牌；缺失/无效/过期则跳转回前端。
# 盐必须与被签方（主后端 LogViewerTokenView）一致。
LOGVIEWER_GATE_SALT = "logviewer-gate"
# 令牌最长有效秒数（默认 120s，足够完成一次按钮跳转）
LOGVIEWER_GATE_MAX_AGE = int(os.environ.get("LOGVIEWER_GATE_MAX_AGE", "120"))
# 直连（无有效令牌）时自动跳转回的前端主站地址；缺省按请求 Host 推导
# （日志查看器挂在 log.<域名> 或 :8120，前端主站在 <域名> 或 :80，见 views._frontend_url）。
LOGVIEWER_FRONTEND_URL = os.environ.get("LOGVIEWER_FRONTEND_URL", "").strip()

# ---------------- 反向代理（nginx 整站代理到 127.0.0.1:8121；公网 8120 由 nginx 监听反代） ----------------
# 让日志查看器正确识别 HTTPS（nginx 终止 TLS 后转发 X-Forwarded-Proto）
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# 外网可达地址（部署脚本写入 LOG_VIEWER_PUBLIC_URL），用于推导 ALLOWED_HOSTS 与
# 是否启用 Secure cookie（M1）。
_LV_URL = os.environ.get("LOG_VIEWER_PUBLIC_URL", "").strip()

# 会话/CSRF cookie 是否标记 Secure：HTTPS 部署（LOG_VIEWER_PUBLIC_URL 为 https）自动启用；
# 纯 HTTP 开发可经 LOGVIEWER_SECURE_COOKIES=false 显式关闭（默认跟随外网地址 scheme）。
_SECURE_COOKIES = os.environ.get("LOGVIEWER_SECURE_COOKIES", "").strip().lower()
if not _SECURE_COOKIES:
    _SECURE_COOKIES = "true" if _LV_URL.startswith("https") else "false"
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = (_SECURE_COOKIES == "true")

# ALLOWED_HOSTS：优先由 LOG_VIEWER_PUBLIC_URL 推导外网可达主机，再补回环地址；
# 亦可通过 LOGVIEWER_ALLOWED_HOSTS（逗号分隔）显式追加。不再通配 "*"（M1）。
_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "::1"]
if _LV_URL:
    from urllib.parse import urlparse as _urlparse

    _p = _urlparse(_LV_URL)
    if _p.netloc:
        _ALLOWED_HOSTS.append(_p.netloc)
_EXTRA_HOSTS = os.environ.get("LOGVIEWER_ALLOWED_HOSTS", "").strip()
if _EXTRA_HOSTS:
    _ALLOWED_HOSTS.extend(h.strip() for h in _EXTRA_HOSTS.split(",") if h.strip())
ALLOWED_HOSTS = _ALLOWED_HOSTS

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

# ---------------- CSRF 受信来源 ----------------
# Django 4+ 对同源 POST 有「Origin == scheme://get_host() 即放行」的同源自动放行逻辑；
# 但 nginx 反代若把 Host 设成不含端口（$host），get_host() 会丢掉 :8120，导致与浏览器
# Origin(http://IP:8120) 不一致而 403。nginx 模板已改为透传 $host:$server_port 修复该问题。
# 此处再静态预置受信来源作为双保险：从 .env 的 LOG_VIEWER_PUBLIC_URL 推导
# （deploy 脚本写入，含正确 scheme://host:port），并补回环地址便于服务器本机运维。
CSRF_TRUSTED_ORIGINS = []
if _LV_URL:
    from urllib.parse import urlparse as _urlparse

    _p = _urlparse(_LV_URL)
    if _p.scheme and _p.netloc:
        CSRF_TRUSTED_ORIGINS.append(f"{_p.scheme}://{_p.netloc}")
CSRF_TRUSTED_ORIGINS += [
    "http://127.0.0.1:8121",
    "https://127.0.0.1:8121",
    "http://localhost:8121",
    "https://localhost:8121",
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
