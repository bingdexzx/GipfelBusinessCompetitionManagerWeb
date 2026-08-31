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
python manage.py runserver 0.0.0.0:8000
```

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
| `SEED_ADMIN_PASSWORD` | `admin123` | | migrate 自动建 admin 时用 |
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
