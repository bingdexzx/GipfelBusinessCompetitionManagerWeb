#!/bin/bash
# PostgreSQL 迁移脚本
# 自动化迁移过程，减少人为错误

set -e

# ==================== 配置 ====================
PROJECT_DIR="/opt/gipfel"
BACKEND_DIR="$PROJECT_DIR/backend"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 数据库配置（请修改为实际值）
DB_NAME="gipfel"
DB_USER="gipfel"
DB_PASSWORD="your_secure_password_here"  # 请修改！
DB_HOST="127.0.0.1"
DB_PORT="5432"

# ==================== 颜色输出 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# ==================== 检查前置条件 ====================
check_prerequisites() {
    info "检查前置条件..."
    
    # 检查是否为 root 用户
    if [ "$EUID" -ne 0 ]; then
        error "请使用 root 用户运行此脚本"
    fi
    
    # 检查 PostgreSQL 是否安装
    if ! command -v psql &> /dev/null; then
        error "PostgreSQL 未安装，请先运行: apt install postgresql postgresql-client libpq-dev"
    fi
    
    # 检查 PostgreSQL 是否运行
    if ! systemctl is-active --quiet postgresql; then
        warning "PostgreSQL 未运行，正在启动..."
        systemctl start postgresql
    fi
    
    # 检查项目目录
    if [ ! -d "$BACKEND_DIR" ]; then
        error "项目目录不存在: $BACKEND_DIR"
    fi
    
    # 检查 SQLite 数据库
    if [ ! -f "$BACKEND_DIR/db.sqlite3" ]; then
        error "SQLite 数据库不存在: $BACKEND_DIR/db.sqlite3"
    fi
    
    success "前置条件检查通过"
}

# ==================== 备份 SQLite ====================
backup_sqlite() {
    info "备份 SQLite 数据库..."
    
    mkdir -p "$BACKUP_DIR"
    BACKUP_FILE="$BACKUP_DIR/db.sqlite3.backup.$TIMESTAMP"
    
    cp "$BACKEND_DIR/db.sqlite3" "$BACKUP_FILE"
    
    success "SQLite 备份完成: $BACKUP_FILE"
    info "备份文件大小: $(du -h "$BACKUP_FILE" | cut -f1)"
}

# ==================== 创建数据库和用户 ====================
create_database() {
    info "创建 PostgreSQL 数据库和用户..."
    
    # 检查用户是否存在
    USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")
    if [ "$USER_EXISTS" != "1" ]; then
        sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
        success "数据库用户创建完成: $DB_USER"
    else
        warning "用户 $DB_USER 已存在，跳过创建"
    fi
    
    # 检查数据库是否存在
    DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")
    if [ "$DB_EXISTS" != "1" ]; then
        sudo -u postgres psql -c "
            CREATE DATABASE $DB_NAME 
                OWNER $DB_USER
                ENCODING 'UTF8'
                LC_COLLATE 'zh_CN.UTF-8'
                LC_CTYPE 'zh_CN.UTF-8'
                TEMPLATE template0;
        "
        sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
        success "数据库创建完成: $DB_NAME"
    else
        warning "数据库 $DB_NAME 已存在，跳过创建"
    fi
}

# ==================== 安装 Python 依赖 ====================
install_dependencies() {
    info "安装 Python 依赖..."
    
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    
    # 安装 psycopg2-binary
    pip install psycopg2-binary
    
    success "Python 依赖安装完成"
}

# ==================== 导出数据 ====================
export_data() {
    info "导出 SQLite 数据..."
    
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    
    EXPORT_FILE="$BACKUP_DIR/data_export_$TIMESTAMP.json"
    
    python manage.py dumpdata --indent 2 --output "$EXPORT_FILE"
    
    success "数据导出完成: $EXPORT_FILE"
    info "导出文件大小: $(du -h "$EXPORT_FILE" | cut -f1)"
}

# ==================== 修改配置 ====================
update_settings() {
    info "更新 Django 配置..."
    
    SETTINGS_FILE="$BACKEND_DIR/backend/settings.py"
    SETTINGS_BACKUP="$BACKUP_DIR/settings.py.backup.$TIMESTAMP"
    
    # 备份原配置
    cp "$SETTINGS_FILE" "$SETTINGS_BACKUP"
    
    # 使用 sed 替换数据库配置
    # 注意：这里使用 Python 脚本更安全，因为 sed 处理复杂文本可能出错
    python3 << 'PYTHON_SCRIPT'
import re

settings_file = '/opt/gipfel/backend/backend/settings.py'

with open(settings_file, 'r') as f:
    content = f.read()

# 新的数据库配置
new_db_config = '''
# ==================== 数据库 ====================
# PostgreSQL 配置（从 SQLite 迁移）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "gipfel",
        "USER": "gipfel",
        "PASSWORD": "your_secure_password_here",  # 请替换为实际密码
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",
        },
        "CONN_MAX_AGE": 600,
    }
}
'''

# 替换数据库配置部分
# 匹配从 "# ==================== 数据库 ====================" 到下一个 "# ===================="
pattern = r'# ==================== 数据库 ====================.*?(?=# ==================== [^=])'
content = re.sub(pattern, new_db_config.strip(), content, flags=re.DOTALL)

with open(settings_file, 'w') as f:
    f.write(content)

print("配置更新完成")
PYTHON_SCRIPT
    
    success "Django 配置更新完成"
    warning "请检查配置文件中的数据库密码是否正确！"
}

# ==================== 运行迁移 ====================
run_migrations() {
    info "运行数据库迁移..."
    
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    
    # 运行迁移
    python manage.py migrate
    
    success "数据库迁移完成"
}

# ==================== 导入数据 ====================
import_data() {
    info "导入数据到 PostgreSQL..."
    
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    
    EXPORT_FILE=$(ls -t "$BACKUP_DIR"/data_export_*.json | head -1)
    
    if [ -z "$EXPORT_FILE" ]; then
        error "未找到导出文件"
    fi
    
    python manage.py loaddata "$EXPORT_FILE"
    
    success "数据导入完成"
}

# ==================== 验证迁移 ====================
verify_migration() {
    info "验证迁移结果..."
    
    cd "$BACKEND_DIR"
    source .venv/bin/activate
    
    # 运行 Django 检查
    python manage.py check
    
    # 验证数据
    python manage.py shell -c "
from apps.users.models import User
from apps.competitions.models import Competition
from apps.contracts.models import Contract

users = User.objects.count()
competitions = Competition.objects.count()
contracts = Contract.objects.count()

print(f'用户数量: {users}')
print(f'比赛数量: {competitions}')
print(f'合同数量: {contracts}')

if users > 0:
    print('✓ 数据验证通过')
else:
    print('✗ 警告：没有用户数据')
"
    
    success "迁移验证完成"
}

# ==================== 更新日志查看器 ====================
update_logviewer() {
    info "更新日志查看器配置..."
    
    LOGVIEWER_SETTINGS="$BACKEND_DIR/logviewer/logviewer/settings.py"
    LOGVIEWER_BACKUP="$BACKUP_DIR/logviewer_settings.py.backup.$TIMESTAMP"
    
    if [ -f "$LOGVIEWER_SETTINGS" ]; then
        # 备份原配置
        cp "$LOGVIEWER_SETTINGS" "$LOGVIEWER_BACKUP"
        
        # 使用 sed 替换数据库配置
        python3 << 'PYTHON_SCRIPT'
settings_file = '/opt/gipfel/backend/logviewer/logviewer/settings.py'

with open(settings_file, 'r') as f:
    content = f.read()

# 替换数据库配置
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
        "NAME": "gipfel",
        "USER": "gipfel",
        "PASSWORD": "your_secure_password_here",  # 请替换为实际密码
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}'''

content = content.replace(old_config, new_config)

with open(settings_file, 'w') as f:
    f.write(content)

print("日志查看器配置更新完成")
PYTHON_SCRIPT
        
        success "日志查看器配置更新完成"
    else
        warning "日志查看器配置文件不存在，跳过"
    fi
}

# ==================== 重启服务 ====================
restart_services() {
    info "重启服务..."
    
    # 重启 PostgreSQL
    systemctl restart postgresql
    success "PostgreSQL 已重启"
    
    # 重启 Nginx
    nginx -t && systemctl restart nginx
    success "Nginx 已重启"
    
    # 重启 Daphne
    if [ -f "$PROJECT_DIR/deploy/start-daphne-workers.sh" ]; then
        bash "$PROJECT_DIR/deploy/start-daphne-workers.sh"
        success "Daphne 已重启"
    else
        warning "Daphne 启动脚本不存在，请手动重启"
    fi
}

# ==================== 显示摘要 ====================
show_summary() {
    echo ""
    echo "=========================================="
    echo "  PostgreSQL 迁移完成！"
    echo "=========================================="
    echo ""
    echo "备份位置: $BACKUP_DIR/"
    echo "  - SQLite 备份: db.sqlite3.backup.$TIMESTAMP"
    echo "  - 数据导出: data_export_$TIMESTAMP.json"
    echo "  - 配置备份: settings.py.backup.$TIMESTAMP"
    echo ""
    echo "数据库信息:"
    echo "  - 主机: $DB_HOST:$DB_PORT"
    echo "  - 数据库: $DB_NAME"
    echo "  - 用户: $DB_USER"
    echo ""
    echo "服务状态:"
    echo "  - PostgreSQL: $(systemctl is-active postgresql)"
    echo "  - Nginx: $(systemctl is-active nginx)"
    echo ""
    echo "下一步:"
    echo "  1. 检查配置文件中的数据库密码"
    echo "  2. 测试 API: curl http://127.0.0.1:8000/api/health"
    echo "  3. 压测验证: ab -n 1000 -c 200 http://your-domain.com/api/health"
    echo "  4. 监控数据库: bash /opt/gipfel/deploy/monitor.sh"
    echo ""
    echo "如需回滚，请参考: deploy/postgresql-migration-guide.md"
    echo "=========================================="
}

# ==================== 主流程 ====================
main() {
    echo "=========================================="
    echo "  Gipfel PostgreSQL 迁移脚本"
    echo "=========================================="
    echo ""
    
    # 检查配置
    if [ "$DB_PASSWORD" = "your_secure_password_here" ]; then
        error "请先修改脚本中的数据库密码！"
    fi
    
    check_prerequisites
    backup_sqlite
    create_database
    install_dependencies
    export_data
    update_settings
    run_migrations
    import_data
    verify_migration
    update_logviewer
    restart_services
    show_summary
}

# 运行主流程
main