#!/usr/bin/env bash
# ============================================================
# Gipfel 快速数据同步脚本
# 用途：在两台服务器之间快速同步数据（增量）
#
# 使用方法：
#   从本机推送到远程：
#     bash scripts/quick-sync.sh push user@remote-ip
#
#   从远程拉取到本机：
#     bash scripts/quick-sync.sh pull user@remote-ip
#
#   指定安装目录：
#     bash scripts/quick-sync.sh push user@remote-ip /opt/gipfel
# ============================================================

set -euo pipefail

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# 参数
ACTION="${1:-}"
REMOTE="${2:-}"
INSTALL_DIR="${3:-/opt/gipfel}"

if [[ -z "$ACTION" || -z "$REMOTE" ]]; then
    echo "用法: $0 <push|pull> <user@host> [install-dir]"
    echo ""
    echo "示例:"
    echo "  $0 push root@192.168.1.100"
    echo "  $0 pull root@192.168.1.50 /opt/gipfel"
    exit 1
fi

# 同步的数据列表
SYNC_ITEMS=(
    "backend/db.sqlite3"
    "backend/uploads/"
    "backend/.env"
    "backend/logs/"
)

log_info "开始同步..."
log_info "方向: $ACTION"
log_info "目标: $REMOTE"
log_info "目录: $INSTALL_DIR"
echo ""

for item in "${SYNC_ITEMS[@]}"; do
    src="$INSTALL_DIR/$item"
    dst="$INSTALL_DIR/$(dirname "$item")/"

    if [[ "$ACTION" == "push" ]]; then
        if [[ -e "$src" ]]; then
            log_info "推送: $item"
            rsync -avz --progress -e "ssh -o StrictHostKeyChecking=accept-new" "$src" "$REMOTE:$dst"
        else
            log_warn "跳过（不存在）: $item"
        fi
    elif [[ "$ACTION" == "pull" ]]; then
        log_info "拉取: $item"
        mkdir -p "$(dirname "$src")"
        rsync -avz --progress -e "ssh -o StrictHostKeyChecking=accept-new" "$REMOTE:$src" "$(dirname "$src")/"
    else
        log_error "未知操作: $ACTION（应为 push 或 pull）"
        exit 1
    fi
    echo ""
done

log_info "同步完成！"
echo ""
log_info "如需重启服务，请在目标服务器执行："
log_info "  sudo systemctl restart gipfel gipfel-logviewer"
