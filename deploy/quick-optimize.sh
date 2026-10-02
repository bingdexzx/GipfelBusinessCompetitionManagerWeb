#!/bin/bash
# 快速优化脚本 - 立即提升并发性能
# 适用于 SQLite 环境，无需迁移数据库

set -e

echo "=========================================="
echo "  Gipfel 并发性能快速优化脚本"
echo "=========================================="
echo ""

PROJECT_DIR="/opt/gipfel"
BACKEND_DIR="$PROJECT_DIR/backend"
NGINX_CONF="/etc/nginx/sites-available/gipfel"

# 1. 优化 SQLite 配置
echo "Step 1: 优化 SQLite 配置..."
cd $BACKEND_DIR
source .venv/bin/activate

# 启用 WAL 模式
python manage.py dbshell << 'EOF'
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA busy_timeout=5000;
PRAGMA temp_store=MEMORY;
PRAGMA mmap_size=268435456;
.quit
EOF

echo "✓ SQLite WAL 模式已启用"
echo ""

# 2. 复制优化后的 Nginx 配置
echo "Step 2: 更新 Nginx 配置..."
if [ -f "$PROJECT_DIR/deploy/nginx-gipfel-optimized.conf" ]; then
    cp "$PROJECT_DIR/deploy/nginx-gipfel-optimized.conf" "$NGINX_CONF"
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    echo "✓ Nginx 配置已更新"
else
    echo "⚠ Nginx 配置文件不存在，跳过"
fi
echo ""

# 3. 增加系统文件描述符限制
echo "Step 3: 优化系统限制..."
cat >> /etc/security/limits.conf << 'EOF'

# Gipfel 优化
* soft nofile 65535
* hard nofile 65535
* soft nproc 65535
* hard nproc 65535
EOF

echo "✓ 系统限制已优化"
echo ""

# 4. 优化内核参数
echo "Step 4: 优化内核参数..."
cat >> /etc/sysctl.conf << 'EOF'

# Gipfel 网络优化
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
net.core.netdev_max_backlog = 65535
EOF

sysctl -p
echo "✓ 内核参数已优化"
echo ""

# 5. 创建 Daphne 日志目录
echo "Step 5: 创建日志目录..."
mkdir -p /var/log/daphne
chown -R www-data:www-data /var/log/daphne
echo "✓ 日志目录已创建"
echo ""

# 6. 安装 systemd 服务
echo "Step 6: 安装 systemd 服务..."
if [ -f "$PROJECT_DIR/deploy/gipfel-daphne.service" ]; then
    cp "$PROJECT_DIR/deploy/gipfel-daphne.service" /etc/systemd/system/
    systemctl daemon-reload
    echo "✓ systemd 服务已安装"
else
    echo "⚠ 服务文件不存在，跳过"
fi
echo ""

# 7. 重启服务
echo "Step 7: 重启服务..."
nginx -t && systemctl restart nginx
echo "✓ Nginx 已重启"

# 停止旧的 Daphne 进程
pkill -f "daphne.*backend.asgi" || true
sleep 2

# 启动新的多 worker
bash "$PROJECT_DIR/deploy/start-daphne-workers.sh"
echo ""

echo "=========================================="
echo "  优化完成！"
echo "=========================================="
echo ""
echo "预期效果："
echo "  - 并发能力：从 ~50 提升到 200-300"
echo "  - 响应时间：降低 30-50%"
echo "  - 超时错误：大幅减少"
echo ""
echo "如果仍有超时，建议迁移到 MySQL："
echo "  参考 deploy/mysql-migration-guide.md"
echo ""
echo "监控命令："
echo "  - 查看 Daphne 进程: ps aux | grep daphne"
echo "  - 查看 Nginx 状态: systemctl status nginx"
echo "  - 查看连接数: ss -s"
echo "  - 实时日志: tail -f /var/log/daphne/*.log"
echo ""