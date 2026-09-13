#!/usr/bin/env bash
# 一键诊断：日志查看器 400 / 连不上 的排查脚本
#
# 用法（服务器上执行）：
#   bash gipfel-logviewer-diag.sh [INSTALL_DIR]      # 默认 /opt/gipfel
#
# 审计 X-14 修复点：
#   ① 改前第 6 行 `grep -E "^(…|LOGVIEWER_SECRET_KEY|…)= "` 把 **LOGVIEWER_SECRET_KEY 原文**
#      打到 stdout —— 该密钥可自签日志查看器/`/admin` 防直连令牌，任何能读到终端输出、
#      CI 日志、会话记录的人都能据此绕过 nginx 直连。现在一律掩码显示。
#   ② 所有 curl 补 `--connect-timeout` / `--max-time`（改前无超时，网络异常时会永久挂住）。
#   ③ 端口不再硬编码 8120：从 .env 的 `LOG_VIEWER_PORT` 读取（与 nginx/ufw 同源）。
#   ④ `sudo -n` 失败时明确提示"需要 NOPASSWD 或手动查看"，不再静默无输出。
#   ⑤ 安装目录可传入，不再写死 /opt/gipfel。
set +e

INSTALL_DIR="${1:-/opt/gipfel}"
ENV_FILE="$INSTALL_DIR/backend/.env"
CURL_OPTS=(--connect-timeout 3 --max-time 6 -s -o /dev/null)

have_sudo_n() { sudo -n true 2>/dev/null; }

# 掩码：只显示前 4 位与长度，绝不输出密钥原文
mask() {
    local v="$1"
    local n=${#v}
    if [[ -z "$v" ]]; then printf '<空>'; return; fi
    if (( n <= 8 )); then printf '****(len=%d)' "$n"; else printf '%s****(len=%d)' "${v:0:4}" "$n"; fi
}

echo "======================================================"
echo " 安装目录: $INSTALL_DIR"
echo "======================================================"
echo "================ 1. .env 当前关键变量（密钥已掩码）================"
if [[ -f "$ENV_FILE" ]]; then
    while IFS= read -r line; do
        key="${line%%=*}"
        val="${line#*=}"
        case "$key" in
            LOGVIEWER_SECRET_KEY) echo "  ${key}=$(mask "$val")  # 已掩码（改前会打印原文）" ;;
            *) echo "  $line" ;;
        esac
    done < <(grep -E "^(LOG_VIEWER_PUBLIC_URL|DJANGO_ALLOWED_HOSTS|LOGVIEWER_ALLOWED_HOSTS|LOGVIEWER_SECRET_KEY|LOG_VIEWER_PORT)=" "$ENV_FILE" 2>/dev/null)
else
    echo "  [warn] $ENV_FILE 缺失"
fi
echo ""
echo "================ 2. 服务单元版本（确认拉到最新）================"
if have_sudo_n; then
    sudo -n cat "$INSTALL_DIR/deploy/logviewer.service" 2>/dev/null | grep -E "(ExecStart|WorkingDirectory|RuntimeDirectory|ReadWritePaths)" | head -6
else
    echo "  [warn] 无 NOPASSWD sudo（sudo -n 不可用）：请手动执行 cat $INSTALL_DIR/deploy/logviewer.service"
    grep -E "(ExecStart|WorkingDirectory|RuntimeDirectory|ReadWritePaths)" \
        "$INSTALL_DIR/deploy/logviewer.service" 2>/dev/null | head -6 \
        || echo "  [warn] 该文件不可读"
fi
echo ""
echo "================ 3. 服务运行状态 ================"
systemctl is-active gipfel-logviewer && echo "  [ok] gipfel-logviewer 运行中" || echo "  [FAIL] gipfel-logviewer 未运行"
PID=$(systemctl show -p MainPID gipfel-logviewer 2>/dev/null | cut -d= -f2)
if [[ -n "$PID" && "$PID" != "0" ]]; then
    echo "  PID=$PID，启动时间：$(ps -o lstart= -p "$PID" 2>/dev/null)"
fi
echo ""
echo "================ 4. 进程实际读到的 ALLOWED_HOSTS（向进程探测）================"
PUB_IP=$(grep -E "^DJANGO_ALLOWED_HOSTS=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2 | cut -d, -f1)
LV_PORT=$(grep -E "^[[:space:]]*LOG_VIEWER_PORT=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- \
    | tr -d '[:space:]' | sed -E "s/^['\"]//; s/['\"]$//")
LV_PORT="${LV_PORT:-8120}"
echo "  从 .env 读到的公网 IP/域名: ${PUB_IP:-<空>}"
echo "  日志查看器公网端口: ${LV_PORT}（来自 $ENV_FILE 的 LOG_VIEWER_PORT）"
echo "  [a] 模拟公网 IP 裸访问（应 302/200 而非 400）："
curl "${CURL_OPTS[@]}" -w "    Host: ${PUB_IP} -> HTTP %{http_code}\n" -H "Host: ${PUB_IP}" http://127.0.0.1:8121/
echo "  [b] 模拟公网 IP + 端口 ${LV_PORT}（应 302/200 而非 400）："
curl "${CURL_OPTS[@]}" -w "    Host: ${PUB_IP}:${LV_PORT} -> HTTP %{http_code}\n" -H "Host: ${PUB_IP}:${LV_PORT}" http://127.0.0.1:8121/
echo "  [c] 恶意 Host（应 400，证明白名单仍生效）："
curl "${CURL_OPTS[@]}" -w "    Host: evil.com -> HTTP %{http_code}\n" -H "Host: evil.com" http://127.0.0.1:8121/
echo "  [d] 经 nginx 公网口访问（应 200/302）："
curl "${CURL_OPTS[@]}" -w "    127.0.0.1:${LV_PORT} -> HTTP %{http_code}\n" "http://127.0.0.1:${LV_PORT}/"
echo ""
echo "================ 5. 失败时的日志线索 ================"
echo "  [tip] 若 [a]/[b] 仍 400，看这里（最近 30 行）："
if have_sudo_n; then
    sudo -n journalctl -u gipfel-logviewer -n 30 --no-pager 2>/dev/null \
        | grep -E "(DisallowedHost|ALLOWED_HOSTS|Invalid HTTP_HOST|Error)" | tail -10
else
    journalctl -u gipfel-logviewer -n 30 --no-pager 2>/dev/null \
        | grep -E "(DisallowedHost|ALLOWED_HOSTS|Invalid HTTP_HOST|Error)" | tail -10 \
        || echo "  [warn] 无权限读取 journal：请手动执行 sudo journalctl -u gipfel-logviewer -n 30"
fi
exit 0
