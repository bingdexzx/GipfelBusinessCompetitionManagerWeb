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
# 强制标准输入来自 /dev/null：任何隐式 read/openssl 等待熵等都不会卡在终端等待输入。
# 需要交互的场景（手动填写公网 IP）已在脚本内用显式 read < /dev/stdin 处理。
exec 0</dev/null
# 输出即时刷新，避免卡住时日志缓冲区看不到进度（便于定位阻塞点）。
exec 1>&1

# ---------------- 参数解析 ----------------
DOMAIN=""
INSTALL_DIR="/opt/gipfel"
WITH_NGINX=0
SKIP_INSTALL_DEPS=0
FORCE_OVERWRITE=0
PUBLIC_IP=""   # 显式指定公网 IP（无域名纯 IP 部署日志查看器用）；非空则跳过自动探测与交互填写
PUBLIC_IP_SET=0  # 标记 --public-ip 是否由用户显式传入（用于结尾提示区分「用户指定」与「自动探测」）

usage() {
    cat <<EOF
Usage: $0 [options]
  --domain DOMAIN              公网域名（写入 nginx server_name + 建议 HTTPS）
  --install-dir PATH           安装目录，默认 /opt/gipfel
  --public-ip IP               公网 IP（无 --domain 部署时日志查看器使用 http://<IP>:8120/）；
                              显式传入可跳过自动探测与交互填写，避免受限网络/非交互环境卡住
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
        --public-ip)          PUBLIC_IP="$2"; PUBLIC_IP_SET=1; shift 2 ;;
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

# 规范化用户/探测得到的地址：去 http(s):// 前缀、去路径/端口后缀；IPv6 保留方括号。
# 用法：normalize_ip "$RAW"  （结果经 stdout 返回）
normalize_ip() {
    local s="$1"
    s="${s#http://}"; s="${s#https://}"
    if [[ "$s" == \[* ]]; then
        s="${s%%]*}]"     # IPv6 带方括号：仅保留 [....]
    else
        s="${s%%/*}"      # 去掉 /path 或 :port/path
        # IPv4（含点）再去掉尾随 :port；裸 IPv6 不动，避免误伤其冒号分隔
        if [[ "$s" == *.* && "$s" == *:* ]]; then
            s="${s%%:*}"
        fi
    fi
    printf '%s' "$s"
}

# 多服务兜底探测公网 IP：任一可达即返回；用 timeout 硬包裹 curl，连 DNS 解析超时一并杀掉，
# 避免无外网/异常 DNS 时 curl 卡在解析阶段永不返回（curl --max-time 不限制 DNS 超时）。
# 返回空字符串表示全部失败。
_probe_public_ip() {
    local ip=""
    for svc in https://api.ipify.org https://ifconfig.me https://icanhazip.com; do
        ip="$(timeout 8 curl -s --max-time 6 "$svc" 2>/dev/null)"
        [[ -n "$ip" ]] && { printf '%s' "$ip"; return 0; }
    done
    return 1
}

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
    echo "[DIAG] .env 不存在，准备从 .env.example 复制（$(date +%T)）" >&2
    cp "$INSTALL_DIR/backend/.env.example" "$INSTALL_DIR/backend/.env"
    echo "[DIAG] .env.example 复制完成（$(date +%T)）" >&2
    # 生成随机密钥：用 /dev/urandom 直接取字节（base64），不依赖 openssl 也不等系统熵，绝不阻塞。
    # 新装系统 openssl rand 偶发因熵不足变慢，故改用 head -c 读 urandom 兜底。
    SECRET="$(head -c 32 /dev/urandom | base64 | tr -d '\n+/=')"
    echo "[DIAG] JWT_SECRET 生成完成（$(date +%T)）" >&2
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
        # 无域名（纯 IP）部署：日志查看器走 8120 端口，显式下发【公网】地址，
        # 避免前端 /api/version 把 Host 推导成错误的 https://log.<IP>/ 或误用内网 IP。
        # 重要：必须用公网 IP（用户从公网访问），不能用 hostname -I 首地址（通常为内网/私网 IP）。
        #
        # 优先顺序：--public-ip 显式传入 > 多服务探测 > 交互手动填写（仅 TTY 且带超时）
        #   —— 任何一步成功都不进入下一步，确保非交互/受限网络环境永不卡住。
        if [[ -n "$PUBLIC_IP" ]]; then
            LV_PUBLIC_IP="$(normalize_ip "$PUBLIC_IP")"
            ok "使用 --public-ip 显式指定的公网 IP：${LV_PUBLIC_IP}"
        else
            # 用 timeout 硬包裹 curl：curl --max-time 不限制 DNS 解析超时，无外网/异常 DNS 时
            # 会卡在解析阶段永不返回；timeout 连 DNS 一起杀掉，保证 N 秒内必返回（空=失败）。
            LV_PUBLIC_IP="$(_probe_public_ip)"
        fi
        if [[ -n "$LV_PUBLIC_IP" ]]; then
            LV_PUBLIC_IP="$(normalize_ip "$LV_PUBLIC_IP")"
            # IPv6 需加方括号：http://[IPv6]:8120/
            if [[ "$LV_PUBLIC_IP" == *:* && "$LV_PUBLIC_IP" != \[* ]]; then
                echo "LOG_VIEWER_PUBLIC_URL=http://[${LV_PUBLIC_IP}]:8120/" >> "$INSTALL_DIR/backend/.env"
            else
                echo "LOG_VIEWER_PUBLIC_URL=http://${LV_PUBLIC_IP}:8120/" >> "$INSTALL_DIR/backend/.env"
            fi
            ok "日志查看器地址已写入 LOG_VIEWER_PUBLIC_URL（公网 IP：${LV_PUBLIC_IP}）。"
        elif [[ -t 0 ]]; then
            # 自动探测全部失败：交互式请运维手动填写公网 IP（仅首次部署且标准输入为终端时；
            # 非交互环境不阻塞，跳过手动填写）。read 显式读 stdin、带 60s 超时，超时则跳过，绝不卡死部署。
            echo ""
            echo "[手动填写] 未能自动探测到公网 IP。请在本终端输入本机公网 IP（回车确认，日志查看器将使用 http://<IP>:8120/）；"
            echo "            留空或 60 秒内未输入将自动跳过，日志查看器地址改由后端按请求 Host 推导（请确保经公网 IP 访问）。"
            if read -r -t 60 LV_MANUAL_IP < /dev/stdin; then
                LV_MANUAL_IP="$(normalize_ip "$LV_MANUAL_IP")"
                if [[ "$LV_MANUAL_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || [[ "$LV_MANUAL_IP" == \[* ]] || [[ "$LV_MANUAL_IP" == *:* ]]; then
                    # 规范化：IPv6 加方括号
                    if [[ "$LV_MANUAL_IP" == \[* ]]; then
                        echo "LOG_VIEWER_PUBLIC_URL=http://${LV_MANUAL_IP}:8120/" >> "$INSTALL_DIR/backend/.env"
                    elif [[ "$LV_MANUAL_IP" == *:* ]]; then
                        echo "LOG_VIEWER_PUBLIC_URL=http://[${LV_MANUAL_IP}]:8120/" >> "$INSTALL_DIR/backend/.env"
                    else
                        echo "LOG_VIEWER_PUBLIC_URL=http://${LV_MANUAL_IP}:8120/" >> "$INSTALL_DIR/backend/.env"
                    fi
                    ok "已用你填写的公网 IP(${LV_MANUAL_IP}) 写入 LOG_VIEWER_PUBLIC_URL。"
                else
                    warn "输入的不是合法 IP（${LV_MANUAL_IP}），未写入 LOG_VIEWER_PUBLIC_URL；日志查看器地址将由后端按请求 Host 推导。"
                fi
            else
                warn "等待输入超时（60s），未写入 LOG_VIEWER_PUBLIC_URL；日志查看器地址将由后端按请求 Host 推导。"
            fi
        else
            warn "未能自动获取公网 IP（非交互环境，跳过手动填写），未写入 LOG_VIEWER_PUBLIC_URL；日志查看器地址将由后端按请求 Host 推导（请确保经公网 IP 访问）。"
        fi
    fi
    # 日志查看器防直连令牌密钥：缺失则生成随机值（与主后端共用同一 .env，保证两端密钥一致）
    if ! grep -q '^LOGVIEWER_SECRET_KEY=' "$INSTALL_DIR/backend/.env"; then
        LVSECRET="$(head -c 32 /dev/urandom | base64 | tr -d '\n+/=')"
        echo "LOGVIEWER_SECRET_KEY=${LVSECRET}" >> "$INSTALL_DIR/backend/.env"
        echo "[DIAG] LOGVIEWER_SECRET_KEY 生成完成（$(date +%T)）" >&2
    fi
    echo "[DIAG] 首次部署 .env 生成完毕（$(date +%T)），JWT_SECRET/LOGVIEWER_SECRET_KEY 已就绪" >&2
fi

# 自愈：无域名部署且 .env 已存在时，纠正/补全 LOG_VIEWER_PUBLIC_URL。
#   - 显式 --public-ip：无论当前有无/对错，都以它为准写入（覆盖内网 IP 或缺失该行）
#   - 否则：仅当当前值指向内网/私网 IP 才纠正；已是公网 IP/域名/缺失行则不动
# 公网 IP 探测失败则移除该行，改由后端按请求 Host 推导（nginx 透传 $host=公网 IP），
# 避免内网 IP 持续生效。
if [[ -z "$DOMAIN" && -f "$INSTALL_DIR/backend/.env" ]]; then
    LV_CUR="$(grep -E '^LOG_VIEWER_PUBLIC_URL=' "$INSTALL_DIR/backend/.env" | tail -n1 | sed -E 's#^LOG_VIEWER_PUBLIC_URL=https?://##; s#[/:].*##')"
    LV_NEED_FIX=0
    if [[ -n "$PUBLIC_IP" ]]; then
        LV_NEED_FIX=1   # 显式指定：强制以 --public-ip 为准（覆盖内网 IP 或缺失行）
    elif [[ -n "$LV_CUR" ]]; then
        if [[ "$LV_CUR" =~ ^10\. ]] || \
           [[ "$LV_CUR" =~ ^192\.168\. ]] || \
           [[ "$LV_CUR" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]] || \
           [[ "$LV_CUR" =~ ^169\.254\. ]] || \
           [[ "$LV_CUR" =~ ^127\. ]]; then
            LV_NEED_FIX=1
        fi
    fi
    if [[ $LV_NEED_FIX -eq 1 ]]; then
        if [[ -n "$PUBLIC_IP" ]]; then
            # 显式指定 --public-ip：直接以此为准，跳过探测（确保受限网络下也能纠正）
            LV_PUBLIC_IP="$(normalize_ip "$PUBLIC_IP")"
            if grep -q '^LOG_VIEWER_PUBLIC_URL=' "$INSTALL_DIR/backend/.env"; then
                if [[ "$LV_PUBLIC_IP" == *:* && "$LV_PUBLIC_IP" != \[* ]]; then
                    sed -i -E "s|^LOG_VIEWER_PUBLIC_URL=.*|LOG_VIEWER_PUBLIC_URL=http://[${LV_PUBLIC_IP}]:8120/|" "$INSTALL_DIR/backend/.env"
                else
                    sed -i -E "s|^LOG_VIEWER_PUBLIC_URL=.*|LOG_VIEWER_PUBLIC_URL=http://${LV_PUBLIC_IP}:8120/|" "$INSTALL_DIR/backend/.env"
                fi
            else
                echo "LOG_VIEWER_PUBLIC_URL=http://${LV_PUBLIC_IP}:8120/" >> "$INSTALL_DIR/backend/.env"
            fi
            warn "已按 --public-ip 写入 LOG_VIEWER_PUBLIC_URL=${LV_PUBLIC_IP}（原值：${LV_CUR:-无}）。"
        else
            # 多服务兜底探测公网 IP（任一可达即可）；均失败则回退「移除该行，交给后端按 Host 推导」
            LV_PUBLIC_IP="$(_probe_public_ip)"
            if [[ -n "$LV_PUBLIC_IP" && "$LV_PUBLIC_IP" != "$LV_CUR" ]]; then
                LV_PUBLIC_IP="$(normalize_ip "$LV_PUBLIC_IP")"
                if [[ "$LV_PUBLIC_IP" == *:* && "$LV_PUBLIC_IP" != \[* ]]; then
                    sed -i -E "s|^LOG_VIEWER_PUBLIC_URL=.*|LOG_VIEWER_PUBLIC_URL=http://[${LV_PUBLIC_IP}]:8120/|" "$INSTALL_DIR/backend/.env"
                else
                    sed -i -E "s|^LOG_VIEWER_PUBLIC_URL=.*|LOG_VIEWER_PUBLIC_URL=http://${LV_PUBLIC_IP}:8120/|" "$INSTALL_DIR/backend/.env"
                fi
                warn "检测到 LOG_VIEWER_PUBLIC_URL 指向内网 IP(${LV_CUR})，已自动纠正为公网 IP(${LV_PUBLIC_IP})。"
            else
                # 公网 IP 探测全部失败：直接移除该行，避免内网 IP 继续生效；
                # 后端 VersionView 会按请求 Host（nginx 透传 $host=公网 IP）推导为 http://<公网IP>:8120/
                sed -i -E "/^LOG_VIEWER_PUBLIC_URL=/d" "$INSTALL_DIR/backend/.env"
                warn "公网 IP 探测失败，已移除 .env 中指向内网 IP(${LV_CUR}) 的 LOG_VIEWER_PUBLIC_URL，改由后端按请求 Host 推导公网地址。"
            fi
        fi
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

    # 按 nginx.conf 实际 include 风格放置 gipfel 配置（兼容 Debian 的 sites-enabled 与
    # 仅 include conf.d 的精简镜像），避免放错位置导致配置根本不被加载、或两处重复 server 块。
    # 同时清理另一处的残留 gipfel 软链/文件，防止重复。
    if grep -q 'sites-enabled' /etc/nginx/nginx.conf 2>/dev/null; then
        ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
        rm -f /etc/nginx/conf.d/gipfel.conf
        ok "已启用 gipfel nginx 虚拟主机（sites-enabled/gipfel.conf）"
    elif grep -q 'conf.d' /etc/nginx/nginx.conf 2>/dev/null; then
        cp -f /etc/nginx/sites-available/gipfel.conf /etc/nginx/conf.d/gipfel.conf
        rm -f /etc/nginx/sites-enabled/gipfel.conf
        ok "已启用 gipfel nginx 虚拟主机（conf.d/gipfel.conf，因 nginx.conf 仅 include conf.d）"
    else
        # 兜底：两处都放（绝大多数默认配置两者至少含其一；若都无 include 则属异常环境）
        ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
        cp -f /etc/nginx/sites-available/gipfel.conf /etc/nginx/conf.d/gipfel.conf
        ok "已启用 gipfel nginx 虚拟主机（sites-enabled + conf.d 均放置，兜底）"
    fi

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

# 公网 IP 提示：优先采用用户显式 --public-ip；否则用与首跑一致的 _probe_public_ip() 探测
# （含 timeout 硬包裹，无外网/异常 DNS 时不会卡在结尾）。探测仍失败才提示手动查询。
# 注意：此处【不可】重置 PUBLIC_IP，否则会覆盖用户传入的值，导致结尾误报「未获取到 IP」。
if [[ -z "$PUBLIC_IP" ]]; then
    PUBLIC_IP="$(_probe_public_ip)"
fi
if [[ -z "$PUBLIC_IP" ]]; then
    PUBLIC_IP_HINT="（未能自动获取公网 IP，可访问 https://ifconfig.me 或云控制台查看）"
    PUBLIC_IP="<公网IP>"
elif [[ $PUBLIC_IP_SET -eq 1 ]]; then
    PUBLIC_IP_HINT="（使用你通过 --public-ip 指定的公网 IP）"
else
    PUBLIC_IP_HINT=""
fi

echo "  目录：        $INSTALL_DIR"
echo "  后端状态：    systemctl status gipfel"
if [[ $WITH_NGINX -eq 1 ]]; then
    SERVER_IP="$(hostname -I | awk '{print $1}')"
    if [[ -n "$DOMAIN" ]]; then
        echo "  网站(公网)：   http://${DOMAIN}/"
        echo "  网站(内网)：   http://${SERVER_IP}/"
    else
        echo "  网站(内网)：   http://${SERVER_IP}/"
        echo "  网站(公网)：   http://${PUBLIC_IP}/"
        echo "  日志查看器(内)： http://${SERVER_IP}:8120/"
        echo "  日志查看器(公)： http://${PUBLIC_IP}:8120/"
        echo "                 （需放行防火墙 8120；前端「系统设置 → 日志查看器」按钮跳转）"
    fi
    echo "  Nginx 状态：  systemctl status nginx"
fi
echo "  默认超管：    admin / admin23（首次登录强制改密）"
echo "  日志：        journalctl -u gipfel -f   /   tail -F $INSTALL_DIR/backend/logs/app.log"
