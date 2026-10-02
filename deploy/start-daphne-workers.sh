#!/bin/bash
# Daphne 多 Worker 启动脚本
# 用于 8核 CPU，启动 4 个 worker 进程
#
# 使用方法：在项目根目录执行
#   bash deploy/start-daphne-workers.sh

set -e

# 自动检测项目路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
LOG_DIR="/var/log/daphne"
VENV_DIR="$BACKEND_DIR/.venv"

# 配置
WORKERS=4
BASE_PORT=8000

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo "============================================================"
echo "  Daphne 多 Worker 启动脚本"
echo "============================================================"
echo ""
echo "项目路径: $BACKEND_DIR"
echo "Worker 数量: $WORKERS"
echo "端口范围: $BASE_PORT - $((BASE_PORT + WORKERS - 1))"
echo ""

# 创建日志目录
mkdir -p "$LOG_DIR"

# 停止现有 Daphne 进程
info "停止现有 Daphne 进程..."
pkill -f "daphne.*backend.asgi" 2>/dev/null || true
sleep 2

# 检查虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    warn "虚拟环境不存在: $VENV_DIR"
    warn "请先创建虚拟环境: python3 -m venv $VENV_DIR"
    exit 1
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 启动 workers
for i in $(seq 0 $((WORKERS - 1))); do
    PORT=$((BASE_PORT + i))
    info "启动 Daphne worker $((i + 1))，端口: $PORT..."
    
    nohup daphne \
        -b 127.0.0.1 \
        -p $PORT \
        -v 1 \
        --access-log "$LOG_DIR/access_$PORT.log" \
        --ping-interval 30 \
        --ping-timeout 10 \
        backend.asgi:application \
        > "$LOG_DIR/daphne_$PORT.log" 2>&1 &
    
    success "Worker $((i + 1)) 启动成功 (PID: $!)"
done

echo ""
echo "============================================================"
echo "  ✓ 所有 Worker 启动完成！"
echo "============================================================"
echo ""
echo "端口: $BASE_PORT - $((BASE_PORT + WORKERS - 1))"
echo "日志: $LOG_DIR/"
echo ""
echo "常用命令:"
echo "  查看进程: ps aux | grep daphne"
echo "  查看日志: tail -f $LOG_DIR/daphne_*.log"
echo "  停止所有: pkill -f daphne"
echo "============================================================"