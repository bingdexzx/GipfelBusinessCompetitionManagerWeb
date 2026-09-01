#!/usr/bin/env bash
# ============================================================
# Gipfel Business Competition Manager — Linux 一键部署脚本
# 适用：Ubuntu 22.04 / Debian 12，有 sudo 权限
# 用法：
#   sudo bash deploy-linux.sh --domain comp.example.com --install-dir /opt/gipfel
#   sudo bash deploy-linux.sh --install-dir /opt/gipfel --with-nginx --skip-install-deps
#
# 步骤：
#   1. 系统依赖（python3-venv python3-dev nodejs npm nginx rsync）
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
check_exists "$PROJECT_ROOT/deploy/logviewer.service"
check_exists "$PROJECT_ROOT/deploy/nginx-gipfel.conf"

# ---------------- 1. 系统依赖 ----------------
if [[ $SKIP_INSTALL_DEPS -eq 0 ]]; then
    log "安装系统依赖：python3-venv python3-dev nodejs npm nginx rsync curl ca-certificates"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y \
        python3 python3-venv python3-dev python3-pip \
        curl ca-certificates gnupg lsb-release \
        nginx openssl rsync

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

# rsync 是代码同步的硬依赖（即便 --skip-install-deps 也必须存在，否则下方 rsync 直接 command not found）
command -v rsync >/dev/null 2>&1 || err "缺少 rsync，请先执行：apt-get install -y rsync（或重跑本脚本去掉 --skip-install-deps 以自动安装）"

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
# 恢复备份的数据库（核心业务数据，必须随部署保留，否则重部署会丢失全部数据）
if [[ -f "$BACKUP_DIR/db.sqlite3" && ! -f "$INSTALL_DIR/backend/db.sqlite3" ]]; then
    cp -a "$BACKUP_DIR/db.sqlite3" "$INSTALL_DIR/backend/db.sqlite3"
    log "已从备份恢复数据库 $BACKUP_DIR/db.sqlite3"
fi

# 首次部署无 .env → 从 example 复制，生成随机 JWT_SECRET
if [[ ! -f "$INSTALL_DIR/backend/.env" ]]; then
    log "首次部署：生成后端 .env"
    cp "$INSTALL_DIR/backend/.env.example" "$INSTALL_DIR/backend/.env"
    SECRET="$(openssl rand -base64 32 | tr -d '\n=')"
    sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${SECRET}|" "$INSTALL_DIR/backend/.env"
    # 显式关闭 DEBUG（.env.example 可能无此行，确保生产环境 DEBUG=false）
    if ! grep -q '^DEBUG=' "$INSTALL_DIR/backend/.env"; then
        echo 'DEBUG=false' >> "$INSTALL_DIR/backend/.env"
    else
        sed -i 's/^DEBUG=.*/DEBUG=false/' "$INSTALL_DIR/backend/.env"
    fi
    if [[ -n "$DOMAIN" ]]; then
        # 取消注释并设置 CORS 白名单（兼容已注释 #CORS_ORIGIN=... 与未注释两种写法）
        sed -i -E "s|^#?[[:space:]]*CORS_ORIGIN=.*|CORS_ORIGIN=https://${DOMAIN},http://${DOMAIN}|" "$INSTALL_DIR/backend/.env"
        grep -q '^CORS_ORIGIN=' "$INSTALL_DIR/backend/.env" || \
            echo "CORS_ORIGIN=https://${DOMAIN},http://${DOMAIN}" >> "$INSTALL_DIR/backend/.env"
    else
        # 无域名（纯 IP）部署：日志查看器走 8120 端口，显式下发公网地址，
        # 避免前端 /api/version 把 Host 推导成错误的 https://log.<IP>/
        SERVER_IP="$(hostname -I | awk '{print $1}')"
        if [[ -n "$SERVER_IP" ]]; then
            echo "LOG_VIEWER_PUBLIC_URL=http://${SERVER_IP}:8120/" >> "$INSTALL_DIR/backend/.env"
        fi
    fi
    # 日志查看器防直连令牌密钥：缺失则生成随机值（与主后端共用同一 .env，保证两端密钥一致）
    if ! grep -q '^LOGVIEWER_SECRET_KEY=' "$INSTALL_DIR/backend/.env"; then
        LVSECRET="$(openssl rand -base64 32 | tr -d '\n=')"
        echo "LOGVIEWER_SECRET_KEY=${LVSECRET}" >> "$INSTALL_DIR/backend/.env"
    fi
fi

mkdir -p "$INSTALL_DIR/backend/uploads" "$INSTALL_DIR/backend/logs"
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
log "执行 migrate（首次会自动建 admin/admin23）"
".venv/bin/python" manage.py check --fail-level ERROR
".venv/bin/python" manage.py migrate --noinput
".venv/bin/python" manage.py collectstatic --noinput
# 日志查看器静态资源（独立项目，settings=logviewer.settings）
log "收集日志查看器静态资源"
cd "$INSTALL_DIR/backend/logviewer"
"$INSTALL_DIR/backend/.venv/bin/python" manage.py collectstatic --noinput --settings=logviewer.settings
cd "$INSTALL_DIR/backend"
ok "数据库迁移完成，静态资源收集完成"

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

# 以 root 身份完成 venv/pip/migrate/collectstatic/build 后，统一把整棵安装树归属运行用户 gipfel，
# 否则 systemd 以 gipfel 启动时对 root 所有的 db.sqlite3/uploads/logs 无写权限会启动失败。
chown -R gipfel:gipfel "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/backend/.env" 2>/dev/null || true
ok "文件归属已切换为 gipfel（运行时可写 db/uploads/logs），.env 权限收紧为 600"

# ---------------- 6. systemd unit ----------------
log "写入 systemd 服务 gipfel.service / gipfel-logviewer.service"
UNIT_FILE="$INSTALL_DIR/deploy/gipfel.service"
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$PROJECT_ROOT/deploy/gipfel.service" > "$UNIT_FILE"
cp -f "$UNIT_FILE" /etc/systemd/system/gipfel.service

LV_UNIT_FILE="$INSTALL_DIR/deploy/logviewer.service"
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$PROJECT_ROOT/deploy/logviewer.service" > "$LV_UNIT_FILE"
cp -f "$LV_UNIT_FILE" /etc/systemd/system/gipfel-logviewer.service

systemctl daemon-reload
systemctl enable --now gipfel
sleep 2
if ! systemctl is-active --quiet gipfel; then
    warn "gipfel 服务未立即激活，等待 5s 重试检查"
    sleep 5
fi
systemctl is-active --quiet gipfel && ok "gipfel.service 运行中" || \
    { journalctl -u gipfel -n 30 --no-pager; err "gipfel 服务启动失败，见上方日志"; }

# 日志查看器（独立站点，nginx 子域 log.<DOMAIN> 代理）
systemctl enable --now gipfel-logviewer
sleep 2
if ! systemctl is-active --quiet gipfel-logviewer; then
    warn "gipfel-logviewer 服务未立即激活，等待 5s 重试检查"
    sleep 5
fi
systemctl is-active --quiet gipfel-logviewer && ok "gipfel-logviewer.service 运行中" || \
    { journalctl -u gipfel-logviewer -n 30 --no-pager; err "gipfel-logviewer 服务启动失败，见上方日志"; }

# ---------------- 7. nginx ----------------
if [[ $WITH_NGINX -eq 1 ]]; then
    log "配置 nginx 虚拟主机"
    VHOST_FILE="$INSTALL_DIR/deploy/nginx-gipfel.conf"
    sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        -e "s|__DOMAIN__|${DOMAIN:-_}|g" \
        "$PROJECT_ROOT/deploy/nginx-gipfel.conf" > "$VHOST_FILE"

    # 日志查看器 server 块二选一（模板含两块，按是否传 --domain 删除另一块）：
    #   有域名 → 保留 log.<DOMAIN> 子域块，删除 8120 端口块；
    #   无域名 → 保留 8120 端口块，删除子域块（server_name log._ 形同失效，干脆移除避免歧义）。
    if [[ -n "$DOMAIN" ]]; then
        sed -i '/# === LOGVIEWER_PORT8120_START ===/,/# === LOGVIEWER_PORT8120_END ===/d' "$VHOST_FILE"
    else
        sed -i '/# === LOGVIEWER_SUBDOMAIN_START ===/,/# === LOGVIEWER_SUBDOMAIN_END ===/d' "$VHOST_FILE"
    fi

    cp -f "$VHOST_FILE" /etc/nginx/sites-available/gipfel.conf

    # 刷新 gipfel vhost 软链（始终指向最新生成的 sites-available/gipfel.conf，
    # 修复任何陈旧/损坏软链；sites-available/gipfel.conf 源文件保留，可随时恢复）
    ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
    ok "已启用 gipfel nginx 虚拟主机（sites-enabled/gipfel.conf）"

    # 禁用 nginx 自带默认欢迎页（避免与 gipfel 主站点 server_name _ 在 80 端口冲突 → 显示 "Welcome to nginx"）
    # 注意：nginx 按 sites-enabled/* 通配包含，「改名 default.disabled」无法禁用（仍被 * 匹配），必须删除才能真正禁用。
    # 枚举所有已知变体：Debian/Ubuntu 的 sites-enabled/default（或旧脚本改名留下的 default.disabled）、
    # RHEL 系的 conf.d/default.conf。漏删任一个都会让 80 端口被默认站点抢走。
    for f in /etc/nginx/sites-enabled/default \
             /etc/nginx/sites-enabled/default.disabled \
             /etc/nginx/sites-enabled/default.conf \
             /etc/nginx/conf.d/default.conf; do
        if [[ -e "$f" ]]; then
            rm -f "$f"
            log "已移除 nginx 默认站点配置：$f"
        fi
    done

    nginx -t || err "nginx -t 失败，请修正"
    # 全新服务器 nginx 可能尚未启动，reload 对未运行服务会失败；按状态选择 start / reload
    systemctl enable nginx 2>/dev/null || true
    if systemctl is-active --quiet nginx; then
        systemctl reload nginx
        ok "nginx 配置已 reload"
    else
        systemctl start nginx
        ok "nginx 已启动"
    fi

    # 验证：80 端口不应再返回 nginx 默认欢迎页；若后端未起则给出 502 排查提示而非误判
    sleep 1
    if command -v curl >/dev/null 2>&1; then
        _body="$(curl -s --max-time 5 http://127.0.0.1/ 2>/dev/null || true)"
        if printf '%s' "$_body" | grep -qi 'Welcome to nginx'; then
            warn "80 端口仍返回 nginx 默认欢迎页：默认站点未被完全禁用。请检查 /etc/nginx/nginx.conf 是否内联了默认 server 块，或仍有其它 sites-enabled/* 配置冲突"
        elif ! systemctl is-active --quiet gipfel; then
            warn "nginx 已正确接管 80 端口，但后端 gipfel 服务未运行，访问将出现 502；请执行：sudo systemctl restart gipfel"
        else
            ok "80 端口验证通过：gipfel 站点已生效（非默认欢迎页）"
        fi
    fi

    if [[ -n "$DOMAIN" ]]; then
        if command -v certbot >/dev/null 2>&1; then
            warn "已安装 certbot，可手动执行：certbot --nginx -d $DOMAIN -d log.$DOMAIN --non-interactive --redirect"
        else
            warn "如需 HTTPS：apt-get install -y certbot python3-certbot-nginx && certbot --nginx -d $DOMAIN -d log.$DOMAIN --redirect"
        fi
        warn "另需：将 log.$DOMAIN 的 DNS A 记录指向本服务器（日志查看器子域代理前置条件）。"
    else
        # 无域名：日志查看器经 8120 端口暴露公网，需放行防火墙
        if command -v ufw >/dev/null 2>&1; then
            ufw allow 8120/tcp >/dev/null 2>&1 || true
            ok "已放行防火墙 8120 端口（ufw 规则已添加；若 ufw 未启用则该规则暂未生效）"
        else
            warn "无域名部署：请确认云/系统防火墙放行 TCP 8120，否则 http://<IP>:8120/ 不可达。"
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
if [[ -z "$DOMAIN" ]]; then
echo "  日志查看器：  http://$(hostname -I | awk '{print $1}'):8120/ （前端「系统设置 → 日志查看器」按钮，需放行 8120）"
fi
echo "  Nginx 状态：  systemctl status nginx"
fi
echo "  默认超管：    admin / admin23（首次登录强制改密）"
echo "  日志：        journalctl -u gipfel -f   /   tail -F $INSTALL_DIR/backend/logs/app.log"
