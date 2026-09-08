#!/usr/bin/env bash
# 一键诊断：日志查看器 400 修复是否生效
# 在服务器上执行：bash gipfel-logviewer-diag.sh
set +e
echo "================ 1. .env 当前关键变量 ================"
grep -E "^(LOG_VIEWER_PUBLIC_URL|DJANGO_ALLOWED_HOSTS|LOGVIEWER_ALLOWED_HOSTS|LOGVIEWER_SECRET_KEY|LOG_VIEWER_PORT)=" /opt/gipfel/backend/.env 2>/dev/null || echo "  [warn] /opt/gipfel/backend/.env 缺失"
echo ""
echo "================ 2. 服务单元版本（确认拉到最新）================"
sudo -n cat /opt/gipfel/deploy/logviewer.service 2>/dev/null | grep -E "(ExecStart|WorkingDirectory)" | head -2
echo ""
echo "================ 3. 服务运行状态 ================"
systemctl is-active gipfel-logviewer && echo "  [ok] gipfel-logviewer 运行中" || echo "  [FAIL] gipfel-logviewer 未运行"
PID=$(systemctl show -p MainPID gipfel-logviewer | cut -d= -f2)
if [[ "$PID" != "0" && -n "$PID" ]]; then
  echo "  PID=$PID，启动时间：$(ps -o lstart= -p $PID 2>/dev/null)"
fi
echo ""
echo "================ 4. 进程实际读到的 ALLOWED_HOSTS（向进程探测）================"
PUB_IP=$(grep -E "^DJANGO_ALLOWED_HOSTS=" /opt/gipfel/backend/.env | head -1 | cut -d= -f2 | cut -d, -f1)
echo "  从 .env 读到的公网 IP/域名: ${PUB_IP:-<空>}"
echo "  [a] 模拟公网 IP 裸访问（应 302/200 而非 400）："
curl -s -o /dev/null -w "    Host: ${PUB_IP} -> HTTP %{http_code}\n" -H "Host: ${PUB_IP}" http://127.0.0.1:8121/
echo "  [b] 模拟公网 IP + 端口 8120（应 302/200 而非 400）："
curl -s -o /dev/null -w "    Host: ${PUB_IP}:8120 -> HTTP %{http_code}\n" -H "Host: ${PUB_IP}:8120" http://127.0.0.1:8121/
echo "  [c] 恶意 Host（应 400，证明白名单仍生效）："
curl -s -o /dev/null -w "    Host: evil.com -> HTTP %{http_code}\n" -H "Host: evil.com" http://127.0.0.1:8121/
echo ""
echo "================ 5. 失败时的日志线索 ================"
echo "  [tip] 若 [a]/[b] 仍 400，看这里（最近 30 行）："
sudo -n journalctl -u gipfel-logviewer -n 30 --no-pager 2>/dev/null | grep -E "(DisallowedHost|ALLOWED_HOSTS|Invalid HTTP_HOST|Error)" | tail -10
