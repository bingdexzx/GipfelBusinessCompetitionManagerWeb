#!/bin/bash
# ============================================================
# Gipfel 业务竞赛管理系统 — 一键更新脚本
#
# 功能：拉取最新代码 → 备份数据库(PostgreSQL/SQLite) → 自动配置
#       PostgreSQL → 迁移数据 → 更新后端依赖 → 构建前端 → 刷新
#       systemd 服务 → 配置 Nginx → 健康检查
#
# 用法：
#   sudo bash update.sh                              # 默认：git pull + 全量更新
#   sudo bash update.sh --source-dir /path/to/repo   # 从本地 checkout 同步
#   sudo bash update.sh --skip-backup                # 跳过数据库备份
#   sudo bash update.sh --skip-build                 # 跳过前端构建
#   sudo bash update.sh --with-nginx                 # 同时刷新 Nginx 配置
#   sudo bash update.sh --domain comp.example.com    # 指定域名（ALLOWED_HOSTS 自愈）
#
# 代码来源（三选一，自动判定）：
#   模式 A  部署目录本身是 git clone → 原地 git pull
#   模式 B  提供 --source-dir → 该目录 git pull 后 rsync 到部署目录
#   模式 C  提供 --repo 且目录为空 → git clone
# ============================================================
set -euo pipefail

# ---------------- 失败时打印行号 ----------------
__on_err() {
    local rc="$1" line="$2" cmd="$3"
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "[FAIL] 脚本在第 ${line} 行终止（退出码 ${rc}）" >&2
    echo "       命令：${cmd}" >&2
    echo "       已完成的步骤保留生效，可直接重跑补齐。" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    exit "$rc"
}
trap '__on_err $? "$LINENO" "$BASH_COMMAND"' ERR

# ==================== 配置 ====================
INSTALL_DIR="/opt/gipfel"
BACKEND_DIR="$INSTALL_DIR/backend"
FRONTEND_DIR="$INSTALL_DIR/frontend"
BACKUP_DIR="$INSTALL_DIR/_backup"
VENV_DIR="$BACKEND_DIR/.venv"
ENV_FILE="$BACKEND_DIR/.env"

# PostgreSQL 默认配置（首次迁移时写入 .env，后续从 .env 读取）
DB_NAME="gipfel"
DB_USER="gipfel"
DB_PASSWORD="CHANGE_ME_TO_STRONG_PASSWORD"
DB_HOST="localhost"
DB_PORT="5432"

# ==================== 颜色输出 ====================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { printf "${GREEN}[$(date '+%H:%M:%S')]${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}  ✓${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}  ⚠${NC} %s\n" "$*"; }
err()  { printf "${RED}  ✗${NC} %s\n" "$*"; exit 1; }

# ==================== 参数解析 ====================
SOURCE_DIR=""
REPO=""
DOMAIN=""
WITH_NGINX=0
SKIP_BACKUP=0
SKIP_BUILD=0

usage() {
    cat <<EOF
用法: sudo bash $0 [选项]

选项:
  --source-dir PATH     从本地 checkout 同步（git pull 后 rsync）
  --repo URL            首次克隆仓库地址
  --domain DOMAIN       公网域名（用于 ALLOWED_HOSTS / CORS 自愈）
  --with-nginx          同时刷新 Nginx 配置
  --skip-backup         跳过数据库备份
  --skip-build          跳过前端构建
  -h, --help            显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source-dir)  SOURCE_DIR="$2"; shift 2 ;;
        --repo)        REPO="$2"; shift 2 ;;
        --domain)      DOMAIN="$2"; shift 2 ;;
        --with-nginx)  WITH_NGINX=1; shift ;;
        --skip-backup) SKIP_BACKUP=1; shift ;;
        --skip-build)  SKIP_BUILD=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *) echo "未知参数: $1"; usage; exit 2 ;;
    esac
done

[[ $EUID -ne 0 ]] && { echo "请用 sudo 执行"; exit 1; }

# ==================== 1. 拉取最新代码 ====================
echo ""
echo "━━━━━━━━━━ 1/9 拉取代码 ━━━━━━━━━━"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    # 模式 A：部署目录本身是 git clone → 原地 pull
    log "部署目录为 git 仓库，执行 git pull..."
    cd "$INSTALL_DIR"
    git pull --ff-only || { warn "git pull 失败（网络问题），使用本地现有代码继续"; }
    # 自更新：脚本本身被更新后重新执行
    if [[ -z "${GIPFEL_UPDATE_REEXEC:-}" && "$0" == "$INSTALL_DIR"/* ]]; then
        export GIPFEL_UPDATE_REEXEC=1
        log "脚本自身已更新，重新执行..."
        exec "$0" "$@"
    fi
elif [[ -n "$SOURCE_DIR" && -d "$SOURCE_DIR/.git" ]]; then
    # 模式 B：从本地 checkout 同步
    log "从 $SOURCE_DIR 拉取并同步..."
    git -C "$SOURCE_DIR" pull --ff-only || warn "git pull 失败，使用本地现有代码"
    mkdir -p "$INSTALL_DIR"
    rsync -a --delete \
        --exclude .venv --exclude __pycache__ --exclude '*.pyc' \
        --exclude node_modules --exclude dist --exclude db.sqlite3 \
        --exclude uploads --exclude logs --exclude '.env' \
        --exclude frontend-dist --exclude staticfiles \
        "$SOURCE_DIR/backend/" "$INSTALL_DIR/backend/"
    rsync -a --delete --exclude node_modules --exclude dist \
        "$SOURCE_DIR/frontend/" "$INSTALL_DIR/frontend/"
    rsync -a --delete "$SOURCE_DIR/deploy/" "$INSTALL_DIR/deploy/" 2>/dev/null || true
    rsync -a --delete "$SOURCE_DIR/scripts/" "$INSTALL_DIR/scripts/" 2>/dev/null || true
elif [[ -n "$REPO" ]]; then
    # 模式 C：克隆
    if [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        err "部署目录非空，无法 git clone。请清空或改用 --source-dir"
    fi
    log "克隆 $REPO → $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
else
    # 自动检测：如果部署目录存在且有内容，跳过拉取
    if [[ -d "$INSTALL_DIR/backend" ]]; then
        warn "部署目录不是 git 仓库，跳过代码拉取（使用现有代码）"
    else
        err "部署目录不存在且未指定 --source-dir / --repo。请先部署。"
    fi
fi

ok "代码已就绪"

# ==================== 2. 备份数据库 ====================
echo ""
echo "━━━━━━━━━━ 2/9 备份数据库 ━━━━━━━━━━"

if [[ $SKIP_BACKUP -eq 1 ]]; then
    warn "跳过数据库备份（--skip-backup）"
else
    TIMESTAMP="$(date +%F_%H%M%S)"
    mkdir -p "$BACKUP_DIR/$TIMESTAMP"

    # 备份 .env
    [[ -f "$ENV_FILE" ]] && cp -a "$ENV_FILE" "$BACKUP_DIR/$TIMESTAMP/.env" && ok ".env 已备份"

    # 备份媒体文件
    [[ -d "$BACKEND_DIR/media" ]] && \
        tar -czf "$BACKUP_DIR/$TIMESTAMP/media.tar.gz" -C "$BACKEND_DIR" media && \
        ok "媒体文件已备份"

    # 检测数据库类型并备份
    _db_engine=""
    if [[ -f "$ENV_FILE" ]]; then
        _db_engine="$(grep -E '^DB_ENGINE=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
    fi

    if [[ "$_db_engine" == *"postgresql"* ]]; then
        # ---- PostgreSQL 备份 ----
        log "PostgreSQL 数据库，执行 pg_dump..."
        _pg_name="$(grep -E '^DB_NAME=' "$ENV_FILE" | head -1 | cut -d= -f2- || echo "$DB_NAME")"
        _pg_user="$(grep -E '^DB_USER=' "$ENV_FILE" | head -1 | cut -d= -f2- || echo "$DB_USER")"

        # SQL 格式备份（可读、可恢复）
        if sudo -u postgres pg_dump -d "$_pg_name" | gzip > "$BACKUP_DIR/$TIMESTAMP/db.sql.gz" 2>/dev/null; then
            ok "PostgreSQL SQL 备份完成（$(du -h "$BACKUP_DIR/$TIMESTAMP/db.sql.gz" | cut -f1)）"
        else
            warn "pg_dump 失败（postgres 用户），尝试用 $_pg_user..."
            PGPASSWORD="$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)" \
                pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$_pg_user" -d "$_pg_name" 2>/dev/null \
                | gzip > "$BACKUP_DIR/$TIMESTAMP/db.sql.gz" || warn "PostgreSQL 备份失败"
        fi

        # 自定义格式备份（支持 pg_restore 并行恢复、选择性恢复）
        sudo -u postgres pg_dump -Fc -d "$_pg_name" > "$BACKUP_DIR/$TIMESTAMP/db.dump" 2>/dev/null || true

        # Django JSON 导出
        cd "$BACKEND_DIR"
        source "$VENV_DIR/bin/activate"
        set -a; source "$ENV_FILE" 2>/dev/null; set +a
        python manage.py dumpdata --indent 2 > "$BACKUP_DIR/$TIMESTAMP/data.json" 2>/dev/null || \
            warn "Django dumpdata 失败"

    elif [[ -f "$BACKEND_DIR/db.sqlite3" ]]; then
        # ---- SQLite 备份 ----
        log "SQLite 数据库，复制文件..."
        cp -a "$BACKEND_DIR/db.sqlite3" "$BACKUP_DIR/$TIMESTAMP/db.sqlite3"
        ok "SQLite 备份完成"

        cd "$BACKEND_DIR"
        [[ -d "$VENV_DIR" ]] && source "$VENV_DIR/bin/activate"
        python manage.py dumpdata --indent 2 > "$BACKUP_DIR/$TIMESTAMP/data.json" 2>/dev/null || true
    else
        warn "未找到数据库，跳过"
    fi

    # 清理 30 天前的旧备份
    find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
    ok "备份完成 → $BACKUP_DIR/$TIMESTAMP/"
fi

# ==================== 3. 停止服务 ====================
echo ""
echo "━━━━━━━━━━ 3/9 停止服务 ━━━━━━━━━━"

for svc in gipfel gipfel-daphne gipfel-logviewer gipfel-celery; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc"
        ok "已停止 $svc"
    fi
done
pkill -f "daphne.*backend.asgi" 2>/dev/null || true

# ==================== 4. 安装依赖 ====================
echo ""
echo "━━━━━━━━━━ 4/9 安装依赖 ━━━━━━━━━━"

log "系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx \
    postgresql postgresql-contrib libpq-dev build-essential curl git gzip 2>/dev/null || true
ok "系统依赖就绪"

log "Python 依赖..."
cd "$BACKEND_DIR"
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel -q
fi
"$VENV_DIR/bin/pip" install -r requirements.txt -q
# 确保 psycopg2-binary（PostgreSQL 驱动）
"$VENV_DIR/bin/python" -c "import psycopg2" 2>/dev/null || \
    "$VENV_DIR/bin/pip" install psycopg2-binary -q
ok "Python 依赖就绪"

# ==================== 5. 配置 PostgreSQL ====================
echo ""
echo "━━━━━━━━━━ 5/9 配置 PostgreSQL ━━━━━━━━━━"

systemctl start postgresql
systemctl enable postgresql
sleep 1

# 从 .env 读取已有配置（如有）
if [[ -f "$ENV_FILE" ]]; then
    _e_name="$(grep -E '^DB_NAME=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
    _e_user="$(grep -E '^DB_USER=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
    _e_pass="$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
    [[ -n "$_e_name" ]] && DB_NAME="$_e_name"
    [[ -n "$_e_user" ]] && DB_USER="$_e_user"
    [[ -n "$_e_pass" && "$_e_pass" != "CHANGE_ME_TO_STRONG_PASSWORD" ]] && DB_PASSWORD="$_e_pass"
fi

# 创建数据库和用户（幂等）
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;" 2>/dev/null || true
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true
sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;" 2>/dev/null || true
sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;" 2>/dev/null || true
ok "PostgreSQL 就绪（$DB_NAME @ $DB_HOST:$DB_PORT）"

# ==================== 6. 更新 .env ====================
echo ""
echo "━━━━━━━━━━ 6/9 更新配置 ━━━━━━━━━━"

# 保留已有密钥
_existing_jwt=""; _existing_secret=""
if [[ -f "$ENV_FILE" ]]; then
    _existing_jwt="$(grep -E '^JWT_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
    _existing_secret="$(grep -E '^SECRET_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
    _existing_lvkey="$(grep -E '^LOGVIEWER_SECRET_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
fi
[[ -z "$_existing_jwt" ]]    && _existing_jwt="$(head -c 32 /dev/urandom | base64 | tr -d '\n+/=')"
[[ -z "$_existing_secret" ]] && _existing_secret="$(head -c 32 /dev/urandom | base64 | tr -d '\n+/=')"
[[ -z "$_existing_lvkey" ]]  && _existing_lvkey="$(head -c 32 /dev/urandom | base64 | tr -d '\n+/=')"

# 写入 .env（仅当不存在或 DB_ENGINE 不是 PostgreSQL 时重写数据库部分）
if [[ ! -f "$ENV_FILE" ]] || ! grep -q "DB_ENGINE=django.db.backends.postgresql" "$ENV_FILE" 2>/dev/null; then
    cat > "$ENV_FILE" << EOF
# ============================================================
# Gipfel 后端配置（由 update.sh 自动生成）
# ============================================================

# PostgreSQL
DB_ENGINE=django.db.backends.postgresql
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT

# Django
DEBUG=False
SECRET_KEY=$_existing_secret
JWT_SECRET=$_existing_jwt
LOGVIEWER_SECRET_KEY=$_existing_lvkey
ALLOWED_HOSTS=localhost,127.0.0.1

# 路径
MEDIA_ROOT=$BACKEND_DIR/media
STATIC_ROOT=$BACKEND_DIR/static
EOF
    ok ".env 已写入（PostgreSQL 配置）"
else
    ok ".env 已存在且已配置 PostgreSQL，跳过重写"
fi

# ALLOWED_HOSTS 自愈：追加域名或公网 IP
if [[ -n "$DOMAIN" ]]; then
    if ! grep -E '^ALLOWED_HOSTS=' "$ENV_FILE" | grep -q "$DOMAIN"; then
        sed -i "s|^ALLOWED_HOSTS=.*|&,${DOMAIN}|" "$ENV_FILE"
        ok "ALLOWED_HOSTS 已追加 $DOMAIN"
    fi
fi

chmod 600 "$ENV_FILE" 2>/dev/null || true
ok "配置更新完成"

# ==================== 7. 数据迁移 / Django 迁移 ====================
echo ""
echo "━━━━━━━━━━ 7/9 数据库迁移 ━━━━━━━━━━"

cd "$BACKEND_DIR"
source "$VENV_DIR/bin/activate"
set -a; source "$ENV_FILE" 2>/dev/null; set +a

# 检查是否需要从 SQLite 迁移
_needs_sqlite_migration=0
if [[ -f "$BACKEND_DIR/db.sqlite3" ]] && [[ -f "$BACKUP_DIR/$TIMESTAMP/data.json" || -f "$BACKUP_DIR"/*/data.json ]]; then
    _needs_sqlite_migration=1
fi

# 运行 Django migrate（无论哪种情况都需要）
log "执行 Django migrate..."
python manage.py migrate --noinput
ok "数据库表结构已同步"

# 如果有 SQLite 数据需要迁移
if [[ $_needs_sqlite_migration -eq 1 ]]; then
    _latest_json="$(ls -t "$BACKUP_DIR"/*/data.json 2>/dev/null | head -1)"
    if [[ -n "$_latest_json" ]]; then
        log "从 SQLite 备份导入数据: $_latest_json"
        python manage.py loaddata "$_latest_json" 2>/dev/null || {
            warn "整体 loaddata 失败，逐个应用尝试..."
            for app in users competitions companies industry_types materials parts products \
                       maps infrastructures tech_tree fuels vehicles warehouses production_lines \
                       regions consumer_demands messages stock contracts announcements files; do
                python manage.py loaddata "$_latest_json" 2>/dev/null || true
            done
        }
        # 重命名旧 SQLite
        mv "$BACKEND_DIR/db.sqlite3" "$BACKEND_DIR/db.sqlite3.migrated" 2>/dev/null || true
        ok "SQLite 数据已迁移到 PostgreSQL"
    fi
fi

# 收集静态文件
log "收集静态文件..."
python manage.py collectstatic --noinput 2>/dev/null || true

# 日志查看器静态资源
if [[ -d "$BACKEND_DIR/logviewer" ]]; then
    cd "$BACKEND_DIR/logviewer"
    "$BACKEND_DIR/.venv/bin/python" manage.py collectstatic --noinput --settings=logviewer.settings 2>/dev/null || true
    cd "$BACKEND_DIR"
fi

ok "数据迁移完成"

# ==================== 8. 构建前端 ====================
echo ""
echo "━━━━━━━━━━ 8/9 构建前端 ━━━━━━━━━━"

if [[ $SKIP_BUILD -eq 1 ]]; then
    warn "跳过前端构建（--skip-build）"
else
    cd "$FRONTEND_DIR"
    if command -v pnpm &>/dev/null; then
        pnpm install --frozen-lockfile --no-audit --no-fund 2>/dev/null || \
            pnpm install --no-audit --no-fund
        pnpm run build
    elif command -v npm &>/dev/null; then
        npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
        npm run build
    else
        warn "未找到 npm/pnpm，跳过前端构建"
    fi
    ok "前端构建完成"
fi

# ==================== 9. 文件权限 + 刷新服务 + 健康检查 ====================
echo ""
echo "━━━━━━━━━━ 9/9 刷新服务 ━━━━━━━━━━"

# 文件归属
if id gipfel >/dev/null 2>&1; then
    chown -R gipfel:gipfel "$INSTALL_DIR" 2>/dev/null || true
    chmod 600 "$ENV_FILE" 2>/dev/null || true
    ok "文件归属已切换为 gipfel"
else
    warn "用户 gipfel 不存在，跳过 chown"
fi

# 刷新 systemd 服务单元
for unit_file in "$INSTALL_DIR"/deploy/*.service; do
    [[ -f "$unit_file" ]] || continue
    unit_name="$(basename "$unit_file")"
    systemctl unmask "$unit_name" 2>/dev/null || true
    rm -f "/etc/systemd/system/$unit_name" "/run/systemd/system/$unit_name"
    sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$unit_file" > "/etc/systemd/system/$unit_name"
    systemctl daemon-reload
    systemctl enable "$unit_name" 2>/dev/null || true
    ok "已刷新服务单元: $unit_name"
done

# 重启服务
systemctl restart postgresql 2>/dev/null || true
for svc in gipfel gipfel-logviewer; do
    if systemctl cat "$svc.service" >/dev/null 2>&1; then
        systemctl restart "$svc"
        sleep 2
        if systemctl is-active --quiet "$svc"; then
            ok "$svc 已重启并运行中"
        else
            warn "$svc 启动失败，查看日志: journalctl -u $svc -n 30"
        fi
    fi
done

# Nginx
if [[ $WITH_NGINX -eq 1 ]]; then
    _vhost_tmpl="$INSTALL_DIR/deploy/nginx-gipfel.conf"
    if [[ -f "$_vhost_tmpl" ]]; then
        _domain="${DOMAIN:-_}"
        sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" -e "s|__DOMAIN__|$_domain|g" \
            "$_vhost_tmpl" > /etc/nginx/sites-available/gipfel.conf
        ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
        rm -f /etc/nginx/sites-enabled/default
        nginx -t && systemctl reload nginx 2>/dev/null || systemctl start nginx 2>/dev/null || true
        ok "Nginx 配置已刷新"
    fi
fi

# 健康检查
echo ""
echo "━━━━━━━━━━ 健康检查 ━━━━━━━━━━"
sleep 3

_check_pass=1
if systemctl is-active --quiet postgresql; then
    ok "PostgreSQL 运行中"
else
    warn "PostgreSQL 未运行"; _check_pass=0
fi

for svc in gipfel gipfel-logviewer nginx; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        ok "$svc 运行中"
    elif systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        warn "$svc 未运行"; _check_pass=0
    fi
done

if curl -s --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null | grep -q 'ok'; then
    ok "API 健康检查通过"
else
    warn "API 健康检查未通过（可能还在启动中）"; _check_pass=0
fi

# ==================== 摘要 ====================
echo ""
echo "============================================================"
if [[ $_check_pass -eq 1 ]]; then
    echo -e "${GREEN}更新完成！所有服务运行正常。${NC}"
else
    echo -e "${YELLOW}更新完成！部分服务需要检查（见上方警告）。${NC}"
fi
echo "============================================================"
echo ""
echo "  部署目录:  $INSTALL_DIR"
echo "  备份位置:  $BACKUP_DIR/$TIMESTAMP/"
echo "  数据库:    PostgreSQL ($DB_NAME @ $DB_HOST:$DB_PORT)"
echo ""
echo "  常用命令:"
echo "    查看日志:   journalctl -u gipfel -f"
echo "    重启服务:   systemctl restart gipfel"
echo "    查看状态:   systemctl status gipfel"
echo "    备份数据库: sudo -u postgres pg_dump $DB_NAME | gzip > backup.sql.gz"
echo "    恢复数据库: gunzip -c backup.sql.gz | sudo -u postgres psql $DB_NAME"
echo ""
echo "============================================================"
