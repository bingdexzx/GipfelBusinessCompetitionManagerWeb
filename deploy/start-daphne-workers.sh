#!/bin/bash
# Daphne 多 Worker 启动脚本
# 用于 8核 CPU，启动 4 个 worker 进程

set -e

# 配置
WORKERS=4
BASE_PORT=8000
PROJECT_DIR="/opt/gipfel/backend"
LOG_DIR="/var/log/daphne"
VENV_DIR="/opt/gipfel/backend/.venv"

# 创建日志目录
mkdir -p $LOG_DIR

# 停止现有 Daphne 进程
echo "Stopping existing Daphne processes..."
pkill -f "daphne.*backend.asgi" || true
sleep 2

# 激活虚拟环境
source $VENV_DIR/bin/activate

# 启动 workers
for i in $(seq 0 $((WORKERS - 1))); do
    PORT=$((BASE_PORT + i))
    echo "Starting Daphne worker $((i + 1)) on port $PORT..."
    
    nohup daphne \
        -b 127.0.0.1 \
        -p $PORT \
        -v 1 \
        --access-log $LOG_DIR/access_$PORT.log \
        --ping-interval 30 \
        --ping-timeout 10 \
        backend.asgi:application \
        > $LOG_DIR/daphne_$PORT.log 2>&1 &
    
    echo "Worker $((i + 1)) started with PID $!"
done

echo ""
echo "=========================================="
echo "All $WORKERS Daphne workers started!"
echo "Ports: $BASE_PORT - $((BASE_PORT + WORKERS - 1))"
echo "Logs: $LOG_DIR/"
echo "=========================================="
echo ""
echo "Use 'pkill -f daphne' to stop all workers"
echo "Use 'tail -f $LOG_DIR/daphne_*.log' to monitor"