#!/usr/bin/env bash
# ============================================================
# 修改 PostgreSQL 应用账号密码，并原子地同步 .env + 重启服务
#
# 用法：
#   sudo bash scripts/change-db-password.sh            # 交互输入（推荐，明文不落任何地方）
#   sudo bash scripts/change-db-password.sh '新密码'    # 命令行传入（会进 shell history，不推荐）
#
# 为什么需要它：单独执行 ALTER USER 改了库密码却不改 .env，应用会立刻连不上。
# 本脚本把「改库 → 同步 .env → 验证 → 重启 → 健康检查」做成原子步骤，
# 任一步失败都给出明确原因与回滚命令。
# ============================================================
set -euo pipefail

DB_USER="${DB_USER:-gipfel}"
DB_NAME="${DB_NAME:-gipfel}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
INSTALL_DIR="${INSTALL_DIR:-/opt/gipfel}"
ENV_FILE="$INSTALL_DIR/backend/.env"

log()  { printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[OK]\033[0m   %s\n' "$*"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || err '请用 sudo / root 运行'
[[ -f "$ENV_FILE" ]] || err "找不到 $ENV_FILE"

# ---------------- 1. 取新密码 ----------------
NEWPW="${1:-}"
if [[ -z "$NEWPW" ]]; then
    read -rsp '请输入新的数据库密码: ' NEWPW; echo
    read -rsp '请再次输入确认:       ' NEWPW2; echo
    [[ "$NEWPW" == "$NEWPW2" ]] || err '两次输入不一致'
fi
[[ -n "$NEWPW" ]] || err '密码不能为空'

# ---------------- 2. 备份 .env ----------------
BAK="$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"
cp -a "$ENV_FILE" "$BAK"
log "已备份 .env → $BAK"

# ---------------- 3. 改数据库密码 ----------------
# 走 stdin 而不是 -f/-c：
#   · 用 -c "ALTER USER ... '明文'" 会把明文暴露在 ps 的进程参数里
#   · 用 -f 临时文件时 psql 以 postgres 身份运行，读不到 root 建的 600 文件
python3 - "$DB_USER" "$NEWPW" <<'PY' | sudo -u postgres psql -q >/dev/null
import sys
user, pw = sys.argv[1], sys.argv[2]
sys.stdout.write("ALTER USER %s WITH PASSWORD '%s';\n" % (user, pw.replace("'", "''")))
PY
ok "已更新数据库密码（角色 $DB_USER）"

# ---------------- 4. 同步 .env ----------------
python3 - "$ENV_FILE" "$NEWPW" <<'PY'
import sys, pathlib, re
env, pw = sys.argv[1], sys.argv[2]
p = pathlib.Path(env); s = p.read_text()
if re.search(r'^DB_PASSWORD=', s, re.M):
    s = re.sub(r'^DB_PASSWORD=.*$', 'DB_PASSWORD=' + pw, s, flags=re.M)
else:
    s = s.rstrip('\n') + '\nDB_PASSWORD=' + pw + '\n'
p.write_text(s)
PY
chmod 600 "$ENV_FILE"
ok '已同步 .env 的 DB_PASSWORD'

# ---------------- 5. 用与 Django 相同的方式验证 ----------------
if PGPASSWORD="$NEWPW" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc 'SELECT 1' >/dev/null 2>&1; then
    ok "凭据验证通过（$DB_USER@$DB_HOST:$DB_PORT/$DB_NAME）"
else
    warn '新密码无法通过 TCP 认证：.env 已改但连接不通'
    warn "回滚 .env：sudo cp -a $BAK $ENV_FILE"
    err '请检查 pg_hba.conf 的 host 规则是否为 scram-sha-256 / md5'
fi

# ---------------- 6. 重启服务 ----------------
# 必须重启：PostgreSQL 不会因改密踢掉已建立的连接，
# 应用连接池（CONN_MAX_AGE=600）里的旧连接仍会继续工作，不重启就看不出一致性问题。
for svc in gipfel gipfel-logviewer; do
    if systemctl cat "$svc.service" >/dev/null 2>&1; then
        systemctl restart "$svc"
    fi
done
sleep 3

if systemctl is-active --quiet gipfel; then
    ok 'gipfel 已重启并运行中'
else
    warn 'gipfel 启动失败，最近日志：'
    journalctl -u gipfel -n 20 --no-pager || true
    err "回滚：sudo cp -a $BAK $ENV_FILE && sudo systemctl restart gipfel"
fi

if systemctl cat gipfel-logviewer.service >/dev/null 2>&1; then
    if systemctl is-active --quiet gipfel-logviewer; then
        ok 'gipfel-logviewer 已重启并运行中'
    else
        warn 'gipfel-logviewer 未运行（它复用同一个 .env，通常也会受影响）'
    fi
fi

# ---------------- 7. 端到端健康检查 ----------------
if curl -s --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null | grep -q 'ok'; then
    ok 'API 健康检查通过'
else
    warn 'API 健康检查未通过（可能仍在启动，稍后再试）'
fi

echo
ok "数据库密码修改完成（备份：$BAK）"
