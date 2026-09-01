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
#   6. systemctl restart gipfel（+ gipfel-logviewer 日志查看器）
#   7. [可选] --with-nginx：用最新 deploy/nginx-gipfel.conf 重新生成 vhost 并 reload
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

usage() {
    cat <<EOF
Usage: $0 [options]
  --install-dir PATH       git clone 所在目录，默认取脚本上级目录（即 clone 根 /opt/gipfel）
  --source-dir PATH        本地源码 checkout；git pull 后 rsync 同步到 INSTALL_DIR（兼容 deploy-linux.sh 模型）
  --repo URL               仓库地址；当 INSTALL_DIR 非 git 仓库且目录为空时用于克隆
  --domain DOMAIN          公网域名（仅在 --with-nginx 时用于重写 nginx server_name）
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

# ---------------- 确定代码来源并拉取最新 ----------------
if [[ -d "$INSTALL_DIR/.git" ]]; then
    # 模式 A：部署目录本身是 clone → 原地 pull
    log "部署目录 $INSTALL_DIR 为 git 仓库，原地拉取最新"
    cd "$INSTALL_DIR"
    git pull --ff-only
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

# ---------------- 5. 重启服务 ----------------
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
    log "重新生成 nginx 虚拟主机"
    sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
        -e "s|__DOMAIN__|${DOMAIN:-_}|g" \
        "$VHOST_TMPL" > /etc/nginx/sites-available/gipfel.conf
    # 始终刷新 gipfel vhost 软链（修复任何陈旧/损坏软链）
    ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
    ok "已启用 gipfel nginx 虚拟主机（sites-enabled/gipfel.conf）"
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
    systemctl reload nginx
    ok "nginx 配置已 reload"
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
