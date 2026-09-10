#!/usr/bin/env bash
# ============================================================
# Gipfel 服务器迁移脚本
# 用途：将服务从旧服务器完整迁移到新服务器
#
# 使用方法：
#   在旧服务器上执行（推送模式）：
#     sudo bash scripts/migrate-server.sh --mode push --target user@new-server-ip --install-dir /opt/gipfel
#
#   在新服务器上执行（拉取模式）：
#     sudo bash scripts/migrate-server.sh --mode pull --source user@old-server-ip --install-dir /opt/gipfel
#
# 功能：
#   1. 自动备份旧服务器数据（SQLite、uploads、.env、logs）
#   2. 通过 rsync 安全传输到新服务器
#   3. 在新服务器恢复数据并启动服务
#   4. 支持增量同步（仅传输变更文件）
# ============================================================

set -euo pipefail

# ==================== 颜色输出 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $*"; }

# ==================== 默认参数 ====================
MODE=""
SOURCE=""
TARGET=""
INSTALL_DIR="/opt/gipfel"
BACKUP_DIR="/tmp/gipfel-migration-$(date +%Y%m%d_%H%M%S)"
SKIP_SERVICES=false
DRY_RUN=false
SSH_PORT=22
SSH_KEY=""

# ==================== 参数解析 ====================
usage() {
    cat <<EOF
用法: $0 [选项]

必选参数（二选一）：
  --mode push --target USER@HOST    推送模式：从本机推送到目标服务器
  --mode pull --source USER@HOST    拉取模式：从源服务器拉取到本机

可选参数：
  --install-dir DIR     安装目录（默认: /opt/gipfel）
  --backup-dir DIR      临时备份目录（默认: /tmp/gipfel-migration-<时间戳>）
  --skip-services       跳过服务配置（仅传输数据）
  --dry-run             模拟运行，不实际执行
  --ssh-port PORT       SSH 端口（默认: 22）
  --ssh-key PATH        SSH 私钥路径
  -h, --help            显示帮助

示例：
  # 推送到新服务器
  sudo $0 --mode push --target root@192.168.1.100 --install-dir /opt/gipfel

  # 从旧服务器拉取
  sudo $0 --mode pull --source root@192.168.1.50 --install-dir /opt/gipfel

  # 使用自定义 SSH 端口和密钥
  sudo $0 --mode push --target root@192.168.1.100 --ssh-port 2222 --ssh-key ~/.ssh/id_rsa
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)       MODE="$2"; shift 2 ;;
        --source)     SOURCE="$2"; shift 2 ;;
        --target)     TARGET="$2"; shift 2 ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
        --skip-services) SKIP_SERVICES=true; shift ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --ssh-port)   SSH_PORT="$2"; shift 2 ;;
        --ssh-key)    SSH_KEY="$2"; shift 2 ;;
        -h|--help)    usage ;;
        *)            log_error "未知参数: $1"; usage ;;
    esac
done

# ==================== 参数验证 ====================
if [[ -z "$MODE" ]]; then
    log_error "必须指定 --mode (push 或 pull)"
    usage
fi

if [[ "$MODE" == "push" && -z "$TARGET" ]]; then
    log_error "推送模式必须指定 --target USER@HOST"
    usage
fi

if [[ "$MODE" == "pull" && -z "$SOURCE" ]]; then
    log_error "拉取模式必须指定 --source USER@HOST"
    usage
fi

# SSH 命令构建
SSH_OPTS="-p $SSH_PORT -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

RSYNC_SSH="ssh $SSH_OPTS"

# ==================== 辅助函数 ====================

# 检查远程命令是否存在
check_remote_command() {
    local host="$1"
    local cmd="$2"
    ssh $SSH_OPTS "$host" "command -v $cmd >/dev/null 2>&1" 2>/dev/null
}

# 在远程执行命令
remote_exec() {
    local host="$1"
    shift
    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] 远程执行: $*"
        return 0
    fi
    ssh $SSH_OPTS "$host" "$@"
}

# rsync 传输
rsync_transfer() {
    local src="$1"
    local dst="$2"
    local extra_opts="${3:-}"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] rsync $src → $dst"
        return 0
    fi

    rsync -avz --progress \
        -e "$RSYNC_SSH" \
        --timeout=300 \
        $extra_opts \
        "$src" "$dst"
}

# ==================== 数据清单 ====================
# 需要迁移的数据（相对于 INSTALL_DIR）
DATA_ITEMS=(
    "backend/db.sqlite3"          # SQLite 数据库
    "backend/uploads"             # 用户上传文件
    "backend/.env"                # 环境变量配置
    "backend/logs"                # 应用日志
    "backend/staticfiles"         # Django 静态文件
    "backend/logviewer/staticfiles"  # 日志查看器静态文件
)

# 需要迁移的配置文件
CONFIG_ITEMS=(
    "deploy/gipfel.service"
    "deploy/logviewer.service"
    "deploy/nginx-gipfel.conf"
)

# ==================== 主流程 ====================

log_step "=========================================="
log_step "Gipfel 服务器迁移工具"
log_step "模式: $MODE"
log_step "安装目录: $INSTALL_DIR"
log_step "=========================================="

# ---------- 推送模式 ----------
if [[ "$MODE" == "push" ]]; then
    REMOTE="$TARGET"

    log_step "[1/6] 检查本机源目录..."
    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_error "本机安装目录不存在: $INSTALL_DIR"
        exit 1
    fi
    log_info "源目录检查通过"

    log_step "[2/6] 检查目标服务器连接..."
    if ! ssh $SSH_OPTS "$REMOTE" "echo ok" >/dev/null 2>&1; then
        log_error "无法连接到目标服务器: $REMOTE"
        log_error "请检查 SSH 连接和防火墙设置"
        exit 1
    fi
    log_info "目标服务器连接正常"

    # 检查目标服务器依赖
    log_step "[3/6] 检查目标服务器环境..."
    for cmd in rsync python3 pip3 nginx systemctl; do
        if check_remote_command "$REMOTE" "$cmd"; then
            log_info "  ✓ $cmd 已安装"
        else
            log_warn "  ✗ $cmd 未安装（后续可能需要手动安装）"
        fi
    done

    # 在目标创建安装目录
    log_step "[4/6] 准备目标目录..."
    remote_exec "$REMOTE" "sudo mkdir -p $INSTALL_DIR/backend $INSTALL_DIR/frontend-dist"

    # 同步数据文件
    log_step "[5/6] 同步数据文件..."
    for item in "${DATA_ITEMS[@]}"; do
        src="$INSTALL_DIR/$item"
        if [[ -e "$src" ]]; then
            log_info "同步: $item"
            # 确保目标目录存在
            remote_exec "$REMOTE" "sudo mkdir -p $(dirname $INSTALL_DIR/$item)"
            rsync_transfer "$src" "$REMOTE:$(dirname $INSTALL_DIR/$item)/"
        else
            log_warn "跳过（不存在）: $item"
        fi
    done

    # 同步代码（如果目标目录为空或 --force）
    log_info "同步项目代码..."
    rsync_transfer "$INSTALL_DIR/backend/" "$REMOTE:$INSTALL_DIR/backend/" \
        "--exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='db.sqlite3' --exclude='uploads' --exclude='logs' --exclude='.env'"

    rsync_transfer "$INSTALL_DIR/frontend-dist/" "$REMOTE:$INSTALL_DIR/frontend-dist/"

    rsync_transfer "$INSTALL_DIR/deploy/" "$REMOTE:$INSTALL_DIR/deploy/"

    # 修复权限
    log_info "修复文件权限..."
    remote_exec "$REMOTE" "
        sudo chown -R gipfel:gipfel $INSTALL_DIR/backend 2>/dev/null || true
        sudo chmod 600 $INSTALL_DIR/backend/.env 2>/dev/null || true
        sudo chmod 755 $INSTALL_DIR/backend/uploads 2>/dev/null || true
    "

    # 服务配置
    if [[ "$SKIP_SERVICES" == false ]]; then
        log_step "[6/6] 配置目标服务器服务..."
        remote_exec "$REMOTE" "
            # 创建系统用户（如不存在）
            if ! id gipfel >/dev/null 2>&1; then
                sudo useradd -r -s /usr/sbin/nologin gipfel || true
            fi

            # 安装 systemd 服务
            sudo cp $INSTALL_DIR/deploy/gipfel.service /etc/systemd/system/
            sudo cp $INSTALL_DIR/deploy/logviewer.service /etc/systemd/system/
            sudo systemctl daemon-reload

            # 提示用户手动完成剩余配置
            echo ''
            echo '=========================================='
            echo '数据同步完成！请在目标服务器上完成以下步骤：'
            echo '=========================================='
            echo ''
            echo '1. 安装 Python 依赖：'
            echo '   cd $INSTALL_DIR/backend'
            echo '   python3 -m venv .venv'
            echo '   source .venv/bin/activate'
            echo '   pip install -r requirements.txt'
            echo ''
            echo '2. 运行数据库迁移：'
            echo '   python manage.py migrate'
            echo '   python manage.py collectstatic --noinput'
            echo ''
            echo '3. 配置 nginx：'
            echo '   sudo cp $INSTALL_DIR/deploy/nginx-gipfel.conf /etc/nginx/sites-available/gipfel.conf'
            echo '   sudo sed -i \"s|__INSTALL_DIR__|$INSTALL_DIR|g\" /etc/nginx/sites-available/gipfel.conf'
            echo '   sudo sed -i \"s|__DOMAIN__|YOUR_DOMAIN|g\" /etc/nginx/sites-available/gipfel.conf'
            echo '   sudo ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/'
            echo '   sudo nginx -t && sudo systemctl reload nginx'
            echo ''
            echo '4. 启动服务：'
            echo '   sudo systemctl enable gipfel gipfel-logviewer'
            echo '   sudo systemctl start gipfel gipfel-logviewer'
            echo ''
            echo '5. 验证：'
            echo '   curl http://127.0.0.1:8000/api/health'
            echo ''
        "
    else
        log_info "跳过服务配置（--skip-services）"
    fi

    log_info "=========================================="
    log_info "推送完成！"
    log_info "=========================================="

# ---------- 拉取模式 ----------
elif [[ "$MODE" == "pull" ]]; then
    REMOTE="$SOURCE"

    log_step "[1/6] 检查源服务器连接..."
    if ! ssh $SSH_OPTS "$REMOTE" "echo ok" >/dev/null 2>&1; then
        log_error "无法连接到源服务器: $REMOTE"
        exit 1
    fi
    log_info "源服务器连接正常"

    # 检查源目录
    log_step "[2/6] 检查源服务器安装目录..."
    if ! remote_exec "$REMOTE" "test -d $INSTALL_DIR"; then
        log_error "源服务器安装目录不存在: $INSTALL_DIR"
        exit 1
    fi
    log_info "源目录检查通过"

    # 创建本地备份目录
    log_step "[3/6] 创建本地备份目录..."
    mkdir -p "$BACKUP_DIR"
    log_info "备份目录: $BACKUP_DIR"

    # 拉取数据文件
    log_step "[4/6] 从源服务器拉取数据..."
    for item in "${DATA_ITEMS[@]}"; do
        remote_path="$REMOTE:$INSTALL_DIR/$item"
        local_path="$BACKUP_DIR/$item"

        # 检查远程文件是否存在
        if ssh $SSH_OPTS "$REMOTE" "test -e $INSTALL_DIR/$item" 2>/dev/null; then
            log_info "拉取: $item"
            mkdir -p "$(dirname "$local_path")"
            rsync_transfer "$remote_path" "$(dirname "$local_path")/"
        else
            log_warn "跳过（不存在）: $item"
        fi
    done

    # 拉取代码
    log_info "拉取项目代码..."
    mkdir -p "$BACKUP_DIR/backend" "$BACKUP_DIR/frontend-dist" "$BACKUP_DIR/deploy"
    rsync_transfer "$REMOTE:$INSTALL_DIR/backend/" "$BACKUP_DIR/backend/" \
        "--exclude='.venv' --exclude='__pycache__' --exclude='*.pyc'"
    rsync_transfer "$REMOTE:$INSTALL_DIR/frontend-dist/" "$BACKUP_DIR/frontend-dist/"
    rsync_transfer "$REMOTE:$INSTALL_DIR/deploy/" "$BACKUP_DIR/deploy/"

    # 恢复到本地安装目录
    log_step "[5/6] 恢复到本地安装目录..."
    if [[ "$DRY_RUN" == false ]]; then
        mkdir -p "$INSTALL_DIR"
        # 备份现有数据（如有）
        if [[ -d "$INSTALL_DIR/backend" ]]; then
            local existing_backup="$INSTALL_DIR/_backup/$(date +%Y%m%d_%H%M%S)"
            log_info "备份现有数据到: $existing_backup"
            mkdir -p "$existing_backup"
            cp -a "$INSTALL_DIR/backend/db.sqlite3" "$existing_backup/" 2>/dev/null || true
            cp -a "$INSTALL_DIR/backend/.env" "$existing_backup/" 2>/dev/null || true
            cp -a "$INSTALL_DIR/backend/uploads" "$existing_backup/" 2>/dev/null || true
        fi

        # 恢复数据
        cp -a "$BACKUP_DIR/backend/db.sqlite3" "$INSTALL_DIR/backend/" 2>/dev/null || true
        cp -a "$BACKUP_DIR/backend/.env" "$INSTALL_DIR/backend/" 2>/dev/null || true
        cp -a "$BACKUP_DIR/backend/uploads" "$INSTALL_DIR/backend/" 2>/dev/null || true
        cp -a "$BACKUP_DIR/backend/logs" "$INSTALL_DIR/backend/" 2>/dev/null || true
        cp -a "$BACKUP_DIR/backend/staticfiles" "$INSTALL_DIR/backend/" 2>/dev/null || true
        cp -a "$BACKUP_DIR/frontend-dist" "$INSTALL_DIR/" 2>/dev/null || true
        cp -a "$BACKUP_DIR/deploy" "$INSTALL_DIR/" 2>/dev/null || true
    fi

    # 服务配置
    if [[ "$SKIP_SERVICES" == false ]]; then
        log_step "[6/6] 配置本地服务..."
        if [[ "$DRY_RUN" == false ]]; then
            # 创建系统用户
            if ! id gipfel >/dev/null 2>&1; then
                sudo useradd -r -s /usr/sbin/nologin gipfel || true
            fi

            # 设置权限
            sudo chown -R gipfel:gipfel "$INSTALL_DIR/backend"
            sudo chmod 600 "$INSTALL_DIR/backend/.env" 2>/dev/null || true

            # 安装 systemd 服务
            sudo cp "$INSTALL_DIR/deploy/gipfel.service" /etc/systemd/system/
            sudo cp "$INSTALL_DIR/deploy/logviewer.service" /etc/systemd/system/
            sudo systemctl daemon-reload
        fi
    fi

    log_info "=========================================="
    log_info "拉取完成！数据已恢复到: $INSTALL_DIR"
    log_info "备份保存在: $BACKUP_DIR"
    log_info "=========================================="
    log_info ""
    log_info "请完成以下步骤："
    log_info "1. 安装 Python 依赖: cd $INSTALL_DIR/backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    log_info "2. 运行迁移: python manage.py migrate && python manage.py collectstatic --noinput"
    log_info "3. 配置 nginx: 参考 deploy/README.md"
    log_info "4. 启动服务: sudo systemctl enable gipfel gipfel-logviewer && sudo systemctl start gipfel gipfel-logviewer"
fi

log_info ""
log_info "迁移脚本执行完毕！"
