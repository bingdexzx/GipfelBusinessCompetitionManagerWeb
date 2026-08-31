# 部署手册

## 方案一：Linux 一键部署（推荐 · Ubuntu 22.04 / Debian 12）

```bash
cd GipfelBusinessCompetitionManagerWeb
sudo bash scripts/deploy-linux.sh \
  --domain comp.example.com \
  --install-dir /opt/gipfel \
  --with-nginx
```

### 脚本执行完之后

| 产物 | 位置 |
| --- | --- |
| 代码 | `/opt/gipfel/`（整个项目复制过去） |
| 虚拟环境 | `/opt/gipfel/backend/.venv/` |
| 数据库 | `/opt/gipfel/backend/db.sqlite3` |
| 上传 | `/opt/gipfel/backend/uploads/` |
| 日志-Django | `/opt/gipfel/backend/logs/` + `/var/log/gipfel/` |
| 日志-nginx | `/var/log/nginx/gipfel.{access,error}.log` |
| systemd 服务 | `/etc/systemd/system/gipfel.service` |
| nginx vhost | `/etc/nginx/sites-available/gipfel.conf`（sites-enabled 软链） |
| 前端静态 | `/opt/gipfel/frontend-dist/`（由 nginx root 直接托管） |

### 验证

```bash
systemctl status gipfel               # active (running)
systemctl status nginx                # active (running)
curl -sS http://127.0.0.1:8000/api/health  # ok:true
curl -sS -I http://127.0.0.1/         # 200（nginx 托管 index.html）
# 浏览器打开 https://comp.example.com
```

### 更新部署（升级版本，保留数据）

```bash
cd GipfelBusinessCompetitionManagerWeb
sudo scripts/deploy-linux.sh --domain comp.example.com --install-dir /opt/gipfel --with-nginx --skip-install-deps
# 脚本自动：
#   1) 备份 db.sqlite3 + uploads 到 /opt/gipfel/_backup/$(date +%F_%H%M)
#   2) 更新代码
#   3) pip install -r requirements.txt（如有新依赖）
#   4) migrate（种子幂等）
#   5) npm ci && npm run build → frontend-dist/
#   6) systemctl restart gipfel
```

### 回滚

```bash
# 当前代码目录改名，把 _backup 里最近的完整复制回来，再 restart 即可
sudo -u gipfel cp /opt/gipfel/_backup/2025-08-31_1200/db.sqlite3 /opt/gipfel/backend/
sudo systemctl restart gipfel
```

---

## 方案二：Windows Server 生产部署

### 方式 A：脚本（最简单）

```powershell
cd GipfelBusinessCompetitionManagerWeb
powershell -ExecutionPolicy Bypass -File scripts\deploy-windows.ps1 `
  -InstallDir "C:\gipfel" -Port 8000 -FrontendPort 80 -WithService
```

完成后：
- 服务「GipfelBackend」启动类型 Automatic，运行 daphne 监听 `127.0.0.1:8000`
- 前端产物 `C:\gipfel\frontend-dist\` 交给 IIS（脚本若找到 IIS 会自动建站点 `Gipfel`；否则你可手动拷到任意静态目录）
- 默认后台管理员：`admin / Admin@2026`（脚本首次运行自动把 admin123 → Admin@2026，避免泄露默认口令）

### 方式 B：IIS + wfastcgi / httpplatformhandler（不推荐维护成本高）

直接用脚本方案 A + IIS「URL Rewrite + ARR 反向代理到 127.0.0.1:8000」即可，
等同 Linux nginx 的逻辑：`/api/*`、`/socket.io/*` → 8000；其余静态。

---

## 方案三：Docker（快速上手）

```dockerfile
# 示例 Dockerfile 片段：多阶段 build 前端 + 单镜像跑 daphne
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./
RUN python manage.py collectstatic --noinput 2>/dev/null || true
COPY --from=frontend /app/frontend/dist /app/frontend-dist
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "--proxy-headers", "backend.asgi:application"]
```

挂载：
```
-v ./data/db.sqlite3:/app/backend/db.sqlite3
-v ./data/uploads:/app/backend/uploads
-v ./data/logs:/app/backend/logs
-e JWT_SECRET=CHANGE-ME
```
