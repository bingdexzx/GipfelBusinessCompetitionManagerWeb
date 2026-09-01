# 部署手册

## 方案一：Linux 一键部署（推荐 · Ubuntu 22.04 / Debian 12）

```bash
cd GipfelBusinessCompetitionManagerWeb
sudo bash scripts/deploy-linux.sh \
  --domain comp.example.com \
  --install-dir /opt/gipfel \
  --with-nginx
```

> **依赖说明**：脚本默认会自动 `apt-get install` 所需系统包（`python3` / `nginx` / `nodejs` / **`rsync`** 等）。若使用 `--skip-install-deps` 跳过安装，需确保目标机**已装好 `rsync`**——代码同步阶段强依赖它，缺失会报 `rsync: command not found`。

### 获取源码（clone 到服务器）

部署脚本必须在源码树内执行（`scripts/deploy-linux.sh` 的相对路径依赖它所在目录），所以**先 clone 到服务器，再进去跑脚本**。

```bash
# 1) 克隆仓库（默认分支 master）
git clone https://github.com/bingdexzx/GipfelBusinessCompetitionManagerWeb.git
cd GipfelBusinessCompetitionManagerWeb

# 2) 一键部署：纯 IP 先用「无 --domain」，有域名加 --domain
sudo bash scripts/deploy-linux.sh --install-dir /opt/gipfel --with-nginx
#   有域名时：
#   sudo bash scripts/deploy-linux.sh --domain comp.example.com --install-dir /opt/gipfel --with-nginx
```

> **网络前提**：部署过程中服务器需能出网到 **apt 源 / PyPI（`pip install`）/ npm 源（`npm ci`）**。仅 GitHub 不通、但 apt/npm/PyPI 可达时，可用下方镜像绕过；若全部都不通，走「服务器完全连不上 GitHub」的 tar 包方案（前端 dist 也可在能联网的机器预构建后整体传入）。

> **GitHub 直连超时（`curl 28` / 443 连不上）？** 国内或受限网络常见，两种绕过方式：
> - 用镜像前缀直接 clone：
>   `git clone https://ghproxy.com/https://github.com/bingdexzx/GipfelBusinessCompetitionManagerWeb.git`
> - 或让本机后续所有 git 操作自动走代理（之后普通 `git clone` / `git pull` 即可）：
>   `git config --global url."https://ghproxy.com/https://github.com/".insteadOf "https://github.com/"`
> - 其他可用镜像：`https://mirror.ghproxy.com/`、`https://kgithub.com/`、`https://gitclone.com/github.com/`（可用性各异，挑能连的）。

> **镜像也不稳、想直接用 GitHub 地址拉取？** 可在服务器上安装 FastGitHub（本地代理加速/恢复 GitHub 连接），之后所有 git/curl 命令自动走 `127.0.0.1:38457` 即可正常访问 GitHub：
> ```bash
> # 1) 下载 FastGitHub（从 Gitee Release，适合 GitHub 连不上的环境）
> wget -c -O /opt/fastgithub_linux-x64.zip \
>   https://gitee.com/chcrazy/FastGitHub/releases/download/latest/fastgithub_linux-x64.zip
> 
> # 2) 解压
> unzip -d /opt /opt/fastgithub_linux-x64.zip
> rm /opt/fastgithub_linux-x64.zip
> 
> # 3) 启动 FastGitHub（后台代理，占用 38457 端口）
> sudo /opt/fastgithub_linux-x64/fastgithub start
> 
> # 4) 设置代理（当前 shell；如需永久生效，写入 /etc/profile 后重新登录）
> export http_proxy=http://127.0.0.1:38457
> export https_proxy=http://127.0.0.1:38457
> 
> # 5) 之后即可正常 clone GitHub 仓库
> git clone https://github.com/bingdexzx/GipfelBusinessCompetitionManagerWeb.git
> ```
> 注意：FastGitHub 进程需保持运行；生产服务器建议用 `systemd` 或 `nohup/screen` 常驻。apt/pip/npm 等流量也会走该代理，通常无碍；若只想让 git 走代理，可用上方 `git config --global url...insteadOf` 方案。

> **服务器完全连不上 GitHub（连镜像也不行）？** 在能访问 GitHub / 已含代码的机器上打包源码传上去，再在服务器本地跑脚本（不需要服务器联网到 GitHub）：
> ```bash
> # 在「源机器」打包（排除重型/生成目录）
> tar czf gipfel-deploy-src.tgz --exclude='.git' \
>   --exclude='backend/.venv' --exclude='backend/db.sqlite3' --exclude='backend/uploads' \
>   --exclude='backend/logs' --exclude='backend/staticfiles' --exclude='backend/logviewer/staticfiles' \
>   --exclude='frontend/node_modules' --exclude='frontend/dist' \
>   backend frontend deploy scripts OPS.md README.md Vue-Django迁移设计.md
> # 传到服务器
> scp gipfel-deploy-src.tgz root@<服务器IP>:/tmp/
> # 服务器上解包并部署（脚本从解包后的源码树内运行，无需 --source-dir）
> mkdir -p /opt/gipfel-src && tar xzf /tmp/gipfel-deploy-src.tgz -C /opt/gipfel-src
> cd /opt/gipfel-src && sudo bash scripts/deploy-linux.sh --install-dir /opt/gipfel --with-nginx
> ```

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
| nginx vhost | `/etc/nginx/sites-available/gipfel.conf`（sites-enabled 软链）。**有域名**时含 `log.<DOMAIN>` 日志查看器子域块；**无域名（纯 IP）**时自动换成 `:8120` 端口块（`server_name _`）——deploy 脚本按是否传 `--domain` 保留对应一块、删除另一块 |
| 前端静态 | `/opt/gipfel/frontend-dist/`（由 nginx root 直接托管） |
| 日志查看器静态 | `/opt/gipfel/backend/logviewer/staticfiles/`（由 nginx 日志查看器块 alias 托管：有域名是 `log.<DOMAIN>` 块，无域名是 `:8120` 块） |

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

日志查看器作为独立 Django 站点，经 nginx **整站代理**到 `127.0.0.1:8120`（不直连公网）。代理形态分两种：

- **有域名**：nginx 子域 `log.<DOMAIN>`（端口 80，建议 certbot 覆盖）→ `127.0.0.1:8120`。
- **无域名（纯 IP）**：nginx `:8120` 端口（`server_name _`）→ `127.0.0.1:8120`，访问 `http://<IP>:8120/`。无需 DNS 子域，适合还没买域名的阶段。deploy 脚本**未传 `--domain` 时**会自动：① 把 vhost 里的日志查看器块改为 8120 端口版、② 在 `.env` 写入 `LOG_VIEWER_PUBLIC_URL=http://<本机IP>:8120/`、③ `ufw allow 8120/tcp` 放行防火墙（无 ufw 则提示手动放行）。

不论哪种形态，均为**仅按钮跳转**：前端「系统设置 → 日志查看器」按钮在点击时向后端 `POST /api/auth/logviewer-token` 获取一次性（默认 120s）签名令牌（仅 `SUPER_ADMIN` 可获取），拼入跳转地址打开（有域名 `https://log.<DOMAIN>/?token=...`，无域名 `http://<IP>:8120/?token=...`，地址由 `/api/version` 下发的 `log_viewer_url` 决定，可用 `.env` 的 `LOG_VIEWER_PUBLIC_URL` 显式覆盖）。日志查看器 `index` 视图校验令牌，缺失/无效/过期均 **403 拒绝**——因此直接输入网址、书签、复制链接都无法进入。

- **前置条件（仅「有域名」形态需要，运维侧）**：
  1. DNS：`log.<DOMAIN>` 的 A 记录指向本服务器；
  2. 证书：`certbot --nginx -d <DOMAIN> -d log.<DOMAIN>`（deploy 脚本的 certbot 提示已纳入该子域）。未启用 HTTPS 时以 HTTP(80) 提供，功能正常（cookie 非 Secure）。
  3. 启用 HTTPS 后，建议在 `.env` 设 `LOGVIEWER_SECURE_COOKIES=true`，使网关会话/ CSRF cookie 标记 Secure。
- **无域名防火墙**：8120 端口必须对外可达；云服务器还需在安全组/防火墙放行 TCP 8120（deploy 脚本已尽力 `ufw allow 8120/tcp`，但仍需确认云侧安全组）。
- **共享密钥**：主后端与日志查看器共用 `.env` 的 `LOGVIEWER_SECRET_KEY` 签发/校验令牌。deploy 脚本首次部署自动生成随机值；已部署实例升级时 `.env` 保留不变，两端始终一致。
- **双重认证**：令牌只放行「进入日志查看器站点的网关」，进入后仍需用 Django 后台超级管理员凭据登录才能真正读取日志。

### 无域名纯 IP 部署（适合还没买域名）

直接**省略 `--domain`** 即可：

```bash
cd GipfelBusinessCompetitionManagerWeb
sudo bash scripts/deploy-linux.sh \
  --install-dir /opt/gipfel \
  --with-nginx
# 不传 --domain → nginx 主站点 server_name 为 _（IP 可访问）；
#                 日志查看器改为 :8120 端口块，访问 http://<IP>:8120/；
#                 .env 自动写入 LOG_VIEWER_PUBLIC_URL=http://<IP>:8120/；
#                 ufw 自动放行 8120（若无 ufw 则提示手动放行云安全组）。
```

- **HTTP 非 HTTPS**：无域名时全站走 HTTP，cookie 非 Secure，功能正常；后续买了域名重跑 `deploy-linux.sh --domain 你的域名 --with-nginx` 即可平滑切换到子域 + HTTPS。
- **访问入口**：浏览器 `http://<IP>/`；日志查看器 `http://<IP>:8120/`（前端「系统设置 → 日志查看器」按钮，需超级管理员登录）。
- **改域名后**：重跑部署脚本传 `--domain`，vhost 会自动把日志查看器切回 `log.<DOMAIN>` 子域块（8120 端口块被删除），并移除 `.env` 里旧的 `LOG_VIEWER_PUBLIC_URL`（需手动删或重跑首次部署）——注意切换后记得跑 certbot 覆盖子域。

### 后端管理后台公网访问（防直连）

后端 `/admin` 管理后台经 nginx 主站点（同域）代理到 `127.0.0.1:8000`，并由 `BackendGateMiddleware` 网关保护：

- **仅按钮跳转**：前端「系统设置 → 后端管理界面」按钮在点击时向后端 `POST /api/auth/backend-token` 获取一次性（默认 120s）签名令牌（仅 `SUPER_ADMIN` 可获取），拼入 `/admin/?token=...` 打开。后端 `BackendGateMiddleware` 校验令牌，缺失/无效/过期均 302 重定向回前端 SPA——因此直接输入网址、书签、复制链接都会被跳回前端。
- **nginx 路由前提**：`deploy/nginx-gipfel.conf` 中 `location /admin/` 必须显式代理到后端；若缺失，该路径会被 SPA 兜底 `location /` 吞掉返回 `index.html`，管理后台在公网不可达（该 `location` 已在部署模板中内置）。
- **共享密钥**：网关令牌与主后端/日志查看器共用 `.env` 的 `LOGVIEWER_SECRET_KEY` 签发与校验（salt 为 `backend-gate` 以与日志查看器令牌隔离）。deploy 脚本首次部署自动生成随机值；已部署实例升级时 `.env` 保留不变，密钥始终一致。
- **双重认证**：令牌只放行「进入管理后台的网关」，进入后仍需用 Django 后台超级管理员凭据登录才能真正操作。
- **令牌有效期**：`.env` 的 `BACKEND_GATE_MAX_AGE`（秒，默认 120）可调。

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
