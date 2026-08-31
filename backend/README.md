# Backend · Django 5

## 快速启动

```bash
# 1. 环境
cp .env.example .env        # 默认即可；生产务必改 JWT_SECRET
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 数据库 + 种子（首次 migrate 自动建 admin/admin123）
python manage.py migrate

# 3. 启动 daphne（HTTP + Socket.IO 同源同端口 :8000）
#    注意：必须用 daphne（ASGI）而非 runserver，否则 Socket.IO 的 WebSocket 升级无法处理。
#    绑定 127.0.0.1（IPv4）；若需局域网/容器访问可改为 0.0.0.0。
daphne -b 127.0.0.1 -p 8000 backend.asgi:application
```

## 排错：开发期 `[vite] ws proxy error: read ECONNRESET`

前端经 Vite 开发代理（`/socket.io` → 后端）连接 Socket.IO 时，控制台偶发
`read ECONNRESET` 并触发反复重连。根因与修复：

- **根因**：Vite 代理目标曾写 `http://localhost:8000`，而 Windows 上 `localhost` 优先解析到
  IPv6 `::1`；daphne 默认只监听 IPv4，代理先对 `::1` 建连被 RST 再回退 IPv4，表现为一连串 RST。
  另外 Socket.IO 默认「先轮询再升级 WebSocket」，升级时废弃的轮询长连接被中断也会产生 RST 噪声。
- **已修复**：`frontend/vite.config.ts` 代理目标已改为 `http://127.0.0.1:8000`（显式 IPv4）；
  `frontend/src/realtime/socket.ts` 客户端已限定 `transports: ["websocket"]`（跳过轮询长连接）。
- **若仍出现**：确认启动 daphne 时绑定的是 IPv4（`-b 127.0.0.1` 或 `0.0.0.0`），不要只绑 `::1`；
  且后端进程未被重启/崩溃（重启后端会令在飞连接 RST，属正常，客户端会自动重连）。


## 健康检查

```bash
curl http://127.0.0.1:8000/api/health
# 期望: {"ok":true,"service":"gipfel-backend","status":"healthy",...}
curl http://127.0.0.1:8000/api/version
# 期望: {"version":"...", "environment":"development"}
```

## 登录并改密

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | jq -r .data.token)

# 此时若直接访问受保护接口会 401 initial_password_must_be_changed
# 先改密:
curl -s -X POST http://127.0.0.1:8000/api/auth/change-password \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"oldPassword":"admin123","newPassword":"Admin@2026"}'
```

## 环境变量

| 变量 | 默认 | 必填 | 说明 |
| --- | --- | --- | --- |
| `JWT_SECRET` | — | ✅ | HS256 签名密钥；空值进程直接退出（fail-fast） |
| `DEBUG` | `false` | | `true` 启用 Django debug-toolbar（需额外安装）与详细错误页 |
| `PORT` | `8000` | | 仅命令行脚本读取；`runserver` 用命令行参数 |
| `LOG_LEVEL` | `INFO` | | `DEBUG/INFO/WARNING/ERROR/CRITICAL` |
| `LOG_DIR` | `./logs` | | 日志目录；自动创建 |
| `UPLOAD_DIR` | `./uploads` | | 文件上传目录；自动创建；前端 `/uploads/*` 由此托管 |
| `CORS_ORIGIN` | `""` | | 公网部署必填，逗号分隔白名单（或含 `*` 则全部放行）；未配置仅本地/私网 |
| `SEED_ADMIN_USERNAME` | `admin` | | 首次 migrate 自动建的超级管理员用户名（业务超管 + 后台超管共用）；已存在则跳过 |
| `SEED_ADMIN_EMAIL` | `admin@example.com` | | 后台超管邮箱 |
| `SEED_ADMIN_PASSWORD` | `admin123` | | 首次 migrate 自动建的超级管理员密码；生产务必改强密码 |
| `JWT_ISSUER` | `gipfel-competition` | | JWT iss |
| `JWT_AUDIENCE` | `gipfel-competition-client` | | JWT aud |
| `JWT_EXPIRES_IN` | `24h` | | 支持 `Nh/Nm/Ns/Nd` |
| `DATABASE_URL` | 未设置 → SQLite `./db.sqlite3` | | `postgres://user:pw@host/dbname` |

## 应用注册顺序（依赖链）

```
common (无依赖)
users  →  common
auth   →  common + users
audit  →  common + users
realtime →  common + users
competitions → common
materials / parts / products / tech_tree / maps / infrastructures / fuels / vehicles / warehouses / production_lines → competitions
industry_types (全局)
companies + company_fields → competitions + industry_types
contracts → competitions + companies
regions + consumer_demands → competitions + maps
messages (label=gipfel_messages) → competitions + users
stock → competitions + companies + users
files → common
```

> `apps.messages` label 显式取 `gipfel_messages`，避免与 `django.contrib.messages` 冲突。

## 通用 CRUD 契约

所有「资源列表/详情」类路由都遵循以下模式：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET    | `/api/{resource}?page=1&pageSize=10&competitionId=1` | 分页列表；比赛隔离自动套用 |
| POST   | `/api/{resource}` | 创建；业务校验通过后返回单条资源 |
| GET    | `/api/{resource}/:id` | 详情 |
| PUT    | `/api/{resource}/:id` | 整体更新（含嵌套关联会事务内全量替换） |
| PATCH  | `/api/{resource}/:id` | 部分更新；简单字段与 PUT 等价，嵌套关联推荐用 PUT |
| DELETE | `/api/{resource}/:id` | 删除；PROTECT 外键阻塞返回 409 |
| GET    | `/api/{resource}/:id/impact` | **删除影响预览**：返回受影响关联对象计数，前端两步删除 UI 用 |

响应统一 `ResponseEnvelope<T>`：

```json
{
  "ok": true,
  "message": "",
  "data": { "id": 1, "name": "..." },   // T
  "error": null
}
```

分页列表的 `data` 还带 `pagination` 字段。

## 数据库迁移

```bash
python manage.py makemigrations        # 全应用扫描生成
python manage.py makemigrations users  # 指定 app
python manage.py migrate               # 应用 + seed 默认超管
python manage.py migrate --fake-initial  # 首次从生产库导入表结构时用
```

循环依赖（`companies ↔ regions` 外键，`parts/products` 自引用 tech_node）已自动拆为 `0001_initial.py` + `0002_*.py`，无需人工干预。

## Django Shell 常用片段

```python
# 列出所有比赛及其公司数
from apps.competitions.models import Competition
[(c.name, c.companies.count()) for c in Competition.objects.all()]

# 赋权 + 触发权限缓存刷新广播
from apps.users.models import User
u = User.objects.get(username="staff01")
u.permissions = '{"data:part:view":1,"data:material:edit":1}'
u.permission_version = (u.permission_version or 0) + 1
u.save()
from apps.realtime.emit import emit_permissions_changed
emit_permissions_changed(u.id, u.permission_version)
```

## Django 管理后台（Admin）

项目已完整启用 Django 自带管理后台，可直接在网页上查看 / 增删改查全部业务数据，便于运维临时排查与修数。

### 访问与账号

- 访问地址：`http://<host>:8000/admin/`（与 API、Socket.IO 同源同端口）
  - 开发期若前端走 Vite 开发服务器（默认 `http://localhost:5173`），也可直接访问 `http://localhost:5173/admin/`，Vite 已把 `/admin` 与 `/static` 代理到后端 8000，无需直连后端端口。
- 超级管理员账号（首次 `migrate` 自动从 `.env` 的 `SEED_ADMIN_*` 创建；业务超管与后台超管共用同一凭据，**已存在则跳过、不覆盖**）：

  | 用户名 | 密码 | 说明 |
  | --- | --- | --- |
  | `admin` | 见 `.env`（`SEED_ADMIN_PASSWORD`，默认 `admin123`） | 生产务必改用强密码；**建议首次登录后立即改密** |

- 登录后可见 39 个业务模型（公司 / 比赛 / 合同 / 股票 / 原料 / 零件 / 产品 / 地图节点 / 基础设施 / 燃料 / 车辆 / 仓库 / 生产线 / 行业类型 / 区域 / 消费需求 / 消息 / 技术树 / 审计等）+ Django 内置的 用户 / 组。

### ⚠️ 重要警示：后台仅用于临时排查 / 修数

> Django 后台直接写 SQLite，**会绕过所有后端业务校验**：
> - 合同执行引擎（DRAFT 直接改 EXECUTED 会导致账实不符、字段效果不触发）
> - 股票 K 线计算、行情推进轮次
> - 权限派生（前端简化界面自动生成的 permissions 与四个 Scopes）
> - 公司字段乐观锁级联重算、删除影响预览（两步确认）等
>
> 因此，**常规管理请一律走前端 Vue 界面**；后台只适合运维临时修数、补救脏数据，改完务必回到前端核对数据一致性。

### 创建 / 重置超级管理员

```bash
cd backend
# 交互式创建（按提示输入用户名 / 邮箱 / 密码）
.\.venv\Scripts\python.exe manage.py createsuperuser

# 无交互式（CI / 脚本）
set DJANGO_SUPERUSER_USERNAME=admin
set DJANGO_SUPERUSER_EMAIL=admin@example.com
set DJANGO_SUPERUSER_PASSWORD=YourNewPass!
.\.venv\Scripts\python.exe manage.py createsuperuser --no-input
```

> 注意：超级管理员只存在于当前 `db.sqlite3`。**重新 `migrate`（换库 / 换机器 / 清空数据库）后需再次执行 `createsuperuser`**。

### 后台能正常工作的两个关键改动（技术说明）

1. **`backend/urls.py`** 挂载了 `path("admin/", admin.site.urls)`，并额外用 `re_path` 无条件托管 `STATIC_ROOT`，使 `DEBUG=False` 时后台样式与脚本也能加载（`django.conf.urls.static.static` 仅在 `DEBUG=True` 时挂载）。
2. **`apps/common/middleware.py`** 的 `SecurityHeadersMiddleware` 对 `/admin` 路径跳过 CSP 等安全头——否则全局 `default-src 'none'; form-action 'none'` 会直接拦截登录与所有表单提交。该豁免仅作用于 `/admin`，`/api` 等接口的安全头保持不变。
3. **`apps/auth/bootstrap.py`** 的 `seed_default_admin` 在 `post_migrate` 信号中自动建超管：写入业务 `users` 表（`role=SUPER_ADMIN`，前端 JWT 登录用）+ 后台 `auth_user` 表（`is_staff/is_superuser=True`，`/admin` 登录用），凭据均来自 `.env` 的 `SEED_ADMIN_*`，幂等（已存在则跳过）。
