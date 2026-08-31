"""
Django 设置模块。

环境变量启动校验（fail-fast）：JWT_SECRET 未配置时直接抛异常拒绝启动，
与原 NestJS main.ts 的 zod 校验保持一致。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env（与原 NestJS dotenv/config 等价）
load_dotenv()


# ==================== 路径常量 ====================
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== 环境变量启动校验（fail-fast） ====================
# 对应原 server/src/main.ts 顶部的 zod 校验：JWT_SECRET 必填
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
if not JWT_SECRET:
    raise RuntimeError(
        "环境变量校验失败:\n  JWT_SECRET: JWT_SECRET is required"
    )


# ==================== 通用配置 ====================
SECRET_KEY = JWT_SECRET  # Django 自身 SECRET_KEY 复用 JWT_SECRET（生产应独立，迁移期简化）

DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = ["*"]  # CORS 与来源校验由自定义中间件统一管控，Django 层放行

PORT = int(os.environ.get("PORT", "8000"))

# JWT 配置（与原 main.ts / jwt.strategy.ts 一致）
JWT_ISSUER = os.environ.get("JWT_ISSUER", "gipfel-competition")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "gipfel-competition-client")
JWT_EXPIRES_IN = os.environ.get("JWT_EXPIRES_IN", "24h")
SEED_ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "admin123")

# 日志
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_DIR = Path(os.environ.get("LOG_DIR", "./logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 上传
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# CORS（未配置时仅本地/私网反射并带凭据，公网须白名单）
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "").strip()


# ==================== CORS 配置 ====================
# 对应原 main.ts 的 enableCors：本地/私网反射并带凭据，公网须白名单
def _resolve_cors_origins() -> list:
    if not CORS_ORIGIN:
        return []
    return [s.strip() for s in CORS_ORIGIN.split(",") if s.strip()]


CORS_ALLOWED_ORIGINS = []  # 不用静态白名单，走自定义校验
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = False


def cors_origin_validator(request_origin: str) -> bool:
    """自定义 CORS origin 校验器（在 apps.common.middleware 中接入）。

    返回 True 表示允许。
    """
    from apps.common.middleware import is_local_or_private_origin

    # 无 Origin：同源/本地调用，允许
    if not request_origin:
        return True
    origins = _resolve_cors_origins()
    allow_all = "*" in origins
    if origins and not allow_all:
        return request_origin in origins
    # 未配置或配置 *：仅本地/私网反射
    return is_local_or_private_origin(request_origin)


# 用信号在 corsheaders 之前接入自定义校验：通过中间件自行处理 OPTIONS 与响应头
# （corsheaders 的 CORS_ORIGIN_WHITELIST 走静态判断，无法动态反射，故自定义中间件接管）


# ==================== 应用注册 ====================
INSTALLED_APPS = [
    "daphne",  # ASGI server（置于 django.contrib.staticfiles 之前以接管 runserver）
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "corsheaders",
    # 本项目
    "apps.common",
    "apps.users",
    "apps.auth",
    "apps.competitions",
    "apps.materials",
    "apps.parts",
    "apps.products",
    "apps.tech_tree",
    "apps.maps",
    "apps.infrastructures",
    "apps.fuels",
    "apps.vehicles",
    "apps.warehouses",
    "apps.production_lines",
    "apps.industry_types",
    "apps.companies",
    "apps.company_fields",
    "apps.contracts",
    "apps.regions",
    "apps.consumer_demands",
    "apps.messages",
    "apps.stock",
    "apps.files",
    "apps.realtime",
    "apps.audit",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # 必须在 Common 之前
    "apps.common.cors.DynamicCorsMiddleware",  # 自定义 CORS 反射（接管 corsheaders 动态判断）
    "apps.common.middleware.SecurityHeadersMiddleware",
    "apps.common.middleware.OperatorContextMiddleware",
    "apps.common.middleware.LoginRateLimitMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"
ASGI_APPLICATION = "backend.asgi.application"


# ==================== 数据库 ====================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# ==================== 密码哈希 ====================
# 与原 bcryptjs cost=12 兼容
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
]


# ==================== DRF ====================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.auth.authentication.JWTAuthentication",  # 自定义 JWT（tokenVersion + issuer/audience）
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": None,  # 自定义分页（parsePagination 等价）
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": (
        "apps.common.response.JSONRenderer",  # 统一 {code,message,data} 包装
    ),
    "EXCEPTION_HANDLER": "apps.common.exceptions.exception_handler",
    "DEFAULT_FILTER_BACKENDS": (),
}

# 分页采用自定义 parsePagination（等价原 NestJS），DEFAULT_PAGINATION_CLASS=None 为有意为之，
# 静默 DRF 的 W001 检查（PAGE_SIZE 仅作为后备默认值）。
SILENCED_SYSTEM_CHECKS = ["rest_framework.W001"]

# ==================== SimpleJWT 配置（被自定义覆盖，此处仅设默认值） ====================
from datetime import timedelta  # noqa: E402


def _parse_expires(value: str) -> timedelta:
    """解析 '24h' / '30m' / '7d' 等 ms 库格式为 timedelta。"""
    import re

    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", value)
    if not m:
        return timedelta(hours=24)
    n = int(m.group(1))
    unit = m.group(2)
    return {  # noqa: E402
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]


SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": _parse_expires(JWT_EXPIRES_IN),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SECRET,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "TOKEN_TYPE": "access",
    "ISSUER": JWT_ISSUER,
    "AUDIENCE": JWT_AUDIENCE,
}


# ==================== 国际化 ====================
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True  # 保持时区感知（与原 Prisma DateTime 一致）


# ==================== 静态文件与上传 ====================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# /uploads 由自定义 URL 路由 + 中间件托管（CORP cross-origin）
MEDIA_URL = "/uploads/"
MEDIA_ROOT = UPLOAD_DIR

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ==================== 日志 ====================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file_rotate": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(LOG_DIR / "gipfel.log"),
            "when": "midnight",
            "backupCount": 14,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "file_rotate"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file_rotate"],
            "level": "INFO",
            "propagate": False,
        },
        "gipfel": {
            "handlers": ["console", "file_rotate"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}


# ==================== Session/Cookie（API 项目基本不用，保留默认） ====================
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
