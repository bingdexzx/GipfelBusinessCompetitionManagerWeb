#!/usr/bin/env bash
# ============================================================
# Gipfel Business Competition Manager — 从 GitHub 拉取最新并更新（升级脚本）
# 适用：两种方式更新已部署的实例 ——
#   ① 部署目录 /opt/gipfel 本身是 git clone（首次用 git clone 拉起）→ 本脚本模式 A 原地 pull；
#   ② 沿用 deploy-linux.sh 的「本地 checkout → rsync 到 /opt/gipfel」模型 → 本脚本模式 B（--source-dir 指向该 checkout）。
#   首次部署请先用 deploy-linux.sh 或 git clone；本脚本专注「拉取最新 + 备份 + 迁移 + 重启」的升级动作。
# 用法：
#   sudo bash scripts/update-from-github.sh
#   sudo bash scripts/update-from-github.sh --install-dir /opt/gipfel
#   sudo bash scripts/update-from-github.sh --repo https://github.com/owner/repo.git        # 首次克隆
#   sudo bash scripts/update-from-github.sh --source-dir /path/to/checkout                  # 从本地 checkout 同步
#   sudo bash scripts/update-from-github.sh --with-nginx --domain comp.example.com           # 同步刷新并 reload nginx
#
# 代码来源（三选一，自动判定）：
#   模式 A  部署目录本身是 git clone        → 原地 git pull（推荐：服务器上 git clone 后日常更新）
#   模式 B  提供 --source-dir（本地 checkout）→ 该目录 git pull 后 rsync 同步到 INSTALL_DIR（同 deploy-linux.sh 模型）
#   模式 C  提供 --repo 且 INSTALL_DIR 为空  → git clone 到 INSTALL_DIR（首次拉起）
#
# 步骤：
#   1. 拉取最新代码（按上述模式）
#   2. 备份 db.sqlite3 + uploads + .env 到 _backup/<时间戳>（安全副本，migrate 前）
#   3. 更新后端：pip install -r requirements.txt → migrate → collectstatic
#   4. 更新前端：npm ci && npm run build → frontend-dist
#   5. chown 归属运行用户 gipfel，.env 权限 600
#   6. 刷新并重启 systemd 服务：把最新 deploy/*.service 重新落到 /etc/systemd/system/（替换 __INSTALL_DIR__，
#      daemon-reload），再 systemctl restart gipfel（+ gipfel-logviewer 日志查看器）。这一步保证仓库对服务单元
#      的改动（如 8121 端口修复）能传播到 live 单元，与 deploy-linux.sh 第 6 步一致。
#   7. [可选] --with-nginx：用最新 deploy/nginx-gipfel.conf 重新生成 vhost（按 --domain 保留对应日志查看器块）
#      并 reload（含 80 端口校验、默认站点禁用、防火墙放行）
#
# 注意：
#   - 数据文件（db.sqlite3 / uploads / .env / logs / staticfiles / .venv / node_modules / frontend-dist）
#     均已被 .gitignore 忽略（模式 B 的 rsync 也显式排除），更新不会触碰它们，业务数据在升级间自动保留。
#   - 若工作区有未提交的源码改动，git pull --ff-only 会失败并中止（避免覆盖），请先处理或 stash。
# ============================================================
set -euo pipefail

# ---------------- 参数解析 ----------------
DOMAIN=""
INSTALL_DIR=""
SOURCE_DIR=""
REPO=""
WITH_NGINX=0
PUBLIC_IP=""   # 显式指定公网 IP（无域名纯 IP 部署日志查看器用）；非空则跳过自动探测

usage() {
    cat <<EOF
Usage: $0 [options]
  --install-dir PATH       git clone 所在目录，默认取脚本上级目录（即 clone 根 /opt/gipfel）
  --source-dir PATH        本地源码 checkout；git pull 后 rsync 同步到 INSTALL_DIR（兼容 deploy-linux.sh 模型）
  --repo URL               仓库地址；当 INSTALL_DIR 非 git 仓库且目录为空时用于克隆
  --domain DOMAIN          公网域名（仅在 --with-nginx 时用于重写 nginx server_name）
  --public-ip IP           公网 IP（无 --domain 部署时日志查看器使用 http://<IP>:8120/）；
                          显式传入可跳过自动探测，确保受限网络下也能纠正内网 IP 或补全缺失行
  --with-nginx             更新后重新生成 nginx 虚拟主机并 reload
  -h, --help               显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir)      INSTALL_DIR="$2"; shift 2 ;;
        --source-dir)       SOURCE_DIR="$2"; shift 2 ;;
        --repo)             REPO="$2"; shift 2 ;;
        --domain)           DOMAIN="$2"; shift 2 ;;
        --public-ip)        PUBLIC_IP="$2"; shift 2 ;;
        --with-nginx)       WITH_NGINX=1; shift ;;
        -h|--help)          usage; exit 0 ;;
        *) echo "未知参数 $1"; usage; exit 2 ;;
    esac
done

[[ $EUID -ne 0 ]] && { echo "请用 sudo 执行"; exit 1; }

# 默认 INSTALL_DIR = 脚本所在目录的上级（clone 根）
if [[ -z "$INSTALL_DIR" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
    INSTALL_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
fi

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

# ---------------- 确定代码来源并拉取最新 ----------------
if [[ -d "$INSTALL_DIR/.git" ]]; then
    # 模式 A：部署目录本身是 clone → 原地 pull
    log "部署目录 $INSTALL_DIR 为 git 仓库，原地拉取最新"
    cd "$INSTALL_DIR"
    git pull --ff-only
    # 自更新：若本脚本自身被本次 pull 更新，用新版本重新执行，
    #   避免用旧脚本逻辑处理新代码。环境变量哨兵防止无限 re-exec；
    #   git pull --ff-only 幂等，重跑无副作用。仅当脚本位于 INSTALL_DIR 内才 re-exec。
    if [[ -z "${GIPFEL_UPDATE_REEXEC:-}" && "$0" == "$INSTALL_DIR"/* ]]; then
        export GIPFEL_UPDATE_REEXEC=1
        log "更新脚本自身已更新，重新执行新版本"
        exec "$0" "$@"
    fi
elif [[ -n "$SOURCE_DIR" && -d "$SOURCE_DIR/.git" ]]; then
    # 模式 B：从本地 source checkout pull 后 rsync 到 INSTALL_DIR（同 deploy-linux.sh 模型）
    log "从本地源码目录 $SOURCE_DIR 拉取最新并同步到 $INSTALL_DIR"
    git -C "$SOURCE_DIR" pull --ff-only
    mkdir -p "$INSTALL_DIR"
    # 排除数据/构建产物/缓存，确保线上 db/uploads/.env 不被覆盖（同 deploy-linux.sh）
    rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.pyc' \
        --exclude node_modules --exclude dist --exclude db.sqlite3 \
        --exclude uploads --exclude logs --exclude '.env' --exclude frontend-dist --exclude staticfiles \
        "$SOURCE_DIR/backend/"  "$INSTALL_DIR/backend/"
    rsync -a --delete --exclude node_modules --exclude dist \
        "$SOURCE_DIR/frontend/" "$INSTALL_DIR/frontend/"
    rsync -a --delete "$SOURCE_DIR/deploy/"   "$INSTALL_DIR/deploy/"
elif [[ -n "$REPO" ]]; then
    # 模式 C：克隆到 INSTALL_DIR（要求目录为空）
    if [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        err "INSTALL_DIR ($INSTALL_DIR) 非空，无法 git clone。请清空后重试，或改用 --source-dir。"
    fi
    log "克隆仓库 $REPO → $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
else
    err "无法确定代码来源：INSTALL_DIR ($INSTALL_DIR) 不是 git 仓库；也未提供 --source-dir 或 --repo。请先 git clone，或用 deploy-linux.sh 首次部署。"
fi


# ---------------- 运行用户（幂等）----------------
if ! id gipfel >/dev/null 2>&1; then
    log "创建专用运行用户 gipfel"
    useradd -r -s /usr/sbin/nologin -U -d "$INSTALL_DIR" gipfel || true
fi

# ---------------- 拉取已完成（见上方代码获取逻辑）----------------
ok "代码已更新到最新，开始应用更新"

# ---------------- 1. 备份数据库/上传/配置 ----------------
BACKUP_DIR="$INSTALL_DIR/_backup/$(date +%F_%H%M%S)"
mkdir -p "$BACKUP_DIR"
if [[ -f "$INSTALL_DIR/backend/db.sqlite3" ]]; then
    cp -a "$INSTALL_DIR/backend/db.sqlite3" "$BACKUP_DIR/" && log "已备份数据库 → $BACKUP_DIR/db.sqlite3"
fi
[[ -d "$INSTALL_DIR/backend/uploads" ]] && cp -a "$INSTALL_DIR/backend/uploads" "$BACKUP_DIR/" 2>/dev/null || true
[[ -f "$INSTALL_DIR/backend/.env" ]]    && cp -a "$INSTALL_DIR/backend/.env"    "$BACKUP_DIR/" 2>/dev/null || true

# ---------------- 2. 更新后端依赖 + 迁移 ----------------
log "更新后端（pip / migrate / collectstatic）"
cd "$INSTALL_DIR/backend"
if [[ ! -d .venv ]]; then
    log "虚拟环境不存在，创建并安装依赖"
    python3 -m venv .venv
    ".venv/bin/pip" install --upgrade pip setuptools wheel
fi
".venv/bin/pip" install -r requirements.txt
".venv/bin/python" manage.py check --fail-level ERROR
".venv/bin/python" manage.py migrate --noinput
".venv/bin/python" manage.py collectstatic --noinput
# 日志查看器静态资源（独立项目，settings=logviewer.settings）
log "收集日志查看器静态资源"
cd "$INSTALL_DIR/backend/logviewer"
"$INSTALL_DIR/backend/.venv/bin/python" manage.py collectstatic --noinput --settings=logviewer.settings
cd "$INSTALL_DIR/backend"
ok "后端依赖与数据库迁移完成"

# ---------------- 3. 更新前端构建 ----------------
log "更新前端（npm ci + build）"
cd "$INSTALL_DIR/frontend"
if [[ ! -d node_modules ]]; then
    npm ci --no-audit --no-fund
else
    # package-lock 变更时增量装；失败回退到 npm ci 保证一致性
    npm install --no-audit --no-fund 2>/dev/null || npm ci --no-audit --no-fund
fi
npm run build
rm -rf "$INSTALL_DIR/frontend-dist"
mkdir -p "$INSTALL_DIR/frontend-dist"
cp -a dist/. "$INSTALL_DIR/frontend-dist/"

# ---------------- 4. 文件归属与权限 ----------------
# 所有步骤以 root 身份写入（.venv / db.sqlite3 / uploads / logs / frontend-dist），
# 统一归属运行用户 gipfel，否则 systemd 以 gipfel 启动时无写权限。
chown -R gipfel:gipfel "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/backend/.env" 2>/dev/null || true
ok "文件归属已切换为 gipfel，.env 权限收紧为 600"

# 自愈：无域名部署时，纠正/补全 .env 中 LOG_VIEWER_PUBLIC_URL。
#   - 显式 --public-ip：无论当前有无/对错，都以它为准写入（覆盖内网 IP 或缺失该行）
#   - 否则：仅当当前值指向内网/私网 IP 才纠正；已是公网 IP/域名/缺失行则不动
# 公网 IP 探测失败则移除该行，改由后端按请求 Host 推导（nginx 透传 $host=公网 IP）。
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
                sed -i -E "/^LOG_VIEWER_PUBLIC_URL=/d" "$INSTALL_DIR/backend/.env"
                warn "公网 IP 探测失败，已移除 .env 中指向内网 IP(${LV_CUR}) 的 LOG_VIEWER_PUBLIC_URL，改由后端按请求 Host 推导公网地址。"
            fi
        fi
    fi
fi

# ---------------- 5. 刷新并重启 systemd 服务 ----------------
# 重要：升级时必须把最新的 deploy/*.service 重新落到 /etc/systemd/system/（替换 __INSTALL_DIR__），
#        否则仓库中对服务单元的改动（如日志查看器 8121 端口修复、ExecStart 变更）不会传播到 live 单元，
#        重启后仍使用旧配置。与 deploy-linux.sh 第 6 步保持一致。
refresh_unit() {
    local src="$1" name="$2"
    [[ -f "$src" ]] || { warn "找不到服务单元模板 $src，跳过刷新 $name"; return; }
    local tmp="$INSTALL_DIR/deploy/$(basename "$src")"
    sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$src" > "$tmp"
    cp -f "$tmp" "/etc/systemd/system/$name"
    systemctl enable "$name" 2>/dev/null || true
    ok "已刷新并启用服务单元 $name → /etc/systemd/system/$name"
}
refresh_unit "$INSTALL_DIR/deploy/gipfel.service" gipfel.service
refresh_unit "$INSTALL_DIR/deploy/logviewer.service" gipfel-logviewer.service
systemctl daemon-reload

if systemctl cat gipfel.service >/dev/null 2>&1; then
    log "重启 gipfel.service"
    systemctl restart gipfel
    sleep 2
    if ! systemctl is-active --quiet gipfel; then
        sleep 5
    fi
    systemctl is-active --quiet gipfel && ok "gipfel.service 已重启并运行中" || \
        { journalctl -u gipfel -n 30 --no-pager; err "gipfel 启动失败，见上方日志（可用备份 $BACKUP_DIR 回滚）"; }
else
    warn "gipfel.service 尚未注册（首次部署请先运行 deploy-linux.sh），跳过重启"
fi

# 日志查看器（独立站点）
if systemctl cat gipfel-logviewer.service >/dev/null 2>&1; then
    log "重启 gipfel-logviewer.service"
    systemctl restart gipfel-logviewer
    sleep 2
    if ! systemctl is-active --quiet gipfel-logviewer; then
        sleep 5
    fi
    systemctl is-active --quiet gipfel-logviewer && ok "gipfel-logviewer.service 已重启并运行中" || \
        { journalctl -u gipfel-logviewer -n 30 --no-pager; err "gipfel-logviewer 启动失败，见上方日志（可用备份 $BACKUP_DIR 回滚）"; }
else
    warn "gipfel-logviewer.service 尚未注册（首次部署请先运行 deploy-linux.sh），跳过重启"
fi

# ---------------- 6. nginx（可选）----------------
if [[ $WITH_NGINX -eq 1 ]]; then
    VHOST_TMPL="$INSTALL_DIR/deploy/nginx-gipfel.conf"
    [[ -f "$VHOST_TMPL" ]] || err "找不到 nginx 模板：$VHOST_TMPL"
    VHOST_OUT="/etc/nginx/sites-available/gipfel.conf"
    log "重新生成 nginx 虚拟主机"
    sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        -e "s|__DOMAIN__|${DOMAIN:-_}|g" \
        "$VHOST_TMPL" > "$VHOST_OUT"
    # 按是否传 --domain 保留日志查看器对应的 server 块（与 deploy-linux.sh 一致）：
    #   有域名 → 保留 log.<DOMAIN> 子域块，删除 8120 端口块；
    #   无域名（纯 IP）→ 保留 8120 端口块，删除子域块（server_name log._ 形同失效，移除避免歧义）。
    if [[ -n "$DOMAIN" ]]; then
        sed -i '/# === LOGVIEWER_PORT8120_START ===/,/# === LOGVIEWER_PORT8120_END ===/d' "$VHOST_OUT"
    else
        sed -i '/# === LOGVIEWER_SUBDOMAIN_START ===/,/# === LOGVIEWER_SUBDOMAIN_END ===/d' "$VHOST_OUT"
    fi
    # 按 nginx.conf 实际 include 风格放置 gipfel 配置（兼容 sites-enabled 与仅 include conf.d 的精简镜像）
    if grep -q 'sites-enabled' /etc/nginx/nginx.conf 2>/dev/null; then
        ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
        rm -f /etc/nginx/conf.d/gipfel.conf
        ok "已启用 gipfel nginx 虚拟主机（sites-enabled/gipfel.conf）"
    elif grep -q 'conf.d' /etc/nginx/nginx.conf 2>/dev/null; then
        cp -f /etc/nginx/sites-available/gipfel.conf /etc/nginx/conf.d/gipfel.conf
        rm -f /etc/nginx/sites-enabled/gipfel.conf
        ok "已启用 gipfel nginx 虚拟主机（conf.d/gipfel.conf，因 nginx.conf 仅 include conf.d）"
    else
        ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
        cp -f /etc/nginx/sites-available/gipfel.conf /etc/nginx/conf.d/gipfel.conf
        ok "已启用 gipfel nginx 虚拟主机（sites-enabled + conf.d 均放置，兜底）"
    fi
    # 禁用 nginx 自带默认欢迎页：枚举所有已知变体并删除，否则 80 端口可能被默认站点抢走
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
    # 无域名：日志查看器经 8120 端口暴露公网，需放行防火墙（与 deploy-linux.sh 一致）
    if [[ -z "$DOMAIN" ]]; then
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
ok "更新完成！"
echo "  部署目录：    $INSTALL_DIR"
echo "  备份位置：    $BACKUP_DIR"
echo "  后端状态：    systemctl status gipfel"
echo "  日志查看器：  systemctl status gipfel-logviewer"
echo "  健康检查：    curl -sS http://127.0.0.1:8000/api/health"
if [[ $WITH_NGINX -eq 1 ]]; then
echo "  网站：        ${DOMAIN:-http://$(hostname -I | awk '{print $1}')}"
fi
echo "  日志：        journalctl -u gipfel -f   /   tail -F $INSTALL_DIR/backend/logs/app.log"

# 明确退出，避免依赖上一条命令的偶然退出码
exit 0
