#!/bin/bash
# 快速优化脚本 - 立即提升并发性能
# 适用于 SQLite 环境，无需迁移数据库
#
# 使用方法：在项目根目录执行
#   sudo bash deploy/quick-optimize.sh

set -e

# 自动检测项目路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
NGINX_CONF="/etc/nginx/sites-available/gipfel"

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
echo "  Gipfel 并发性能快速优化脚本"
echo "============================================================"
echo ""
echo "项目路径: $PROJECT_DIR"
echo ""

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo "请使用 root 用户运行此脚本: sudo bash deploy/quick-optimize.sh"
    exit 1
fi

# ==================== 1. 优化 SQLite 配置 ====================
info "Step 1: 优化 SQLite 配置..."
cd "$BACKEND_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

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

success "SQLite WAL 模式已启用"
echo ""

# ==================== 2. 更新 Nginx 配置 ====================
info "Step 2: 更新 Nginx 配置..."
if [ -f "$PROJECT_DIR/deploy/nginx-gipfel-optimized.conf" ]; then
    cp "$PROJECT_DIR/deploy/nginx-gipfel-optimized.conf" "$NGINX_CONF"
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    success "Nginx 配置已更新"
else
    warn "Nginx 配置文件不存在，跳过"
fi
echo ""

# ==================== 3. 增加系统文件描述符限制 ====================
info "Step 3: 优化系统限制..."
if ! grep -q "Gipfel 优化" /etc/security/limits.conf; then
    cat >> /etc/security/limits.conf << 'EOF'

# Gipfel 优化
* soft nofile 65535
* hard nofile 65535
* soft nproc 65535
* hard nproc 65535
EOF
    success "系统限制已优化"
else
    warn "系统限制已配置，跳过"
fi
echo ""

# ==================== 4. 优化内核参数 ====================
info "Step 4: 优化内核参数..."
if ! grep -q "Gipfel 网络优化" /etc/sysctl.conf; then
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
    success "内核参数已优化"
else
    warn "内核参数已配置，跳过"
fi
echo ""

# ==================== 5. 创建 Daphne 日志目录 ====================
info "Step 5: 创建日志目录..."
mkdir -p /var/log/daphne
chown -R www-data:www-data /var/log/daphne
success "日志目录已创建"
echo ""

# ==================== 6. 重启服务 ====================
info "Step 6: 重启服务..."

# 重启 Nginx
if command -v nginx &> /dev/null; then
    nginx -t && systemctl restart nginx
    success "Nginx 已重启"
fi

# 停止旧的 Daphne 进程
pkill -f "daphne.*backend.asgi" 2>/dev/null || true
sleep 2

# 启动新的多 worker
if [ -f "$PROJECT_DIR/deploy/start-daphne-workers.sh" ]; then
    bash "$PROJECT_DIR/deploy/start-daphne-workers.sh"
else
    warn "Daphne 启动脚本不存在，请手动启动"
fi
echo ""

echo "============================================================"
echo "  ✓ 优化完成！"
echo "============================================================"
echo ""
echo "预期效果:"
echo "  - 并发能力：从 ~50 提升到 200-300"
echo "  - 响应时间：降低 30-50%"
echo "  - 超时错误：大幅减少"
echo ""
echo "如果仍有超时，建议迁移到 PostgreSQL:"
echo "  bash deploy/migrate-to-postgresql.sh"
echo ""
echo "监控命令:"
echo "  - 查看进程: ps aux | grep daphne"
echo "  - 查看状态: systemctl status nginx"
echo "  - 查看连接: ss -s"
echo "  - 实时日志: tail -f /var/log/daphne/*.log"
echo "============================================================"