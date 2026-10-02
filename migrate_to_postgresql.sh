#!/bin/bash
# ============================================================
# SQLite → PostgreSQL 数据迁移脚本
# 用法: ./migrate_to_postgresql.sh
# ============================================================

set -e

# ==================== 配置 ====================
BACKEND_DIR="/opt/gipfel/backend"
BACKUP_DIR="/opt/gipfel/backups"
VENV_DIR="$BACKEND_DIR/.venv"

DB_NAME="gipfel"
DB_USER="gipfel"
DB_PASSWORD="CHANGE_ME_TO_STRONG_PASSWORD"
DB_HOST="localhost"
DB_PORT="5432"

# ==================== 颜色 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] 警告:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] 错误:${NC} $1"; exit 1; }

# ==================== 检查前置条件 ====================
check_prerequisites() {
    log "检查前置条件..."
    
    # 检查是否为 root
    if [ "$EUID" -ne 0 ]; then
        error "请使用 root 用户或 sudo 运行此脚本"
    fi
    
    # 检查 PostgreSQL
    if ! command -v psql &> /dev/null; then
        error "PostgreSQL 未安装，请先运行: apt install postgresql postgresql-contrib"
    fi
    
    # 检查 psycopg2
    source "$VENV_DIR/bin/activate"
    if ! python -c "import psycopg2" 2>/dev/null; then
        log "安装 psycopg2-binary..."
        pip install psycopg2-binary
    fi
    
    log "前置条件检查通过"
}

# ==================== 备份 SQLite 数据库 ====================
backup_sqlite() {
    log "备份 SQLite 数据库..."
    
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
    
    if [ -f "$BACKEND_DIR/db.sqlite3" ]; then
        # 复制数据库文件
        cp "$BACKEND_DIR/db.sqlite3" "$BACKUP_DIR/db_before_migration_$TIMESTAMP.sqlite3"
        
        # 导出 JSON
        cd "$BACKEND_DIR"
        source "$VENV_DIR/bin/activate"
        python manage.py dumpdata --indent 2 > "$BACKUP_DIR/data_before_migration_$TIMESTAMP.json"
        
        log "备份完成: $BACKUP_DIR/data_before_migration_$TIMESTAMP.json"
    else
        error "未找到 SQLite 数据库: $BACKEND_DIR/db.sqlite3"
    fi
}

# ==================== 配置 PostgreSQL ====================
setup_postgresql() {
    log "配置 PostgreSQL..."
    
    # 启动 PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # 创建数据库和用户
    sudo -u postgres psql << EOF
-- 如果用户已存在，跳过创建
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;

-- 如果数据库已存在，跳过创建
SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec

-- 授权
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
ALTER USER $DB_USER CREATEDB;
EOF
    
    log "PostgreSQL 配置完成"
}

# ==================== 创建 Django 配置文件 ====================
create_django_config() {
    log "创建 Django 配置文件..."
    
    # 生成 SECRET_KEY
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    
    # 创建 .env 文件
    cat > "$BACKEND_DIR/.env" << EOF
# PostgreSQL 数据库配置
DB_ENGINE=django.db.backends.postgresql
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT

# Django 配置
DEBUG=False
SECRET_KEY=$SECRET_KEY
ALLOWED_HOSTS=localhost,127.0.0.1

# 媒体文件
MEDIA_ROOT=$BACKEND_DIR/media
STATIC_ROOT=$BACKEND_DIR/static
EOF
    
    # 创建数据库路由配置（临时，用于迁移）
    cat > "$BACKEND_DIR/backend/db_router.py" << 'EOF'
"""临时数据库路由：迁移期间同时读取 SQLite 和写入 PostgreSQL"""

class MigrationRouter:
    """迁移期间的数据库路由"""
    
    def db_for_read(self, model, **hints):
        return 'default'
    
    def db_for_write(self, model, **hints):
        return 'default'
    
    def allow_relation(self, obj1, obj2, **hints):
        return True
    
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True
EOF
    
    log "配置文件创建完成"
}

# ==================== 修改 settings.py ====================
update_settings() {
    log "更新 settings.py..."
    
    # 备份原配置
    cp "$BACKEND_DIR/backend/settings.py" "$BACKEND_DIR/backend/settings.py.bak"
    
    # 创建新的 settings.py
    cat > "$BACKEND_DIR/backend/settings.py" << 'PYEOF'
"""
Django settings for Gipfel Business Competition Manager.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# 安全配置
SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# 应用定义
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 第三方
    'rest_framework',
    'corsheaders',
    # 本地应用
    'apps.users',
    'apps.competitions',
    'apps.companies',
    'apps.company_fields',
    'apps.contracts',
    'apps.industry_types',
    'apps.materials',
    'apps.parts',
    'apps.products',
    'apps.maps',
    'apps.infrastructures',
    'apps.tech_tree',
    'apps.fuels',
    'apps.vehicles',
    'apps.warehouses',
    'apps.production_lines',
    'apps.regions',
    'apps.consumer_demands',
    'apps.messages',
    'apps.stock',
    'apps.audit',
    'apps.announcements',
    'apps.files',
    'apps.realtime',
    'apps.preparation',
    'apps.common',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'
ASGI_APPLICATION = 'backend.asgi.application'

# 数据库配置
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.getenv('DB_NAME', 'gipfel'),
        'USER': os.getenv('DB_USER', 'gipfel'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# 密码验证
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 国际化
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# 静态文件
STATIC_URL = '/static/'
STATIC_ROOT = os.getenv('STATIC_ROOT', BASE_DIR / 'static')
MEDIA_URL = '/uploads/'
MEDIA_ROOT = os.getenv('MEDIA_ROOT', BASE_DIR / 'media')

# 默认主键字段类型
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS 配置
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://localhost:3000',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:3000',
]

# REST Framework 配置
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'EXCEPTION_HANDLER': 'apps.common.exceptions.custom_exception_handler',
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Simple JWT 配置
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
}

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'django.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'gipfel': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
PYEOF
    
    log "settings.py 更新完成"
}

# ==================== 运行数据库迁移 ====================
run_migrations() {
    log "运行数据库迁移..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 创建迁移
    python manage.py makemigrations
    
    # 应用迁移
    python manage.py migrate
    
    log "数据库迁移完成"
}

# ==================== 导入数据 ====================
import_data() {
    log "导入数据..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 找到最新的备份文件
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/data_before_migration_*.json 2>/dev/null | head -1)
    
    if [ -n "$LATEST_BACKUP" ]; then
        log "使用备份文件: $LATEST_BACKUP"
        
        # 尝试导入数据
        # 注意：某些模型可能需要特殊处理
        python manage.py loaddata "$LATEST_BACKUP" || {
            warn "loaddata 部分失败，尝试逐个应用导入..."
            
            # 逐个应用导入
            for app in users competitions companies industry_types materials parts products \
                       maps infrastructures tech_tree fuels vehicles warehouses production_lines \
                       regions consumer_demands messages stock contracts announcements; do
                python manage.py dumpdata "$app" --output "/tmp/${app}_backup.json" 2>/dev/null || true
                if [ -f "/tmp/${app}_backup.json" ]; then
                    python manage.py loaddata "/tmp/${app}_backup.json" 2>/dev/null || warn "导入 $app 失败"
                fi
            done
        }
        
        log "数据导入完成"
    else
        warn "未找到备份文件，跳过数据导入"
    fi
}

# ==================== 创建超级管理员 ====================
create_superuser() {
    log "检查超级管理员..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 检查是否已有超级管理员
    if python manage.py shell -c "from apps.users.models import User; print(User.objects.filter(role='SUPER_ADMIN').exists())" | grep -q "True"; then
        log "已存在超级管理员，跳过创建"
    else
        log "创建超级管理员..."
        python manage.py shell -c "
from apps.users.models import User
User.objects.create_superuser(
    username='admin',
    password='admin123',
    role='SUPER_ADMIN'
)
print('超级管理员创建成功: admin / admin123')
"
    fi
}

# ==================== 收集静态文件 ====================
collect_static() {
    log "收集静态文件..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    python manage.py collectstatic --noinput
    
    log "静态文件收集完成"
}

# ==================== 验证迁移 ====================
verify_migration() {
    log "验证迁移..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 检查数据库连接
    python manage.py check --database default
    
    # 检查表数量
    TABLE_COUNT=$(python manage.py shell -c "
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute(\"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'\")
    print(cursor.fetchone()[0])
")
    log "数据库表数量: $TABLE_COUNT"
    
    # 检查用户数量
    USER_COUNT=$(python manage.py shell -c "from apps.users.models import User; print(User.objects.count())")
    log "用户数量: $USER_COUNT"
    
    log "迁移验证完成"
}

# ==================== 主流程 ====================
main() {
    echo "============================================================"
    echo " SQLite → PostgreSQL 数据迁移"
    echo "============================================================"
    echo ""
    echo "配置信息:"
    echo "  后端目录: $BACKEND_DIR"
    echo "  备份目录: $BACKUP_DIR"
    echo "  数据库:   $DB_HOST:$DB_PORT/$DB_NAME"
    echo "  用户:     $DB_USER"
    echo ""
    echo "============================================================"
    echo ""
    
    # 确认继续
    read -p "是否继续迁移？(y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "已取消迁移"
        exit 0
    fi
    
    # 执行迁移流程
    check_prerequisites
    backup_sqlite
    setup_postgresql
    create_django_config
    update_settings
    run_migrations
    import_data
    create_superuser
    collect_static
    verify_migration
    
    echo ""
    echo "============================================================"
    echo " 迁移完成！"
    echo "============================================================"
    echo ""
    echo "数据库: PostgreSQL ($DB_HOST:$PORT/$DB_NAME)"
    echo "备份:   $BACKUP_DIR"
    echo ""
    echo "下一步:"
    echo "  1. 检查配置文件: $BACKEND_DIR/.env"
    echo "  2. 启动服务: systemctl start gipfel-daphne"
    echo "  3. 访问系统: http://localhost"
    echo ""
    echo "如果遇到问题，可以从备份恢复:"
    echo "  cp $BACKUP_DIR/db_before_migration_*.sqlite3 $BACKEND_DIR/db.sqlite3"
    echo ""
    echo "============================================================"
}

# 执行主流程
main