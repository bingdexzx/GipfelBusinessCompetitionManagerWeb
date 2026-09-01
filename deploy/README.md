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
| systemd 服务 | `/etc/systemd/system/gipfel.service`、`/etc/systemd/system/gipfel-logviewer.service` |
| nginx vhost | `/etc/nginx/sites-available/gipfel.conf`（sites-enabled 软链，含 `log.<DOMAIN>` 日志查看器子域块） |
| 前端静态 | `/opt/gipfel/frontend-dist/`（由 nginx root 直接托管） |
| 日志查看器静态 | `/opt/gipfel/backend/logviewer/staticfiles/`（由 nginx `log.<DOMAIN>` 块 alias 托管） |

### 验证

```bash
systemctl status gipfel               # active (running)
systemctl status nginx                # active (running)
systemctl status gipfel-logviewer     # active (running)  ← 日志查看器
curl -sS http://127.0.0.1:8000/api/health  # ok:true
curl -sS -I http://127.0.0.1/         # 200（nginx 托管 index.html）
# 浏览器打开 https://comp.example.com
```

### 日志查看器公网访问（防直连）

日志查看器作为独立 Django 站点，经 nginx 子域 `log.<DOMAIN>` **整站代理**到 `127.0.0.1:8120`（不直连公网）。

- **仅按钮跳转**：前端「系统设置 → 日志查看器」按钮在点击时向后端 `POST /api/auth/logviewer-token` 获取一次性（默认 120s）签名令牌（仅 `SUPER_ADMIN` 可获取），拼入 `https://log.<DOMAIN>/?token=...` 打开。日志查看器 `index` 视图校验令牌，缺失/无效/过期均 **403 拒绝**——因此直接输入网址、书签、复制链接都无法进入。
- **前置条件（运维侧）**：
  1. DNS：`log.<DOMAIN>` 的 A 记录指向本服务器；
  2. 证书：`certbot --nginx -d <DOMAIN> -d log.<DOMAIN>`（deploy 脚本的 certbot 提示已纳入该子域）。未启用 HTTPS 时以 HTTP(80) 提供，功能正常（cookie 非 Secure）。
  3. 启用 HTTPS 后，建议在 `.env` 设 `LOGVIEWER_SECURE_COOKIES=true`，使网关会话/ CSRF cookie 标记 Secure。
- **共享密钥**：主后端与日志查看器共用 `.env` 的 `LOGVIEWER_SECRET_KEY` 签发/校验令牌。deploy 脚本首次部署自动生成随机值；已部署实例升级时 `.env` 保留不变，两端始终一致。
- **双重认证**：令牌只放行「进入日志查看器站点的网关」，进入后仍需用 Django 后台超级管理员凭据登录才能真正读取日志。

### 更新部署（升级版本，保留数据）

```bash
cd GipfelBusinessCompetitionManagerWeb
sudo scripts/deploy-linux.sh --domain comp.example.com --install-dir /opt/gipfel --with-nginx --skip-install-deps
# 脚本自动：
#   1) 备份 db.sqlite3 + uploads + .env 到 /opt/gipfel/_backup/$(date +%F_%H%M%S)
#   2) 更新代码（排除 db.sqlite3/uploads/.env，避免覆盖线上数据）
#   3) 从备份恢复 db.sqlite3 + uploads + .env（保留业务数据）
#   4) pip install -r requirements.txt（如有新依赖）
#   5) migrate（种子幂等）+ collectstatic（主后端 + 日志查看器静态资源）
#   6) npm ci && npm run build → frontend-dist/
#   7) systemctl restart gipfel（+ gipfel-logviewer 日志查看器）
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
