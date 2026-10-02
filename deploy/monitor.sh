#!/bin/bash
# Gipfel 服务监控脚本
# 用于检查优化效果和排查问题
#
# 使用方法：在项目根目录执行
#   bash deploy/monitor.sh

# 自动检测项目路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"

echo ""
echo "============================================================"
echo "  Gipfel 服务状态监控"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""
echo "项目路径: $PROJECT_DIR"
echo ""

# 1. 系统资源
echo "【系统资源】"
echo "CPU 使用率:"
top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1
echo ""
echo "内存使用:"
free -h | grep Mem
echo ""
echo "磁盘使用:"
df -h / | tail -1
echo ""

# 2. Daphne 进程状态
echo "【Daphne 进程】"
DAPHNE_COUNT=$(ps aux | grep "daphne.*backend.asgi" | grep -v grep | wc -l)
echo "运行中的 Worker 数量: $DAPHNE_COUNT"
if [ $DAPHNE_COUNT -gt 0 ]; then
    echo "进程详情:"
    ps aux | grep "daphne.*backend.asgi" | grep -v grep | awk '{print "  PID: "$2" | CPU: "$3"% | MEM: "$4"% | 启动时间: "$9}'
else
    echo "⚠ 没有运行中的 Daphne 进程！"
fi
echo ""

# 3. Nginx 状态
echo "【Nginx 状态】"
if systemctl is-active --quiet nginx; then
    echo "状态: ✓ 运行中"
else
    echo "状态: ✗ 未运行"
fi
echo ""

# 4. 数据库状态
echo "【数据库状态】"
cd "$BACKEND_DIR" 2>/dev/null || cd backend
if [ -d ".venv" ]; then
    source .venv/bin/activate 2>/dev/null
fi

# 检查数据库类型
if grep -q "django.db.backends.postgresql" "$BACKEND_DIR/backend/settings.py" 2>/dev/null; then
    echo "数据库: PostgreSQL"
    if systemctl is-active --quiet postgresql; then
        echo "PostgreSQL 服务: ✓ 运行中"
        # 查询连接数
        sudo -u postgres psql -d gipfel -c "SELECT count(*) as connections FROM pg_stat_activity;" 2>/dev/null || echo "  (无法查询连接数)"
    else
        echo "PostgreSQL 服务: ✗ 未运行"
    fi
elif [ -f "$BACKEND_DIR/db.sqlite3" ]; then
    echo "数据库: SQLite"
    echo "数据库文件: $BACKEND_DIR/db.sqlite3"
    echo "数据库大小: $(du -h "$BACKEND_DIR/db.sqlite3" 2>/dev/null | cut -f1 || echo '未知')"
    
    # 检查 WAL 模式
    if command -v python3 &> /dev/null && [ -d ".venv" ]; then
        WAL_MODE=$(python manage.py dbshell -c "PRAGMA journal_mode;" 2>/dev/null | head -1 || echo "未知")
        echo "WAL 模式: $WAL_MODE"
    fi
else
    echo "数据库: 未找到"
fi
echo ""

# 5. 网络连接
echo "【网络连接】"
echo "TCP 连接统计:"
ss -s 2>/dev/null | grep -A 2 "TCP:" || echo "  (无法获取)"
echo ""
echo "监听端口:"
ss -tlnp 2>/dev/null | grep -E "8000|8001|8002|8003|80" | awk '{print "  "$4}' || echo "  (无法获取)"
echo ""

# 6. 最近错误日志
echo "【最近错误日志】"
echo "Daphne 错误 (最近5条):"
if [ -d "/var/log/daphne" ]; then
    tail -5 /var/log/daphne/daphne_*.log 2>/dev/null || echo "  (无日志)"
else
    echo "  (日志目录不存在)"
fi
echo ""
echo "Nginx 错误 (最近5条):"
tail -5 /var/log/nginx/error.log 2>/dev/null || echo "  (无日志)"
echo ""

# 7. 性能建议
echo "【性能建议】"
if [ $DAPHNE_COUNT -lt 4 ]; then
    echo "⚠ Daphne worker 数量不足，建议启动 4 个"
    echo "  运行: bash deploy/start-daphne-workers.sh"
fi

LOAD=$(cat /proc/loadavg | awk '{print $1}')
CORES=$(nproc)
if (( $(echo "$LOAD > $CORES" | bc -l 2>/dev/null || echo 0) )); then
    echo "⚠ 系统负载过高 ($LOAD > $CORES 核心)"
fi

echo ""
echo "============================================================"
echo "  监控完成"
echo "============================================================"
echo ""
echo "常用命令:"
echo "  - 实时监控: watch -n 2 'bash deploy/monitor.sh'"
echo "  - 查看日志: tail -f /var/log/daphne/*.log"
echo "  - 重启服务: bash deploy/start-daphne-workers.sh"
echo "  - 快速优化: sudo bash deploy/quick-optimize.sh"
echo "  - 数据库迁移: sudo bash deploy/migrate-to-postgresql.sh"
echo ""