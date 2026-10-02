#!/bin/bash
# Gipfel 服务监控脚本
# 用于检查优化效果和排查问题

echo "=========================================="
echo "  Gipfel 服务状态监控"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
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
    echo "活跃连接:"
    curl -s http://127.0.0.1/nginx_status 2>/dev/null || echo "  (nginx_status 未启用)"
else
    echo "状态: ✗ 未运行"
fi
echo ""

# 4. 数据库状态
echo "【数据库状态】"
cd /opt/gipfel/backend 2>/dev/null || cd backend
source .venv/bin/activate 2>/dev/null

# 检查 SQLite WAL 模式
if [ -f "db.sqlite3" ]; then
    echo "SQLite 数据库: ✓ 存在"
    echo "数据库大小: $(du -h db.sqlite3 | cut -f1)"
    
    # 检查 WAL 模式
    WAL_MODE=$(python manage.py dbshell -c "PRAGMA journal_mode;" 2>/dev/null | head -1)
    if [ "$WAL_MODE" = "wal" ]; then
        echo "WAL 模式: ✓ 已启用"
    else
        echo "WAL 模式: ✗ 未启用 (当前: $WAL_MODE)"
    fi
else
    echo "SQLite 数据库: ✗ 不存在"
fi

# 检查 MySQL（如果配置了）
if grep -q "django.db.backends.mysql" backend/settings.py 2>/dev/null; then
    echo "MySQL: 已配置"
    if systemctl is-active --quiet mysql; then
        echo "MySQL 服务: ✓ 运行中"
    else
        echo "MySQL 服务: ✗ 未运行"
    fi
fi
echo ""

# 5. 网络连接
echo "【网络连接】"
echo "TCP 连接统计:"
ss -s | grep -A 2 "TCP:"
echo ""
echo "监听端口:"
ss -tlnp | grep -E "8000|8001|8002|8003|80" | awk '{print "  "$4}'
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
fi

if [ $(free | grep Mem | awk '{print $7}') -lt 2000000 ]; then
    echo "⚠ 可用内存不足 2GB，考虑减少 worker 数量"
fi

LOAD=$(cat /proc/loadavg | awk '{print $1}')
CORES=$(nproc)
if (( $(echo "$LOAD > $CORES" | bc -l) )); then
    echo "⚠ 系统负载过高 ($LOAD > $CORES 核心)"
fi

echo ""
echo "=========================================="
echo "  监控完成"
echo "=========================================="
echo ""
echo "常用命令："
echo "  - 实时监控: watch -n 2 '$0'"
echo "  - 查看日志: tail -f /var/log/daphne/*.log"
echo "  - 重启服务: systemctl restart gipfel-daphne"
echo "  - 性能测试: ab -n 1000 -c 200 http://localhost/api/health"
echo ""