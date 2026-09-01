# Gipfel 商赛系统 · 运维文档（OPS）

面向运维人员的日常操作手册。架构、目录结构、API 契约见 [`README.md`](README.md)；部署步骤见 [`deploy/README.md`](deploy/README.md)。

---

## 1. 服务与端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| 前端（Vite / 生产 nginx 静态） | `:5173`（开发）/ 80·443（生产） | 浏览器访问入口 |
| 后端（Django 5 + daphne ASGI） | `:8000` | HTTP REST + Socket.IO WebSocket 同源同端口；`/admin` 管理后台仅前端按钮携带一次性令牌可进，直连 302 回前端 |
| 日志查看器（独立 Django 站点） | `:8120`（内部，仅绑定 127.0.0.1） | 在线查看 `backend/logs/`，**共享主后端 `db.sqlite3`**；公网整站代理到 `127.0.0.1:8120`，且**仅前端按钮点击（携带一次性令牌）可进入**，直接输入网址被 403 拒绝。有域名经 nginx 子域 `log.<DOMAIN>`（端口 80）；无域名（纯 IP）经 nginx `:8120` 端口（`server_name _`）访问 `http://<IP>:8120/`（详见 deploy/README.md「无域名纯 IP 部署」） |

> 后端 `:8000` 由 `start-dev.bat` 固定，不读 `.env` 的 `PORT`；`PORT` 仅被 `manage.py rundaphne` 与 `/api/version` 下发的跳转按钮使用。日志查看器端口读 `.env` 的 `LOG_VIEWER_PORT`（默认 8120）。

## 2. 环境要求

- **Python** 3.10+（实测 3.13 可用，需 Pillow≥11）
- **Node.js** 18+（推荐 20 LTS，22 已验证）
- 操作系统：Linux（Ubuntu 22.04 / Debian 12，生产推荐）、Windows 10/11（仅开发）

## 3. 启动与停止

### 3.1 Linux（生产，systemd）

```bash
systemctl start gipfel        # 后端 daphne
systemctl stop gipfel         # 停止
systemctl restart gipfel      # 重启（改代码/配置后）
systemctl status gipfel       # 状态
systemctl status gipfel-logviewer   # 日志查看器（独立站点）
systemctl status nginx        # 反向代理 + 前端静态
journalctl -u gipfel -f       # 实时日志
```

### 3.2 Windows（开发）

```bat
scripts\bootstrap-dev.bat     :: 首次：虚拟环境 + pip + npm + migrate + 建默认超管（可加 --skip-frontend）
scripts\start-dev.bat         :: 并行拉起 Django(:8000) + Vite(:5173) + 日志查看器(:8120)
```

停止：`start-dev.bat` 窗口按 `Ctrl+C` 结束全部子进程。

> `start-dev.bat` 用的是 `manage.py runserver`，但 **daphne 已在 `INSTALLED_APPS` 首位并接管了 runserver 命令**，因此实际就是以 ASGI/daphne 运行，HTTP + WebSocket 同源同端口，Socket.IO 正常。

## 4. 默认账号

| 用户名 | 密码 | 角色 | 说明 |
| --- | --- | --- | --- |
| `admin` | `admin23` | SUPER_ADMIN | 首次登录强制改密 |

- **两套账号体系**：业务 `users` 表（前端 JWT 登录，自定义 User 用 bcrypt 校验 `password_hash`）；后台 `auth_user` 表（Django `/admin` 与日志查看器登录，用 pbkdf2_sha256）。
- 日志查看器与 `/admin` **共用 `auth_user` 凭据**（均校验 `is_superuser`）。前端改密**不会**同步到后台/日志查看器。
- 密码由 `.env` 的 `SEED_ADMIN_*` 驱动；首次 `migrate` 自动创建，已存在则跳过（不覆盖）。

## 5. 健康检查

```bash
curl -sS http://127.0.0.1:8000/api/health     # 期望 {"ok":true,"service":"gipfel-backend",...}
curl -sS http://127.0.0.1:8000/api/version    # 期望含 log_viewer_url 字段（日志查看器公网地址）
curl -sS http://127.0.0.1:8120/api/health     # 日志查看器健康检查
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8120/   # 直连应为 403（防直连网关）
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/admin/   # 直连应为 302（防直连网关，Location 指向 /）
```

## 6. 常用运维命令

后端（在 `backend/` 下，激活虚拟环境 `.\.venv\Scripts\Activate.ps1` 或 `source .venv/bin/activate`）：

```bash
python manage.py check                  # Django 系统检查
python manage.py migrate                # 应用迁移（幂等，自动 seed 默认超管）
python manage.py createsuperuser        # 新建/重置后台超管（交互）
python manage.py shell                  # ORM shell
python manage.py rundaphne --bind 0.0.0.0   # 生产启动（端口取 .env 的 PORT）
```

前端（在 `frontend/` 下）：

```bash
npm run build        # 生产构建 → dist/
npm run preview      # 预览构建产物
npm run typecheck    # 类型检查（CI 必跑）
```

## 7. 日志

- **后端运行日志**：`backend/logs/gipfel.log`（按天滚动，保留 14 天）；生产亦可用 `journalctl -u gipfel -f`。
- **日志查看器**：公网经 `https://log.<DOMAIN>/`（有域名）或 `http://<IP>:8120/`（无域名纯 IP 部署，见 deploy/README.md「无域名纯 IP 部署」）整站代理；开发环境 `http://127.0.0.1:8120/`。**仅能从「系统设置 → 日志查看器」按钮（携带一次性令牌）进入**；直接输入网址会被 403 拒绝。进入后仍需用 Django 后台超级管理员凭据登录。
- **cookie 隔离**：两者同在 `localhost`，cookie 名必须不同，否则主后端 `HttpOnly` 的会盖掉前端要读的那份：

  | 站点 | CSRF cookie | Session cookie | HttpOnly |
  | --- | --- | --- | --- |
  | 主后端 `:8000` | `csrftoken` | `sessionid` | 是 |
  | 日志查看器 `:8120` | `lv_csrftoken` | `lv_sessionid` | 否（前端 JS 需读取回传 `X-CSRFToken`） |

## 8. 备份与恢复

需备份的核心数据（SQLite 默认）：

- `backend/db.sqlite3`（数据库）
- `backend/uploads/`（上传文件）
- `backend/logs/`（日志，可选）

恢复：停止服务 → 用备份覆盖上述目录 → 重启。详细回滚流程见 [`deploy/README.md`](deploy/README.md) 的「更新部署 / 回滚」一节（`deploy-linux.sh --skip-install-deps` 会自动先备份到 `/opt/gipfel/_backup/`）。

## 9. 故障排查（FAQ）

### Q1. Django 后台 `/admin` 或日志查看器登录失败，密码明明正确

- **根因（曾真实发生）**：`backend/backend/settings.py` 的 `PASSWORD_HASHERS` 若只保留 bcrypt，而 `auth_user` 账号密码是 `pbkdf2_sha256`，`identify_hasher()` 找不到 pbkdf2 算法会使 `check_password` 恒返回 `False`，表现为「密码正确却永远登录失败」。业务 `users` 表自行用 bcrypt 校验，不受影响（前端登录正常）。
- **处置**：确认 `PASSWORD_HASHERS` 含 `PBKDF2PasswordHasher` 等默认算法（当前已配置，bcrypt 排首位）。改完后用 `python manage.py shell` 验证：
  ```python
  from django.contrib.auth.models import User
  u = User.objects.get(username="admin")
  u.check_password("admin23")   # 应为 True
  ```

### Q2. 日志查看器登录报 403 `CSRF token ... has incorrect length`

- **根因**：主后端与日志查看器同在 `localhost`，CSRF/Session cookie 同名会冲突。已用 `lv_csrftoken` / `lv_sessionid` 独立前缀隔离。
- **处置（多为浏览器缓存）**：升级后若仍 403，通常是浏览器缓存了重启前的旧 `app.js`（旧版读 `csrftoken`）。**硬刷新 `Ctrl+Shift+R` 或开无痕窗口**即可。

### Q3. 双击 `bootstrap-dev.bat` 一闪而过（闪退）

- **根因（曾真实发生）**：`.bat` 块内 `echo` 文本若含圆括号，cmd 会当成命令分组，`)` 之后的内容被当作新命令而报 `or was unexpected at this time`；且该错误在**解析期**就中止脚本，跳过所有 `pause`，窗口一闪而没。
- **处置**：当前脚本已在顶部加 `cmd /k` 兜底包装——即便将来出现语法错误，窗口也会**保留并显示错误与命令提示符**，不再静默闪退。仍闪退请确认双击的是 `scripts\bootstrap-dev.bat`（而非 `start-dev.bat`），或在文件所在目录按住 Shift 右键「在此处打开命令窗口」后手动运行看输出。

### Q4. 默认密码到底是多少

`admin / admin23`（**不是 admin123**）。文档、`.env`、种子默认值、当前数据库已统一为 `admin23`。

### Q5. 改端口后前端跳转按钮还指向旧端口

前端「系统设置 → 后端管理」的红色「后端管理界面」按钮走同源相对路径 `/admin/`（不拼端口，随 nginx 域名自适应），点击时向后端 `POST /api/auth/backend-token` 取一次性令牌（仅 `SUPER_ADMIN`）拼入 `/admin/?token=...` 打开；后端 `BackendGateMiddleware` 校验，直连 `/admin/` 无令牌会被 302 重定向回前端 SPA。黄色「日志查看器」按钮地址由 `/api/version` 下发的 `log_viewer_url` 拼接（默认由请求 Host 派生 `https://log.<域名>/`，可用 `.env` 的 `LOG_VIEWER_PUBLIC_URL` 显式覆盖）。改 `.env` 的 `LOG_VIEWER_PORT` 或域名后**重启后端**即可，无需改前端代码。

### Q8. 日志查看器直接输入网址打不开 / 提示「拒绝直接访问」

- **这是预期的安全行为（防直连）**：日志查看器 `index` 视图要求携带主后端签发的一次性令牌（`POST /api/auth/logviewer-token`，仅 `SUPER_ADMIN` 可获取，默认 120s 有效）。直接输入网址、书签、复制链接都无令牌 → 403 拒绝。
- **正确入口**：主系统「系统设置 → 日志查看器」按钮（仅超级管理员可见）。点击时前端自动取令牌并拼入跳转 URL。
- **仍打不开**：① 确认已用超级管理员账号登录；② 令牌 120s 内有效，超时重开按钮即可；③ 若 403 持续，检查主后端与日志查看器 `.env` 的 `LOGVIEWER_SECRET_KEY` 是否**一致**（不一致会导致验签失败）；④ 经 nginx 子域 `log.<DOMAIN>` 访问需 DNS A 记录 + certbot 覆盖该子域（见 deploy/README.md）；⑤ **无域名纯 IP 部署**经 `http://<IP>:8120/` 访问，需确认 `deploy/nginx-gipfel.conf` 的 8120 端口块已生效（deploy 脚本无 `--domain` 时自动保留），且云/系统防火墙放行 TCP 8120（deploy 脚本无域名时自动 `ufw allow 8120/tcp`，否则需手动放行）。
- **底层**：`LOGVIEWER_GATE_MAX_AGE`（秒）/ `LOGVIEWER_GATE_SALT` 在 `backend/logviewer/logviewer/settings.py` 可调；`LOGVIEWER_SECRET_KEY` 在主后端 `settings.py` 读取，与日志查看器共用同一 `.env`。

### Q9. 直接输入网址打开 /admin 被跳回前端首页

- **这是预期的安全行为（防直连）**：后端 `/admin` 管理后台由 `BackendGateMiddleware` 网关保护，要求携带主后端签发的一次性令牌（`POST /api/auth/backend-token`，仅 `SUPER_ADMIN` 可获取，默认 120s 有效）。直接输入网址、书签、复制链接都无令牌 → 302 重定向回前端 SPA 根路径 `/`。
- **正确入口**：主系统「系统设置 → 后端管理界面」按钮（仅超级管理员可见）。点击时前端自动取令牌并拼入跳转 URL。
- **仍打不开**：① 确认已用超级管理员账号登录；② 令牌 120s 内有效，超时重开按钮即可；③ 若持续重定向，检查 `.env` 的 `LOGVIEWER_SECRET_KEY` 是否与后端一致（网关验签依赖它）。

### Q10. 打开网站显示「Welcome to nginx!」默认页

- **现象**：访问 `http://<服务器IP>/` 看到 nginx 默认欢迎页，而不是商赛系统登录页。
- **根因**：nginx 自带默认站点（`sites-enabled/default`，旧脚本可能改名成 `default.disabled`）仍然被加载，且其 `server_name _` 与 gipfel 主站点在 80 端口撞名，把 80 端口抢走了。gipfel 配置没失效，只是没拿到 80 端口。
- **自动修复**：`deploy-linux.sh` / `update-from-github.sh` 的 `--with-nginx` 步骤现在会**自动删除**所有默认站点变体（`sites-enabled/default`、`sites-enabled/default.disabled`、`sites-enabled/default.conf`、`conf.d/default.conf`），始终刷新 `gipfel.conf` 软链，reload 后还会 `curl 127.0.0.1` 校验：若仍返回欢迎页会告警（提示检查 `nginx.conf` 是否内联了默认 server 块），若后端 `gipfel` 未起会提示 502 排查。**重跑部署脚本（加 `--with-nginx`）即可自动解决**。
- **手动补救**（脚本跑过仍异常时）：
  ```bash
  sudo rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.disabled \
            /etc/nginx/sites-enabled/default.conf /etc/nginx/conf.d/default.conf
  sudo ln -sf /etc/nginx/sites-available/gipfel.conf /etc/nginx/sites-enabled/gipfel.conf
  sudo nginx -t && sudo systemctl reload nginx
  ```
- **仍显示欢迎页**：`cat /etc/nginx/nginx.conf` 看是否内联了 `server { ... }` 默认块（去掉或注释它），或 `ls /etc/nginx/sites-enabled/` 是否还有其它非 gipfel 配置冲突。
- **变为 502 Bad Gateway**：nginx 已正确接管，但后端 `gipfel` 服务没跑：`sudo systemctl restart gipfel`。

### Q6. Socket.IO / 实时数据不刷新

- `start-dev.bat` 的 `runserver` 已被 daphne 接管为 ASGI，WebSocket 正常；若异常，确认 `daphne` 在 `INSTALLED_APPS` 首位。
- 前端经 Vite 代理 `/socket.io` → `http://127.0.0.1:8000`（**显式 IPv4**，避免 Windows 上 `localhost` 解析到 IPv6 `::1` 导致 `ECONNRESET`）。

### Q7. 登录接口返回 429

`LoginRateLimitMiddleware` **只拦截 `POST /api/auth/login`**：同一 IP + 用户名在 5 分钟窗口内累计失败 10 次即锁定 15 分钟并返回 429。锁定状态存**进程内存**，重启后端即清空。阈值由 `apps/common/middleware.py` 常量 `_FAIL_WINDOW` / `_FAIL_THRESHOLD` / `_LOCK_DURATION` 控制，非环境变量。

## 10. 安全与合规速览

- **JWT**：HS256，`JWT_SECRET` 必填（未配置进程 fail-fast 拒绝启动），默认 24h，`tokenVersion` 顶号立即失效。
- **RBAC**：41 个权限键、20 个权限域；5 级动作等级蕴含（`view<edit<manage<execute<audit`，合同域自定义）。`can(action, resource)` 前后端一致。
- **比赛隔离**：业务查询按 `competition_id` 自动域过滤。
- **CORS**：未配置 `CORS_ORIGIN` 时仅本地/私网反射并带凭据；公网必须显式白名单。
- **登录限流**：见 Q7。
- **日志查看器防直连**：公网整站代理（nginx 监听公网 `:8120` → 反代内网 `127.0.0.1:8121`，日志查看器 daphne 仅绑内网 8121）；有域名经 nginx 子域 `log.<DOMAIN>`（端口 80），无域名纯 IP 经 nginx `:8120` 端口（`server_name _`）。`index` 视图校验主后端签发的一次性签名令牌（`LOGVIEWER_SECRET_KEY` 共享密钥，默认 120s 有效），缺失/无效/过期即 403，实现「仅按钮点击可跳转、直连网址无法跳转」。进入后仍需后台超级管理员登录。
- **后端管理后台 `/admin` 防直连**：`BackendGateMiddleware` 网关保护 `/admin/*`，要求携带主后端签发的一次性签名令牌（`LOGVIEWER_SECRET_KEY` 共享密钥 + salt `backend-gate`，默认 120s 有效），缺失/无效/过期即 302 重定向回前端 SPA，实现「仅按钮点击可跳转、直连网址自动跳回前端」。进入后仍需 Django 后台超级管理员登录。令牌有效期由 `.env` 的 `BACKEND_GATE_MAX_AGE`（秒）控制。
- **⚠️ 后台写库警示**：Django `/admin` 直接写 SQLite 会**绕过业务校验**（合同引擎、股票计算、权限派生、乐观锁级联重算等），常规管理请走前端界面；后台仅用于运维临时修数，改完回前端核对一致性。

## 11. 升级流程

### 首次部署（Linux 一键部署）

完整步骤见 [`deploy/README.md`](deploy/README.md) 的「获取源码」一节。最简流程（默认分支 `master`，纯 IP 省略 `--domain`）：

```bash
# 克隆到 /opt（不要叫 /opt/gipfel，会与安装目录 rsync 自拷贝冲突）
git clone https://github.com/bingdexzx/GipfelBusinessCompetitionManagerWeb.git /opt/GipfelBusinessCompetitionManagerWeb
cd /opt/GipfelBusinessCompetitionManagerWeb
sudo bash scripts/deploy-linux.sh --install-dir /opt/gipfel --with-nginx
# 有域名时加 --domain：sudo bash scripts/deploy-linux.sh --domain 你的域名 --install-dir /opt/gipfel --with-nginx
```

> GitHub 直连超时（`curl 28` / 443 连不上）时，可用镜像前缀 clone：`git clone https://ghproxy.com/https://github.com/bingdexzx/GipfelBusinessCompetitionManagerWeb.git`；或按 `deploy/README.md` 安装 FastGitHub 本地代理后走 `http://127.0.0.1:38457`。服务器完全连不上 GitHub 时，在能联网的机器上打包源码 `tar czf ...` 再 `scp` 传到服务器解包部署（详见 deploy/README.md）。

### 增量升级（保留数据）

```bash
git pull                         # 拉取代码
# 后端
cd backend && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
# 前端
cd ../frontend && npm ci && npm run build
# 重启
systemctl restart gipfel        # Linux
# Windows 开发：Ctrl+C 停 start-dev.bat 后重跑
```

升级后务必跑一次第 5 节的健康检查。
