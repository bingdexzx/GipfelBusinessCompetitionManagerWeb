# Gipfel Business Competition Manager Web

企业竞争模拟竞赛管理系统 —— **Vue 3 + Django 5 网站版**。
保持与原桌面版功能与界面一致，剥离 Electron，改造为纯 Web（HTTP + Socket.IO）部署。

> 原始桌面版代码不做任何改动（保留在仓库根目录下的 `server/`、`client/`、`shared/` 等目录），
> 本项目所有代码统一放在 `GipfelBusinessCompetitionManagerWeb/` 目录下。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Vue 3 + TS + Element Plus + Pinia + Vite)         │
│  · HTTP REST  →  /api/*  →  Django REST Framework           │
│  · WebSocket  →  /socket.io/*  →  python-socketio (ASGI)    │
│  · 静态资源   →  /assets/*  ←  nginx 或 Vite dev proxy      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Django 5 后端                                               │
│  · daphne ASGI server（HTTP + WebSocket 同源同端口 :8000）  │
│  · DRF：34 张表 / 24 个 app / 统一 CRUD 基类                 │
│  · JWT + RBAC：31 个权限键、角色动作等级继承                 │
│  · 实时广播：Socket.IO Rooms（comp-{id} + user-{id}）       │
│  · 合同引擎 / 股票引擎 / 产业计算图                          │
│  · SQLite（默认）/ PostgreSQL（生产）                        │
└─────────────────────────────────────────────────────────────┘
```

- **前端端口**：开发 `:5173`（Vite，自动代理 `/api` `/socket.io` `/uploads` 到 `:8000`），生产由 nginx 或 Django `STATICFILES_DIRS` 托管
- **后端端口**：Daphne 默认 `:8000`
- **上传目录**：`backend/uploads/`（环境变量 `UPLOAD_DIR`）
- **数据库**：`backend/db.sqlite3`（默认，环境变量 `DATABASE_URL` 可切换）
- **日志**：`backend/logs/`（环境变量 `LOG_DIR`）

---

## 2. 三行启动（开发者本地 · Windows）

```powershell
cd GipfelBusinessCompetitionManagerWeb
# 1. 首次初始化（虚拟环境、pip 依赖、npm 依赖、迁移、建默认超管）
powershell -ExecutionPolicy Bypass -File scripts\bootstrap-dev.ps1

# 2. 一键开发启动：同时拉起 Django (:8000) + Vite (:5173)
powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
```

浏览器访问 `http://localhost:5173`，登录默认账号：

| 用户名 | 初始密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | SUPER_ADMIN（首次登录强制改密） |

> 若想分别启动前后端，见 [backend/README.md](backend/README.md) 与 [frontend/README.md](frontend/README.md)。

---

## 3. 目录结构

```
GipfelBusinessCompetitionManagerWeb/
├── backend/                         Django 5 后端
│   ├── apps/                        24 个业务 + 基础设施 app
│   │   ├── auth/                    JWT 登录/改密/顶号/默认超管种子
│   │   ├── users/                   用户与权限版本
│   │   ├── competitions/            比赛 / 财年
│   │   ├── common/                  CRUD 基类、审计、分页、中间件、signals
│   │   ├── realtime/                Socket.IO 网关、emit 服务、seq/重放
│   │   ├── materials/parts/products 生产链
│   │   ├── maps/tech_tree/          地图与科技树
│   │   ├── companies/company_fields 公司字段（乐观锁 + 级联重算）
│   │   ├── industry_types/          产业类型 + 计算图字段
│   │   ├── contracts/               合同 + 引擎 engine.py
│   │   ├── stock/                   股票引擎（推进轮次 bulk 广播）
│   │   ├── messages/                消息中心
│   │   └── files/                   上传
│   ├── deploy/                      生产部署模板（systemd/nginx）
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md                    ← 后端专属说明
│
├── frontend/                        Vue 3 前端
│   ├── src/
│   │   ├── router/                  视图路由（按角色 lazy-load）
│   │   ├── stores/                  Pinia：auth / competition / config
│   │   ├── views/                   全部业务视图：数据管理、赛事、公司、股票等
│   │   ├── components/DataManager   通用 CRUD 组件（约 10 个简单资源直接复用）
│   │   ├── realtime/                socket 客户端 + resourceChanged 响应式广播
│   │   ├── contracts/graph-model    合同条件/效果表达式引擎
│   │   └── utils/permissions        can() / canAny() / 角色动作等级表
│   ├── vite.config.ts               dev 代理到 8000
│   ├── package.json
│   └── README.md                    ← 前端专属说明
│
├── scripts/
│   ├── bootstrap-dev.ps1            Windows 开发环境首次初始化
│   ├── start-dev.ps1                Windows 开发启动（Django + Vite 并行）
│   ├── deploy-linux.sh              Linux 一键部署（daphne + systemd + nginx + 前端静态）
│   └── deploy-windows.ps1           Windows 生产部署（nssm + 前端产物）
│
├── deploy/
│   ├── gipfel.service               systemd unit 模板
│   └── nginx-gipfel.conf            nginx 虚拟主机模板
│
├── Vue-Django迁移设计.md             技术迁移方案 / API 契约 / 阶段进度
└── README.md                        ← 你现在正在看的
```

---

## 4. 环境要求

| 组件 | 最低版本 | 建议版本 |
| --- | --- | --- |
| Python | 3.10 | **3.12**（3.13 已验证可用，需 Pillow≥11） |
| Node.js | 18 | **20 LTS**（22 也已验证） |
| npm | 9 | 10 |
| 操作系统 | — | Windows 10/11、Linux（Ubuntu 22.04+ / Debian 12） |
| 浏览器 | — | Chrome 120+、Edge 120+、Firefox 120+ |

依赖亮点（详见 `requirements.txt` 与 `package.json`）：

- 后端：`Django 5.0`、`djangorestframework 3.15`、`daphne 4.1`（ASGI）、`python-socketio 5.11`、`PyJWT`、`bcrypt`、`django-cors-headers`、`Pillow 11`、`drf-spectacular`（OpenAPI 可选）
- 前端：`Vue 3.5`、`Vue Router 4.4`、`Pinia 2.2`、`Element Plus 2.7`、`Vite 5.3`、`axios 1.7`、`echarts 5.5`、`socket.io-client 4.7`、`pinia-plugin-persistedstate 3.2`、`pinyin-pro 3.25`

---

## 5. 生产部署

### 5.1 Linux（推荐 · Ubuntu 22.04 / Debian 12）

```bash
# 在目标服务器上执行，须有 sudo 权限
cd GipfelBusinessCompetitionManagerWeb
sudo bash scripts/deploy-linux.sh \
  --domain comp.example.com \
  --install-dir /opt/gipfel \
  --with-nginx

# 完成后：
#   systemctl status gipfel      # 后端 daphne
#   systemctl status nginx       # 反向代理 + 前端静态
#   https://comp.example.com     # 访问
```

脚本自动完成：
1. 系统依赖安装（python3-venv、python3-dev、nodejs、npm、nginx、openssl）
2. 虚拟环境 + `pip install -r requirements.txt`
3. `python manage.py migrate`（自动幂等建默认 admin）
4. `npm ci && npm run build` 并把产物放到 `$INSTALL_DIR/frontend-dist`
5. 写入 `deploy/gipfel.service` → `/etc/systemd/system/gipfel.service` 并 `enable --now`
6. 写入 `deploy/nginx-gipfel.conf` → `/etc/nginx/sites-available/` 并 `ln -s` `sites-enabled`，`nginx -t && systemctl reload`
7. （可选）`certbot --nginx -d comp.example.com` 一键 HTTPS

### 5.2 Windows Server（IIS ARR + nssm 或直接 daphne）

```powershell
cd GipfelBusinessCompetitionManagerWeb
powershell -ExecutionPolicy Bypass -File scripts\deploy-windows.ps1 `
  -InstallDir "C:\gipfel" `
  -Port 8000 -FrontendPort 80
```

脚本自动完成：
1. 建虚拟环境 + pip 依赖
2. `migrate`（建默认 admin）
3. `npm ci && npm run build`
4. 使用 nssm 注册 `GipfelBackend` Windows 服务（daphne.exe :8000）
5. 前端 build 产物交给 80 端口（可选：自动配 IIS 站点/反向代理到 8000）

详细手动部署步骤、systemd/nginx 模板、回滚流程见 [deploy/README.md](deploy/README.md)。

---

## 6. 安全与合规

- **JWT**：HS256，`JWT_SECRET`（必填，未配置进程 fail-fast 拒绝启动），默认 24h，`tokenVersion` 顶号立即失效
- **RBAC**：31 个权限键、4 级动作等级继承（`view < edit < manage < admin`），`can(action, resource)` 前后端一致
- **比赛隔离**：所有业务查询自动按 `competition_id` 域过滤（`apply_competition_scope`）
- **CORS**：未配置 `CORS_ORIGIN` 时仅本地/私网反射并带凭据；公网必须显式白名单
- **安全头**：自定义中间件写入 CSP、X-Frame-Options=DENY、X-Content-Type-Options=nosniff、Strict-Transport-Security、Referrer-Policy
- **限流**：`RateLimitMiddleware` 默认 600 req/min/IP、匿名登录 10/min/IP，可 `RATE_LIMIT_*` 环境变量调节
- **乐观锁**：公司字段写操作携带 `version`，冲突 409 提示前端重试
- **删公司两步确认**：`DELETE /api/companies/:id` 先返回「删除影响预览」，前端二次确认带 `confirmName` 才执行
- **审计日志**：所有写操作（create/update/delete）统一信号 → `AuditLog` 表落库，含 operator、IP、changes JSON 快照

---

## 7. 默认账号与权限

首次 `migrate` 完成后，若 `users` 表为空，自动写入：

| 用户名 | 初始密码 | 角色 | 权限 |
| --- | --- | --- | --- |
| `admin` | `admin123` | SUPER_ADMIN | 全部 31 项 + 所有比赛域 |

**强制改密**：首次登录成功后返回的 JWT 仍能通过鉴权，但调用受 `must_change_password` 守卫的接口（如 `/auth/me`、全部业务接口）会返回 **401 `initial_password_must_be_changed`**，前端立即跳转到改密页。改密成功后 JWT 不变，`must_change_password` 置为 False，正常使用。

### 新建比赛管理员

```powershell
# 命令行创建（或前端「账号管理」里手动建）
.\.venv\Scripts\python.exe manage.py create_competition_admin `
  --username comp01admin --password "S3cret!" --competition-id 1
```

---

## 8. 常用命令速查

### 后端

```powershell
cd GipfelBusinessCompetitionManagerWeb\backend
.\.venv\Scripts\Activate.ps1            # 激活虚拟环境
python manage.py check                  # Django 系统检查
python manage.py makemigrations         # 生成模型迁移
python manage.py migrate                # 应用迁移（+ 自动 seed 默认 admin）
python manage.py createsuperuser        # 另一种建超管方式
python manage.py shell                  # ORM shell
python manage.py runserver 0.0.0.0:8000 # daphne 启动（HTTP + Socket.IO 同源）
```

### 前端

```powershell
cd GipfelBusinessCompetitionManagerWeb\frontend
npm install      # 依赖
npm run dev      # Vite 开发 :5173（代理 /api /socket.io /uploads 到 :8000）
npm run build    # 生产构建 → dist/
npm run preview  # 预览构建产物
npm run typecheck # vue-tsc 类型检查（CI 必跑）
```

### 端到端冒烟（快速验证迁移后功能）

```powershell
# 1. 起服务
cd backend; .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

# 2. 另开终端：health → login → 改密 → me → competitions CRUD → maps/full → stocks/industry-types
#    全部应为 200，参考 design doc 的 9.1 API 契约
```

---

## 9. 开发与贡献规范

- 任何新增业务模型必须在 `apps/realtime/emit.py` 的 `MODEL_TO_RESOURCE` 注册（值为 `None` 表示「列名映射但不广播」，如子表）
- 批量 ORM 操作（如股票推进轮次）用 `with suppress_signals():` 包裹，随后发 `bulk` 广播
- 前端所有 REST API 走 `src/api/index.ts` 的统一 axios 实例（带 JWT 拦截、错误 toast、Unauthorized 401 跳登录）
- 前端实时广播使用 `useResourceChanged()` composable，**不要**直接写 `socket.on`，避免重复订阅、重复调用
- 权限检查：后端装饰器 `@require_permissions("data:part:edit")` + 前端按钮 `v-if="can('edit', 'data:part')"` 成对出现
- CI：`npm run typecheck` 与 `python manage.py check` 必须全绿，无 migrations 未应用

---

## 10. 技术迁移方案

详细的技术选型、API 契约（每个路由方法/参数/返回/权限）、数据模型映射、分阶段实施进度表，见 [Vue-Django迁移设计.md](Vue-Django迁移设计.md)。

---

## 11. 与原桌面版的差异说明

| 维度 | 原桌面版（NestJS + Electron） | 本 Web 版（Django + Vue） |
| --- | --- | --- |
| 部署形态 | 桌面应用安装包 | 纯网站：浏览器访问 |
| 运行时 | 客户端内嵌 Node.js 服务 | 服务端 daphne ASGI + 浏览器 SPA |
| 数据存储 | 客户端本地 SQLite | 服务器 SQLite / Postgres |
| 实时通信 | ipcMain | Socket.IO Rooms + JWT 鉴权 |
| 认证 | 本地用户 | JWT + tokenVersion 顶号 |
| 用户范围 | 单用户本机 | 多用户 + 比赛多租户隔离 |
| API 签名 | `/api/*` REST 完全一致 | **完全一致**（前端零改动即可切换 target） |
| UI / 交互 | Element Plus 组件、路由、视图 | **完全一致**（仅剥离 Electron shell 依赖） |

一句话：**功能与界面不变，只有「交付形态」与「运行时位置」变了。**
