#!/bin/bash
# ============================================================
# Gipfel PostgreSQL 一键迁移脚本
# 
# 使用方法：
#   1. 通过 git 拉取最新代码
#   2. 修改下方数据库密码配置
#   3. 执行: bash deploy/migrate-to-postgresql.sh
#
# 作者：MiMo
# 版本：v1.0
# ============================================================

set -e

# ==================== 请修改以下配置 ====================

# 数据库密码（必须修改！）
DB_PASSWORD="YourPassword123!"

# 数据库配置（一般不需要修改）
DB_NAME="gipfel"
DB_USER="gipfel"
DB_HOST="127.0.0.1"
DB_PORT="5432"

# ==================== 配置结束 ====================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 项目路径
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 打印函数
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# 显示标题
echo ""
echo "============================================================"
echo "  Gipfel PostgreSQL 一键迁移脚本"
echo "============================================================"
echo ""

# 检查密码是否修改
if [ "$DB_PASSWORD" = "YourPassword123!" ]; then
    error "请先修改脚本中的数据库密码！\n   编辑文件: deploy/migrate-to-postgresql.sh\n   修改第 12 行: DB_PASSWORD=\"你的密码\""
fi

# ==================== 1. 检查环境 ====================
info "检查运行环境..."

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    error "请使用 root 用户运行此脚本: sudo bash deploy/migrate-to-postgresql.sh"
fi

# 检查项目目录
if [ ! -d "$BACKEND_DIR" ]; then
    error "项目目录不存在: $BACKEND_DIR"
fi

# 检查 SQLite 数据库
if [ ! -f "$BACKEND_DIR/db.sqlite3" ]; then
    error "SQLite 数据库不存在: $BACKEND_DIR/db.sqlite3"
fi

# 检查 PostgreSQL
if ! command -v psql &> /dev/null; then
    warn "PostgreSQL 未安装，正在安装..."
    apt update
    apt install -y postgresql postgresql-client libpq-dev python3-dev
    systemctl start postgresql
    systemctl enable postgresql
fi

# 检查 PostgreSQL 服务
if ! systemctl is-active --quiet postgresql; then
    info "启动 PostgreSQL..."
    systemctl start postgresql
fi

success "环境检查通过"
echo ""

# ==================== 2. 备份数据 ====================
info "备份现有数据..."

mkdir -p "$BACKUP_DIR"

# 备份 SQLite
cp "$BACKEND_DIR/db.sqlite3" "$BACKUP_DIR/db.sqlite3.backup.$TIMESTAMP"
success "SQLite 备份完成: db.sqlite3.backup.$TIMESTAMP"

# 备份配置文件
cp "$BACKEND_DIR/backend/settings.py" "$BACKUP_DIR/settings.py.backup.$TIMESTAMP"
success "配置文件备份完成: settings.py.backup.$TIMESTAMP"

# 导出数据
cd "$BACKEND_DIR"
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

info "导出数据（这可能需要几分钟）..."
python manage.py dumpdata --indent 2 --output "$BACKUP_DIR/data_export_$TIMESTAMP.json"
success "数据导出完成: data_export_$TIMESTAMP.json"
echo ""

# ==================== 3. 创建数据库 ====================
info "创建 PostgreSQL 数据库..."

# 检查用户是否存在
USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null || echo "0")
if [ "$USER_EXISTS" != "1" ]; then
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null
    success "创建数据库用户: $DB_USER"
else
    warn "用户 $DB_USER 已存在，跳过创建"
fi

# 检查数据库是否存在
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null || echo "0")
if [ "$DB_EXISTS" != "1" ]; then
    sudo -u postgres psql -c "
        CREATE DATABASE $DB_NAME 
            OWNER $DB_USER
            ENCODING 'UTF8'
            TEMPLATE template0;
    " 2>/dev/null
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null
    success "创建数据库: $DB_NAME"
else
    warn "数据库 $DB_NAME 已存在，跳过创建"
fi
echo ""

# ==================== 4. 安装依赖 ====================
info "安装 Python 依赖..."

cd "$BACKEND_DIR"
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

pip install psycopg2-binary -q
success "安装 psycopg2 完成"
echo ""

# ==================== 5. 修改配置 ====================
info "修改 Django 配置..."

# 使用 Python 修改配置文件
python3 << EOF
import re

settings_file = '$BACKEND_DIR/backend/settings.py'

with open(settings_file, 'r') as f:
    content = f.read()

# 新的数据库配置
new_db_config = '''# ==================== 数据库 ====================
# PostgreSQL 配置
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "$DB_NAME",
        "USER": "$DB_USER",
        "PASSWORD": "$DB_PASSWORD",
        "HOST": "$DB_HOST",
        "PORT": "$DB_PORT",
        "OPTIONS": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",
        },
        "CONN_MAX_AGE": 600,
    }
}'''

# 替换数据库配置
pattern = r'# ==================== 数据库 ====================.*?(?=# ==================== [^=])'
content = re.sub(pattern, new_db_config.strip(), content, flags=re.DOTALL)

with open(settings_file, 'w') as f:
    f.write(content)

print("配置更新完成")
EOF

success "Django 配置更新完成"
echo ""

# ==================== 6. 运行迁移 ====================
info "运行数据库迁移..."

cd "$BACKEND_DIR"
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python manage.py migrate --noinput
success "数据库迁移完成"
echo ""

# ==================== 7. 导入数据 ====================
info "导入数据到 PostgreSQL..."

IMPORT_FILE=$(ls -t "$BACKUP_DIR"/data_export_*.json 2>/dev/null | head -1)

if [ -z "$IMPORT_FILE" ]; then
    error "未找到导出文件"
fi

python manage.py loaddata "$IMPORT_FILE"
success "数据导入完成"
echo ""

# ==================== 8. 验证数据 ====================
info "验证迁移结果..."

python manage.py shell -c "
from apps.users.models import User
from apps.competitions.models import Competition

users = User.objects.count()
competitions = Competition.objects.count()

print(f'用户数量: {users}')
print(f'比赛数量: {competitions}')

if users > 0:
    print('✓ 数据验证通过')
else:
    print('✗ 警告：没有用户数据')
"

success "数据验证完成"
echo ""

# ==================== 9. 更新日志查看器 ====================
info "更新日志查看器配置..."

LOGVIEWER_SETTINGS="$BACKEND_DIR/logviewer/logviewer/settings.py"
if [ -f "$LOGVIEWER_SETTINGS" ]; then
    python3 << EOF
settings_file = '$LOGVIEWER_SETTINGS'

with open(settings_file, 'r') as f:
    content = f.read()

old_config = '''# 复用主服务数据库（含 django.contrib.auth_user）
DB_PATH = MAIN_DIR / "db.sqlite3"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DB_PATH),
    }
}'''

new_config = '''# 复用主服务数据库（PostgreSQL）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "$DB_NAME",
        "USER": "$DB_USER",
        "PASSWORD": "$DB_PASSWORD",
        "HOST": "$DB_HOST",
        "PORT": "$DB_PORT",
    }
}'''

content = content.replace(old_config, new_config)

with open(settings_file, 'w') as f:
    f.write(content)
EOF
    success "日志查看器配置更新完成"
else
    warn "日志查看器配置文件不存在，跳过"
fi
echo ""

# ==================== 10. 重启服务 ====================
info "重启服务..."

# 重启 PostgreSQL
systemctl restart postgresql
success "PostgreSQL 已重启"

# 重启 Nginx
if command -v nginx &> /dev/null; then
    nginx -t 2>/dev/null && systemctl restart nginx
    success "Nginx 已重启"
fi

# 重启 Daphne
pkill -f "daphne.*backend.asgi" 2>/dev/null || true
sleep 2

if [ -f "$PROJECT_DIR/deploy/start-daphne-workers.sh" ]; then
    bash "$PROJECT_DIR/deploy/start-daphne-workers.sh"
else
    cd "$BACKEND_DIR"
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi
    nohup daphne -b 127.0.0.1 -p 8000 backend.asgi:application > /var/log/daphne/daphne.log 2>&1 &
fi
success "Daphne 已重启"
echo ""

# ==================== 完成 ====================
echo "============================================================"
echo "  ✓ 迁移完成！"
echo "============================================================"
echo ""
echo "备份位置: $BACKUP_DIR/"
echo "  - SQLite: db.sqlite3.backup.$TIMESTAMP"
echo "  - 数据: data_export_$TIMESTAMP.json"
echo "  - 配置: settings.py.backup.$TIMESTAMP"
echo ""
echo "数据库信息:"
echo "  - 主机: $DB_HOST:$DB_PORT"
echo "  - 数据库: $DB_NAME"
echo "  - 用户: $DB_USER"
echo ""
echo "下一步:"
echo "  1. 测试 API: curl http://127.0.0.1:8000/api/health"
echo "  2. 压测验证: 使用本地 stress-test.bat"
echo ""
echo "如需回滚:"
echo "  cp $BACKUP_DIR/settings.py.backup.$TIMESTAMP $BACKEND_DIR/backend/settings.py"
echo "  systemctl restart nginx"
echo "============================================================"