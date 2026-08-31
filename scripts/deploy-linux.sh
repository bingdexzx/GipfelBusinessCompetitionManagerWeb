#!/usr/bin/env bash
# ============================================================
# Gipfel Business Competition Manager — Linux 一键部署脚本
# 适用：Ubuntu 22.04 / Debian 12，有 sudo 权限
# 用法：
#   sudo bash deploy-linux.sh --domain comp.example.com --install-dir /opt/gipfel
#   sudo bash deploy-linux.sh --install-dir /opt/gipfel --with-nginx --skip-install-deps
#
# 步骤：
#   1. 系统依赖（python3-venv python3-dev nodejs npm nginx）
#   2. 同步代码到 $INSTALL_DIR，备份已有数据
#   3. 虚拟环境 + pip
#   4. migrate（自动 seed 默认 admin）
#   5. npm ci + build → frontend-dist
#   6. systemd unit gipfel.service enable --now
#   7. [可选] nginx vhost 写入 + reload
# ============================================================
set -euo pipefail

# ---------------- 参数解析 ----------------
DOMAIN=""
INSTALL_DIR="/opt/gipfel"
WITH_NGINX=0
SKIP_INSTALL_DEPS=0
FORCE_OVERWRITE=0

usage() {
    cat <<EOF
Usage: $0 [options]
  --domain DOMAIN              公网域名（写入 nginx server_name + 建议 HTTPS）
  --install-dir PATH           安装目录，默认 /opt/gipfel
  --with-nginx                 配置 nginx 虚拟主机
  --skip-install-deps          跳过 apt install（已知环境已装好）
  --force-overwrite            即使 INSTALL_DIR 存在也覆盖（保留 backup）
  -h, --help                   显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)             DOMAIN="$2"; shift 2 ;;
        --install-dir)        INSTALL_DIR="$2"; shift 2 ;;
        --with-nginx)         WITH_NGINX=1; shift ;;
        --skip-install-deps)  SKIP_INSTALL_DEPS=1; shift ;;
        --force-overwrite)    FORCE_OVERWRITE=1; shift ;;
        -h|--help)            usage; exit 0 ;;
        *) echo "未知参数 $1"; usage; exit 2 ;;
    esac
done

[[ $EUID -ne 0 ]] && { echo "请用 sudo 执行"; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
BACKUP_DIR="${INSTALL_DIR}/_backup/$(date +%F_%H%M%S)"
SUDO_USER_HOME="$(eval echo ~${SUDO_USER:-$USER})"

log()   { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
ok()    { printf "\033[32m[OK]\033[0m   %s\n" "$*"; }
warn()  { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
err()   { printf "\033[31m[ERROR]\033[0m %s\n" "$*"; exit 1; }

check_exists() {
    [[ -f "$1" ]] || { err "缺少必要文件：$1"; }
}
check_exists "$PROJECT_ROOT/backend/requirements.txt"
check_exists "$PROJECT_ROOT/frontend/package.json"
check_exists "$PROJECT_ROOT/deploy/gipfel.service"
check_exists "$PROJECT_ROOT/deploy/nginx-gipfel.conf"

# ---------------- 1. 系统依赖 ----------------
if [[ $SKIP_INSTALL_DEPS -eq 0 ]]; then
    log "安装系统依赖：python3-venv python3-dev nodejs npm nginx curl ca-certificates"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y \
        python3 python3-venv python3-dev python3-pip \
        curl ca-certificates gnupg lsb-release \
        nginx openssl

    # NodeSource 20 LTS（apt 默认 node 太老）
    if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -d. -f1 | tr -d v)" -lt 18 ]]; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs
    fi

    ( command -v npm >/dev/null && command -v node >/dev/null ) || err "node/npm 未安装成功"
    ok "系统依赖完成：python=$(python3 --version) node=$(node -v) npm=$(npm -v)"
else
    log "跳过系统依赖安装（--skip-install-deps）"
fi

# ---------------- 1.5 创建专用运行用户 ----------------
if ! id gipfel >/dev/null 2>&1; then
    log "创建专用运行用户 gipfel"
    useradd -r -s /usr/sbin/nologin -U -d "$INSTALL_DIR" gipfel || true
fi

# ---------------- 2. 同步代码，必要时备份旧数据 ----------------
if [[ -d "$INSTALL_DIR/backend" && -f "$INSTALL_DIR/backend/db.sqlite3" ]]; then
    log "发现现有部署 → 备份到 $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    cp -a "$INSTALL_DIR/backend/db.sqlite3" "$BACKUP_DIR/" 2>/dev/null || true
    cp -a "$INSTALL_DIR/backend/uploads"    "$BACKUP_DIR/" 2>/dev/null || true
    cp -a "$INSTALL_DIR/backend/.env"       "$BACKUP_DIR/" 2>/dev/null || true
fi

log "同步代码 → $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# 仅同步 backend / frontend / deploy 三个源码目录；避免 node_modules / .venv / db.sqlite3
# （--delete 只删目标端已同步子目录内的旧文件）
rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.pyc' \
    --exclude node_modules --exclude dist --exclude db.sqlite3 \
    --exclude uploads --exclude logs --exclude '.env' \
    "$PROJECT_ROOT/backend/"  "$INSTALL_DIR/backend/"
rsync -a --delete --exclude node_modules --exclude dist \
    "$PROJECT_ROOT/frontend/" "$INSTALL_DIR/frontend/"
rsync -a --delete "$PROJECT_ROOT/deploy/"   "$INSTALL_DIR/deploy/"

# 恢复备份的 uploads/.env
if [[ -d "$BACKUP_DIR/uploads" ]]; then
    mkdir -p "$INSTALL_DIR/backend/uploads"
    rsync -a "$BACKUP_DIR/uploads/" "$INSTALL_DIR/backend/uploads/"
fi
if [[ -f "$BACKUP_DIR/.env" && ! -f "$INSTALL_DIR/backend/.env" ]]; then
    cp -a "$BACKUP_DIR/.env" "$INSTALL_DIR/backend/.env"
fi

# 首次部署无 .env → 从 example 复制，生成随机 JWT_SECRET
if [[ ! -f "$INSTALL_DIR/backend/.env" ]]; then
    log "首次部署：生成后端 .env"
    cp "$INSTALL_DIR/backend/.env.example" "$INSTALL_DIR/backend/.env"
    SECRET="$(openssl rand -base64 32 | tr -d '\n=')"
    sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${SECRET}|" "$INSTALL_DIR/backend/.env"
    sed -i "s|^DEBUG=true|DEBUG=false|"                  "$INSTALL_DIR/backend/.env"
    if [[ -n "$DOMAIN" ]]; then
        sed -i "s|^CORS_ORIGIN=|CORS_ORIGIN=https://${DOMAIN},http://${DOMAIN}|" "$INSTALL_DIR/backend/.env"
    fi
fi

mkdir -p "$INSTALL_DIR/backend/uploads" "$INSTALL_DIR/backend/logs"
chown -R gipfel:gipfel "$INSTALL_DIR"
ok "代码同步完成"

# ---------------- 3. 虚拟环境 + pip ----------------
cd "$INSTALL_DIR/backend"
if [[ ! -d .venv ]]; then
    log "创建 Python 虚拟环境并安装依赖"
    python3 -m venv .venv
    ".venv/bin/pip" install --upgrade pip setuptools wheel
else
    log "虚拟环境存在，更新依赖"
fi
".venv/bin/pip" install -r requirements.txt
ok "Python 依赖安装完成"

# ---------------- 4. 数据库迁移 + seed 默认 admin ----------------
log "执行 migrate（首次会自动建 admin/admin123）"
".venv/bin/python" manage.py check --fail-level ERROR
".venv/bin/python" manage.py migrate --noinput
ok "数据库迁移完成"

# ---------------- 5. 前端构建 ----------------
log "构建前端（npm ci + build）"
cd "$INSTALL_DIR/frontend"
if [[ ! -d node_modules ]]; then
    npm ci --no-audit --no-fund
else
    # 有 package-lock 变更时增量装
    npm install --no-audit --no-fund 2>/dev/null || npm ci --no-audit --no-fund
fi
npm run build
rm -rf "$INSTALL_DIR/frontend-dist"
mkdir -p "$INSTALL_DIR/frontend-dist"
cp -a dist/. "$INSTALL_DIR/frontend-dist/"
chown -R gipfel:gipfel "$INSTALL_DIR/frontend-dist"
ok "前端构建完成 → $INSTALL_DIR/frontend-dist"

# ---------------- 6. systemd unit ----------------
log "写入 systemd 服务 gipfel.service"
UNIT_FILE="$INSTALL_DIR/deploy/gipfel.service"
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$PROJECT_ROOT/deploy/gipfel.service" > "$UNIT_FILE"

cp -f "$UNIT_FILE" /etc/systemd/system/gipfel.service
systemctl daemon-reload
systemctl enable --now gipfel
sleep 2
if ! systemctl is-active --quiet gipfel; then
    warn "gipfel 服务未立即激活，等待 5s 重试检查"
    sleep 5
fi
systemctl is-active --quiet gipfel && ok "gipfel.service 运行中" || \
    { journalctl -u gipfel -n 30 --no-pager; err "gipfel 服务启动失败，见上方日志"; }

# ---------------- 7. nginx ----------------
if [[ $WITH_NGINX -eq 1 ]]; then
    log "配置 nginx 虚拟主机"
    VHOST_FILE="$INSTALL_DIR/deploy/nginx-gipfel.conf"
    sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        -e "s|__DOMAIN__|${DOMAIN:-_}|g" \
        "$PROJECT_ROOT/deploy/nginx-gipfel.conf" > "$VHOST_FILE"

    cp -f "$VHOST_FILE" /etc/nginx/sites-available/gipfel.conf
    [[ -f /etc/nginx/sites-enabled/gipfel.conf ]] || \
        ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
    # 禁用默认欢迎页（避免抢占端口 80）
    [[ -f /etc/nginx/sites-enabled/default ]] && \
        mv /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.disabled 2>/dev/null || true

    nginx -t || err "nginx -t 失败，请修正"
    systemctl reload nginx
    ok "nginx 配置已 reload"

    if [[ -n "$DOMAIN" ]]; then
        if command -v certbot >/dev/null 2>&1; then
            warn "已安装 certbot，可手动执行：certbot --nginx -d $DOMAIN --non-interactive --redirect"
        else
            warn "如需 HTTPS：apt-get install -y certbot python3-certbot-nginx && certbot --nginx -d $DOMAIN --redirect"
        fi
    fi
fi

# ---------------- 收尾 ----------------
echo
ok "部署完成！"
echo "  目录：        $INSTALL_DIR"
echo "  后端状态：    systemctl status gipfel"
if [[ $WITH_NGINX -eq 1 ]]; then
echo "  网站：        ${DOMAIN:-http://$(hostname -I | awk '{print $1}')}"
echo "  Nginx 状态：  systemctl status nginx"
fi
echo "  默认超管：    admin / admin123（首次登录强制改密）"
echo "  日志：        journalctl -u gipfel -f   /   tail -F $INSTALL_DIR/backend/logs/app.log"
