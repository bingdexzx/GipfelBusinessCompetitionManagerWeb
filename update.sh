#!/bin/bash
# ============================================================
# Gipfel 业务竞赛管理系统 - 更新迁移脚本
# 用法: ./update.sh [--migrate-db]
#   --migrate-db  执行 SQLite → PostgreSQL 数据迁移
# ============================================================

set -e  # 遇到错误立即退出

# ==================== 配置区域 ====================
APP_NAME="gipfel"
APP_DIR="/opt/gipfel"
BACKEND_DIR="$APP_DIR/backend"
FRONTEND_DIR="$APP_DIR/frontend"
BACKUP_DIR="$APP_DIR/backups"
LOG_FILE="$APP_DIR/update.log"
VENV_DIR="$BACKEND_DIR/.venv"

# PostgreSQL 配置（迁移时使用）
DB_NAME="gipfel"
DB_USER="gipfel"
DB_PASSWORD="CHANGE_ME_TO_STRONG_PASSWORD"
DB_HOST="localhost"
DB_PORT="5432"

# ==================== 颜色输出 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==================== 工具函数 ====================
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] 警告:${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] 错误:${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] 信息:${NC} $1" | tee -a "$LOG_FILE"
}

# ==================== 检查是否为 root 用户 ====================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "请使用 root 用户或 sudo 运行此脚本"
    fi
}

# ==================== 停止服务 ====================
stop_services() {
    log "正在停止服务..."
    
    # 停止 Daphne (ASGI 服务器)
    if systemctl is-active --quiet gipfel-daphne 2>/dev/null; then
        systemctl stop gipfel-daphne
        log "已停止 Daphne 服务"
    fi
    
    # 停止 Celery (如果使用)
    if systemctl is-active --quiet gipfel-celery 2>/dev/null; then
        systemctl stop gipfel-celery
        log "已停止 Celery 服务"
    fi
    
    # 停止 Nginx (如果需要)
    if systemctl is-active --quiet nginx 2>/dev/null; then
        systemctl stop nginx
        log "已停止 Nginx 服务"
    fi
    
    # 杀死残留进程
    pkill -f "daphne.*backend.asgi" 2>/dev/null || true
    pkill -f "celery.*worker" 2>/dev/null || true
    
    log "所有服务已停止"
}

# ==================== 启动服务 ====================
start_services() {
    log "正在启动服务..."
    
    # 启动 Nginx
    if systemctl is-enabled --quiet nginx 2>/dev/null; then
        systemctl start nginx
        log "已启动 Nginx 服务"
    fi
    
    # 启动 Daphne
    if systemctl is-enabled --quiet gipfel-daphne 2>/dev/null; then
        systemctl start gipfel-daphne
        log "已启动 Daphne 服务"
    fi
    
    # 启动 Celery
    if systemctl is-enabled --quiet gipfel-celery 2>/dev/null; then
        systemctl start gipfel-celery
        log "已启动 Celery 服务"
    fi
    
    log "所有服务已启动"
}

# ==================== 备份数据库 ====================
backup_database() {
    log "正在备份数据库..."
    
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
    
    if [ -f "$BACKEND_DIR/db.sqlite3" ]; then
        # SQLite 备份
        BACKUP_FILE="$BACKUP_DIR/db_backup_$TIMESTAMP.sqlite3"
        cp "$BACKEND_DIR/db.sqlite3" "$BACKUP_FILE"
        log "SQLite 数据库已备份到: $BACKUP_FILE"
        
        # 导出 JSON 数据
        cd "$BACKEND_DIR"
        source "$VENV_DIR/bin/activate"
        python manage.py dumpdata --indent 2 > "$BACKUP_DIR/data_backup_$TIMESTAMP.json"
        log "数据已导出到: $BACKUP_DIR/data_backup_$TIMESTAMP.json"
    else
        warn "未找到 SQLite 数据库文件"
    fi
    
    # 备份媒体文件
    if [ -d "$BACKEND_DIR/media" ]; then
        tar -czf "$BACKUP_DIR/media_backup_$TIMESTAMP.tar.gz" -C "$BACKEND_DIR" media
        log "媒体文件已备份到: $BACKUP_DIR/media_backup_$TIMESTAMP.tar.gz"
    fi
}

# ==================== 安装系统依赖 ====================
install_system_deps() {
    log "正在安装系统依赖..."
    
    apt-get update
    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        nginx \
        postgresql \
        postgresql-contrib \
        libpq-dev \
        build-essential \
        curl \
        git
    
    log "系统依赖安装完成"
}

# ==================== 安装 Python 依赖 ====================
install_python_deps() {
    log "正在安装 Python 依赖..."
    
    cd "$BACKEND_DIR"
    
    # 创建虚拟环境（如果不存在）
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
        log "已创建虚拟环境"
    fi
    
    # 激活虚拟环境并安装依赖
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install -r requirements.txt
    
    log "Python 依赖安装完成"
}

# ==================== 安装前端依赖并构建 ====================
build_frontend() {
    log "正在构建前端..."
    
    cd "$FRONTEND_DIR"
    
    # 安装 Node.js 依赖
    if command -v pnpm &> /dev/null; then
        pnpm install --frozen-lockfile
        pnpm run build
    elif command -v npm &> /dev/null; then
        npm ci
        npm run build
    else
        error "未找到 npm 或 pnpm，请先安装 Node.js"
    fi
    
    log "前端构建完成"
}

# ==================== 配置 PostgreSQL ====================
setup_postgresql() {
    log "正在配置 PostgreSQL..."
    
    # 启动 PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # 创建数据库和用户
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || warn "数据库 $DB_NAME 已存在"
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || warn "用户 $DB_USER 已存在"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;"
    
    log "PostgreSQL 配置完成"
}

# ==================== 迁移数据到 PostgreSQL ====================
migrate_to_postgresql() {
    log "正在迁移数据到 PostgreSQL..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 临时修改配置为 PostgreSQL
    export DB_ENGINE="django.db.backends.postgresql"
    export DB_NAME="$DB_NAME"
    export DB_USER="$DB_USER"
    export DB_PASSWORD="$DB_PASSWORD"
    export DB_HOST="$DB_HOST"
    export DB_PORT="$DB_PORT"
    
    # 运行数据库迁移
    python manage.py migrate
    
    # 导入数据（如果有备份）
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/data_backup_*.json 2>/dev/null | head -1)
    if [ -n "$LATEST_BACKUP" ]; then
        log "正在导入数据: $LATEST_BACKUP"
        python manage.py loaddata "$LATEST_BACKUP"
        log "数据导入完成"
    else
        warn "未找到数据备份文件，跳过数据导入"
    fi
    
    log "PostgreSQL 迁移完成"
}

# ==================== 更新配置文件 ====================
update_config() {
    log "正在更新配置文件..."
    
    # 更新 Django 配置
    cat > "$BACKEND_DIR/backend/.env" << EOF
# 数据库配置
DB_ENGINE=django.db.backends.postgresql
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT

# Django 配置
DEBUG=False
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
ALLOWED_HOSTS=localhost,127.0.0.1

# 媒体文件
MEDIA_ROOT=$BACKEND_DIR/media
STATIC_ROOT=$BACKEND_DIR/static
EOF
    
    log "配置文件更新完成"
}

# ==================== 运行 Django 管理命令 ====================
run_django_commands() {
    log "正在运行 Django 管理命令..."
    
    cd "$BACKEND_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 收集静态文件
    python manage.py collectstatic --noinput
    
    # 检查数据库连接
    python manage.py check --database default
    
    log "Django 管理命令执行完成"
}

# ==================== 配置 Nginx ====================
setup_nginx() {
    log "正在配置 Nginx..."
    
    cat > /etc/nginx/sites-available/gipfel << 'EOF'
server {
    listen 80;
    server_name _;
    
    client_max_body_size 50M;
    
    # 前端静态文件
    location / {
        root /opt/gipfel/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
    
    # API 请求
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
    }
    
    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
    
    # 媒体文件
    location /uploads/ {
        alias /opt/gipfel/backend/media/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # 静态文件
    location /static/ {
        alias /opt/gipfel/backend/static/;
        expires 7d;
    }
}
EOF
    
    # 启用站点
    ln -sf /etc/nginx/sites-available/gipfel /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # 测试配置
    nginx -t
    
    log "Nginx 配置完成"
}

# ==================== 配置 Systemd 服务 ====================
setup_systemd() {
    log "正在配置 Systemd 服务..."
    
    # Daphne 服务
    cat > /etc/systemd/system/gipfel-daphne.service << EOF
[Unit]
Description=Gipfel Daphne ASGI Server
After=network.target postgresql.service

[Service]
Type=notify
User=root
Group=root
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/daphne -b 0.0.0.0 -p 8000 backend.asgi:application
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    # 重新加载 systemd
    systemctl daemon-reload
    systemctl enable gipfel-daphne
    
    log "Systemd 服务配置完成"
}

# ==================== 健康检查 ====================
health_check() {
    log "正在执行健康检查..."
    
    # 等待服务启动
    sleep 5
    
    # 检查 PostgreSQL
    if systemctl is-active --quiet postgresql; then
        log "✓ PostgreSQL 运行正常"
    else
        error "✗ PostgreSQL 未运行"
    fi
    
    # 检查 Daphne
    if systemctl is-active --quiet gipfel-daphne; then
        log "✓ Daphne 运行正常"
    else
        error "✗ Daphne 未运行"
    fi
    
    # 检查 Nginx
    if systemctl is-active --quiet nginx; then
        log "✓ Nginx 运行正常"
    else
        error "✗ Nginx 未运行"
    fi
    
    # 检查 API 响应
    if curl -s -o /dev/null -w "%{http_code}" http://localhost/api/ | grep -q "200\|404"; then
        log "✓ API 响应正常"
    else
        warn "✗ API 无响应"
    fi
    
    log "健康检查完成"
}

# ==================== 显示摘要 ====================
show_summary() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN}更新完成！${NC}"
    echo "============================================================"
    echo ""
    echo "数据库: PostgreSQL ($DB_HOST:$DB_PORT/$DB_NAME)"
    echo "后端:   http://localhost:8000"
    echo "前端:   http://localhost"
    echo ""
    echo "备份位置: $BACKUP_DIR"
    echo "日志文件: $LOG_FILE"
    echo ""
    echo "常用命令:"
    echo "  查看日志: journalctl -u gipfel-daphne -f"
    echo "  重启服务: systemctl restart gipfel-daphne"
    echo "  查看状态: systemctl status gipfel-daphne"
    echo ""
    echo "============================================================"
}

# ==================== 主流程 ====================
main() {
    # 初始化日志
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "==================== 更新开始 ====================" >> "$LOG_FILE"
    
    # 解析参数
    MIGRATE_DB=false
    for arg in "$@"; do
        case $arg in
            --migrate-db)
                MIGRATE_DB=true
                shift
                ;;
            --help)
                echo "用法: $0 [--migrate-db]"
                echo "  --migrate-db  执行 SQLite → PostgreSQL 数据迁移"
                exit 0
                ;;
        esac
    done
    
    # 检查是否为 root
    check_root
    
    log "开始更新流程..."
    
    # 备份数据库
    backup_database
    
    # 停止服务
    stop_services
    
    # 安装系统依赖
    install_system_deps
    
    # 安装 Python 依赖
    install_python_deps
    
    # 构建前端
    build_frontend
    
    # 数据库迁移（可选）
    if [ "$MIGRATE_DB" = true ]; then
        setup_postgresql
        update_config
        migrate_to_postgresql
    fi
    
    # 运行 Django 命令
    run_django_commands
    
    # 配置 Nginx
    setup_nginx
    
    # 配置 Systemd
    setup_systemd
    
    # 启动服务
    start_services
    
    # 健康检查
    health_check
    
    # 显示摘要
    show_summary
    
    log "更新流程完成"
}

# 执行主流程
main "$@"