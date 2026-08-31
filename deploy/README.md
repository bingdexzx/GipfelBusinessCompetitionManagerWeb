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

## 方案二：Windows（仅开发，无生产部署脚本）

Windows 不提供独立生产部署脚本；生产部署请使用方案一的 Linux 脚本 [deploy-linux.sh](../scripts/deploy-linux.sh)。

开发启动器 [scripts/start-dev.bat](../scripts/start-dev.bat) 会并行拉起：

- Django `:8000`（runserver）
- Vite `:5173`（前端开发服务器）
- 日志查看器 `:8120`（独立服务，端口取 `backend/.env` 的 `LOG_VIEWER_PORT`，登录账号使用 Django 后台超级管理员凭据）

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
