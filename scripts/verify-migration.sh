#!/usr/bin/env bash
# ============================================================
# Gipfel 迁移验证脚本
# 用途：检查服务器迁移后的服务状态
#
# 使用方法：
#   bash scripts/verify-migration.sh [install-dir]
# ============================================================

set -euo pipefail

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check_pass() { echo -e "  ${GREEN}✓${NC} $*"; ((PASS++)); }
check_fail() { echo -e "  ${RED}✗${NC} $*"; ((FAIL++)); }
check_warn() { echo -e "  ${YELLOW}⚠${NC} $*"; ((WARN++)); }

INSTALL_DIR="${1:-/opt/gipfel}"

echo "=========================================="
echo "Gipfel 迁移验证"
echo "安装目录: $INSTALL_DIR"
echo "=========================================="
echo ""

# ---------- 文件检查 ----------
echo "[1/5] 检查文件完整性..."

if [[ -f "$INSTALL_DIR/backend/db.sqlite3" ]]; then
    size=$(stat -f%z "$INSTALL_DIR/backend/db.sqlite3" 2>/dev/null || stat -c%s "$INSTALL_DIR/backend/db.sqlite3" 2>/dev/null || echo "0")
    if [[ "$size" -gt 0 ]]; then
        check_pass "数据库文件存在 ($(numfmt --to=iec $size 2>/dev/null || echo "$size bytes"))"
    else
        check_fail "数据库文件为空"
    fi
else
    check_fail "数据库文件不存在: $INSTALL_DIR/backend/db.sqlite3"
fi

if [[ -f "$INSTALL_DIR/backend/.env" ]]; then
    check_pass "环境配置文件存在"
else
    check_fail "环境配置文件不存在: $INSTALL_DIR/backend/.env"
fi

if [[ -d "$INSTALL_DIR/backend/uploads" ]]; then
    count=$(find "$INSTALL_DIR/backend/uploads" -type f 2>/dev/null | wc -l)
    check_pass "上传目录存在 ($count 个文件)"
else
    check_warn "上传目录不存在（可能是新安装）"
fi

if [[ -d "$INSTALL_DIR/frontend-dist" ]]; then
    check_pass "前端构建产物存在"
else
    check_fail "前端构建产物不存在"
fi

echo ""

# ---------- 服务检查 ----------
echo "[2/5] 检查系统服务..."

if systemctl is-active --quiet gipfel 2>/dev/null; then
    check_pass "gipfel 服务运行中"
else
    check_warn "gipfel 服务未运行"
fi

if systemctl is-active --quiet gipfel-logviewer 2>/dev/null; then
    check_pass "gipfel-logviewer 服务运行中"
else
    check_warn "gipfel-logviewer 服务未运行"
fi

if systemctl is-active --quiet nginx 2>/dev/null; then
    check_pass "nginx 服务运行中"
else
    check_warn "nginx 服务未运行"
fi

echo ""

# ---------- API 检查 ----------
echo "[3/5] 检查 API 响应..."

if command -v curl >/dev/null 2>&1; then
    response=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health 2>/dev/null || echo "000")
    if [[ "$response" == "200" ]]; then
        check_pass "API 健康检查通过 (HTTP 200)"
    else
        check_fail "API 健康检查失败 (HTTP $response)"
    fi
else
    check_warn "curl 未安装，跳过 API 检查"
fi

echo ""

# ---------- 权限检查 ----------
echo "[4/5] 检查文件权限..."

if [[ -f "$INSTALL_DIR/backend/.env" ]]; then
    perms=$(stat -c%a "$INSTALL_DIR/backend/.env" 2>/dev/null || echo "unknown")
    if [[ "$perms" == "600" || "$perms" == "640" ]]; then
        check_pass ".env 文件权限正确 ($perms)"
    else
        check_warn ".env 文件权限较宽松 ($perms)，建议设置为 600"
    fi
fi

if [[ -d "$INSTALL_DIR/backend" ]]; then
    owner=$(stat -c%U "$INSTALL_DIR/backend" 2>/dev/null || echo "unknown")
    if [[ "$owner" == "gipfel" ]]; then
        check_pass "backend 目录所有者正确 (gipfel)"
    else
        check_warn "backend 目录所有者为 $owner（建议为 gipfel）"
    fi
fi

echo ""

# ---------- 配置检查 ----------
echo "[5/5] 检查配置文件..."

if [[ -f "/etc/nginx/sites-enabled/gipfel.conf" ]]; then
    check_pass "nginx 配置已启用"
else
    check_warn "nginx 配置未启用（可能需要创建软链接）"
fi

if [[ -f "/etc/systemd/system/gipfel.service" ]]; then
    check_pass "systemd 服务文件已安装"
else
    check_warn "systemd 服务文件未安装"
fi

echo ""

# ---------- 总结 ----------
echo "=========================================="
echo "验证结果"
echo "=========================================="
echo -e "  ${GREEN}通过: $PASS${NC}"
echo -e "  ${RED}失败: $FAIL${NC}"
echo -e "  ${YELLOW}警告: $WARN${NC}"
echo ""

if [[ $FAIL -gt 0 ]]; then
    echo -e "${RED}存在失败项，请检查并修复！${NC}"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo -e "${YELLOW}存在警告项，建议检查。${NC}"
    exit 0
else
    echo -e "${GREEN}所有检查通过！迁移成功！${NC}"
    exit 0
fi
