# 02 · API 契约全集

> 基准：`origin/master`（提交 `fca118c`），只读导出在 `.baseline-master/`。
> 本章所有行号都是在**该提交**上数的（与工作树 `bugfix-merged` 普遍不同）。
> 唯一验收口径：**凭本章能实现出一个前端零改动即可对接的 HTTP 层**。

---

## 0. 本章速览

### 覆盖范围

| 覆盖 | 不覆盖 |
| --- | --- |
| 主后端 `/api/*` 全部 **121 条路由 / 216 个方法级端点**的完整清单 | 权限 key 的语义、动作蕴含、角色模板（见 [03-认证权限与安全.md](03-认证权限与安全.md)） |
| 统一响应信封 `{code,message,data}` 的精确形状与可复制 JSON | 各实体字段的完整定义（见 [01-领域模型与数据库.md](01-领域模型与数据库.md)） |
| 分页参数、默认值、上限、四种列表形状 | 前端响应缓存 / 本地全量副本 / 增量对账策略（见 [06-前端架构.md](06-前端架构.md)） |
| 错误表达：HTTP 状态码 + 中文 message（**无机器码**） | 合同 / 股票引擎的算法（见 [05-核心引擎与算法.md](05-核心引擎与算法.md)） |
| 通用 CRUD 基类的钩子方法名与调用顺序 | Socket.IO 事件名与房间模型（见 [04-实时通信协议.md](04-实时通信协议.md)） |
| 比赛域隔离：`scope.py` 与 `guards.py` 的实际分工 | 部署、端口、环境变量、nginx（见 [07-部署运维与环境变量.md](07-部署运维与环境变量.md)） |
| 增量同步 `updatedAfter` 协议 | Django admin 内部的 257 条子路由（只在 §9.3 说明网关） |
| 文件上传、附件下载、`/uploads/` 静态托管 | 日志查看器应用的 UI（只在 §1.3 列出其 9 条路由） |
| 无鉴权 / 白名单端点清单 | — |
| 前端实际调用路径 vs 后端路由的差异（孤儿 / 僵尸） | — |

### 数据来源文件（本章实际读过的 `.baseline-master/` 文件）

后端：`backend/backend/urls.py`、`backend/backend/settings.py`、26 个 `backend/apps/*/urls.py`、`backend/logviewer/logviewer/urls.py`、`backend/apps/common/{response,renderers,exceptions,pagination,base_crud,guards,scope,sync,permissions,middleware,backend_gate,rate_limit,rate_limit_views}.py`、`backend/apps/auth/{views,authentication}.py`、`backend/apps/files/views.py`、`backend/apps/messages/views.py`、`backend/apps/competitions/views.py`、`backend/apps/users/views.py`、`backend/apps/companies/views.py`、`backend/apps/company_fields/views.py`、`backend/apps/contracts/views.py`、`backend/apps/stock/views.py`、`backend/apps/preparation/views.py`。

前端：`frontend/src/api/{index.ts,request.ts}`、`frontend/src/stores/{auth,version}.ts`、`frontend/src/views/**`（全量 grep 路径字面量）、`frontend/src/components/**`。

### 关键统计（附获取命令）

| 指标 | `origin/master` | 获取命令 |
| --- | --- | --- |
| 有 `urls.py` 的 app | **26** | `Get-ChildItem .baseline-master/backend/apps -Directory \| Where-Object { Test-Path "$($_.FullName)/urls.py" } \| Measure-Object` |
| `urls.py` 文件总数 | **28**（26 app + `backend/urls.py` + `logviewer/logviewer/urls.py`） | 同上 + 2 |
| `path()/re_path()` 注册 | **120** = `backend/urls.py` **33** + `logviewer` **9** + 各 app **78** | 见脚本 A |
| 主后端解析出的路由总数 | **380** = `/api/*` **121** + admin **257** + 静态托管 **2** | 见脚本 B |
| **`/api/*` 方法级端点** | **216** | 见脚本 B |
| 　└ 口径 | **只数视图类显式定义的 `get`/`post`/`put`/`patch`/`delete`，不含 DRF 自动生成的 `OPTIONS`/`HEAD`**；含自动 `OPTIONS` 则为 **337**（216 + 121） | 脚本 B |
| 　└ 方法分布 | GET **90** / POST **46** / PATCH **32** / DELETE **30** / PUT **18** | 同上 |
| 权限 key / 域 | **39 / 19**（`permissions.py:3` 自述一致） | `Select-String -Path .baseline-master/backend/apps/common/permissions.py -Pattern '"key": "\w+:\w+"'` |
| `BusinessError(...)` 调用点 | **228** | 见脚本 C |
| 出现过的业务错误码字面量 | **7 个**：400 / 401 / 403 / 404 / 409 / 500 / 503 | 同上 |
| 出站响应体里的机器码（`errorCode`） | **0 个**（全仓库零命中） | `Select-String -Path .baseline-master/backend -Include *.py -Pattern 'errorCode' -Recurse` |
| 中间件条目 | **14**（`settings.py:273-291`） | — |

> **行数口径说明**：本章引用的**单文件行数**一律是**原始行数**（含空行与注释，等于读取工具报告的 `total N lines`）。**汇总类**行数（app 总行数、`.vue`/`.ts` 总行数）在本套文档中采用**非空行**口径 —— 两者不可混用。

**脚本 A · 数 `path()` 注册**

```powershell
Get-ChildItem .baseline-master -Recurse -Filter urls.py -File |
  ForEach-Object { "{0,-50} {1}" -f $_.FullName.Replace((Get-Location).Path,''), (Select-String -Path $_.FullName -Pattern '^\s*(re_)?path\(' | Measure-Object).Count }
# 合计 120 = backend/urls.py 33 + logviewer 9 + 26 个 app urls.py 78
```

**脚本 B · 用 Django 解析器展开路由（只读，零写盘）**

```powershell
@'
import sys, os, pathlib, collections
pathlib.Path.mkdir = lambda self, *a, **k: None      # 屏蔽 settings 里的 mkdir，保证不写盘
sys.path.insert(0, os.path.abspath(".baseline-master/backend"))
os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"
os.environ.setdefault("JWT_SECRET", "baseline-readonly-probe-key-0123456789abcdef")
import django; django.setup()
from django.urls import get_resolver
from rest_framework.views import APIView
res = get_resolver(); rows = []
def walk(ps, prefix=""):
    for p in ps:
        if hasattr(p, "url_patterns"): walk(p.url_patterns, prefix + str(p.pattern))
        else: rows.append((prefix + str(p.pattern), p))
walk(res.url_patterns)
api = [r for r in rows if r[0].startswith("api/")]
def methods(p):
    vc = getattr(p.callback, "view_class", None)
    return ["GET"] if vc is None else [m.upper() for m in ("get","post","put","patch","delete") if hasattr(vc, m)]
mh = collections.Counter()
for _, p in api:
    for m in methods(p): mh[m] += 1
print("total=%d api=%d api_methods=%d admin=%d" % (
    len(rows), len(api), sum(mh.values()), len([r for r in rows if r[0].startswith("admin/")])))
print("method_histogram=%s (不含 DRF 自动 OPTIONS/HEAD)" % dict(mh))
print("APIView.permission_classes =", tuple(c.__name__ for c in APIView.permission_classes))
ft = []
for pat, p in api:
    vc = getattr(p.callback, "view_class", None)
    if vc is None: continue
    owner = next(k for k in vc.__mro__ if "permission_classes" in k.__dict__)
    if owner is APIView: ft.append(pat)
print("routes_falling_through_to_APIView =", len(ft), ft)
'@ | & backend\.venv\Scripts\python.exe -
# 输出：
# total=380 api=121 api_methods=216 admin=257
# method_histogram={'GET': 90, 'POST': 46, 'PATCH': 32, 'DELETE': 30, 'PUT': 18} (不含 DRF 自动 OPTIONS/HEAD)
# APIView.permission_classes = ('IsAuthenticated', 'CompetitionScopePermission')
# routes_falling_through_to_APIView = 0 []
```

**脚本 C · 数业务错误码**

```powershell
@'
import re, pathlib, collections
pat = re.compile(r"BusinessError\(\s*(?:\"\"\"(.*?)\"\"\"|\"(.*?)\"|f\"(.*?)\"|'(.*?)'|f'(.*?)')\s*,\s*code=([^,]+),\s*status_code=([^)]+)\)", re.S)
rows = []
for f in pathlib.Path(".baseline-master/backend/apps").rglob("*.py"):
    if "__pycache__" in str(f) or "migrations" in str(f): continue
    for m in pat.finditer(f.read_text(encoding="utf-8", errors="replace")):
        rows.append(m.group(5).strip().rstrip(","))
print("calls=%d codes=%s" % (len(rows), dict(sorted(collections.Counter(rows).items(), key=lambda x: int(x[0])))))
'@ | & backend\.venv\Scripts\python.exe -
# 输出：calls=228 codes={'400': 122, '401': 1, '403': 36, '404': 53, '409': 14, '500': 1, '503': 1}
```

---

## 1. 路由总表（完整，不抽样）

### 1.1 顶层注册（`backend/backend/urls.py`，共 66 行）

| 行 | 注册 | 说明 |
| --- | --- | --- |
| `:16` | `path("admin/", admin.site.urls)` | Django admin，另有 257 条子路由；见 §9.3 |
| `:18` | `path("api/health", HealthView)` | 无鉴权 |
| `:19` | `path("api/version", VersionView)` | 无鉴权（字段分级） |
| `:21` | `path("api/auth/", include("apps.auth.urls"))` | 前缀 `api/auth/` |
| `:23` | `path("api/", include("apps.users.urls"))` | 注释说明：子路由非空，避免 `POST /api/users` 触发尾随斜杠重定向 |
| `:25` | `path("api/system/rate-limit", RateLimitConfigView)` | **仅超管**（视图内判定） |
| `:26` | `path("api/system/rate-limit/reset", RateLimitResetView)` | 同上 |
| `:28-50` | 23 条 `path("api/", include(...))` | competitions / materials / parts / products / tech_tree / maps / infrastructures / fuels / vehicles / warehouses / production_lines / industry_types / companies / company_fields / contracts / regions / consumer_demands / messages / stock / files / audit / announcements / widget_packages |
| `:52` | `path("api/", include("apps.preparation.urls"))` | **比赛准备总览与归档**（只读 + 导入），注释标注「需 `competition:manage`」 |
| `:59` | `re_path(r"^uploads/(?P<path>.*)$", static_serve, {document_root: MEDIA_ROOT})` | **无条件托管**（DEBUG=False 也生效，见 `:55-58` 的注释） |
| `:65` | `re_path(r"^static/(?P<path>.*)$", static_serve, {document_root: STATIC_ROOT})` | 同上 |

⚠️ **无尾随斜杠**：业务路由全部写成 `path("materials")` 这类**无尾斜杠**形态。`/api/materials` 命中；`/api/materials/` 落到 `CommonMiddleware`，而 `APPEND_SLASH` 只会给无尾斜杠的请求补 `/`，方向相反 → **404（不是 301）**。

### 1.2 全量方法级路由表（**216 行**，与脚本 B 输出逐条对应）

图例：
- 「权限」列 = 该方法上 `@require_permissions(...)` 标注的 key；`—` = **未标注，仅要求已登录**（设计基线，见 §10.2）；
- 「CRUD」= 视图由 `apps/common/base_crud.py` 生成，权限取自类属性 `view_permission`（GET）/ `edit_permission`（非 GET），见 §5；
- 「域」列：`比赛` = 走 `apply_competition_scope` 过滤；`全局` = 不按比赛过滤；`视图内` = 在函数体内自行判定。

#### 1.2.1 健康检查 / 版本 / 流量限制（4 条路由，5 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/health` | `HealthView`（`auth/views.py:67`） | `AllowAny`（**无鉴权**） | 全局 |
| GET | `/api/version` | `VersionView`（`auth/views.py:76`） | `AllowAny`（**无鉴权**，字段分级） | 全局 |
| GET | `/api/system/rate-limit` | `RateLimitConfigView`（`common/rate_limit_views.py:20`） | 登录 + **视图内 `role=="SUPER_ADMIN"`**（`:27`） | 全局 |
| PUT | `/api/system/rate-limit` | 同上 | 同上（`:55`） | 全局 |
| POST | `/api/system/rate-limit/reset` | `RateLimitResetView`（`common/rate_limit_views.py:88`） | 登录 + 视图内 `role=="SUPER_ADMIN"`（`:95`） | 全局 |

#### 1.2.2 认证（5 条路由，5 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| POST | `/api/auth/login` | `LoginView`（`auth/views.py:120`） | `AllowAny`（**无鉴权**） | 全局 |
| GET | `/api/auth/me` | `MeView`（`auth/views.py:217`） | `IsAuthenticated` | 全局 |
| POST | `/api/auth/change-password` | `ChangePasswordView`（`auth/views.py:227`） | `IsAuthenticated`；**强改密门禁唯一放行路径** | 全局 |
| POST | `/api/auth/logviewer-token` | `LogViewerTokenView`（`auth/views.py:171`） | 登录 + 视图内 `role=="SUPER_ADMIN"` | 全局 |
| POST | `/api/auth/backend-token` | `BackendTokenView`（`auth/views.py:194`） | 登录 + 视图内 `role=="SUPER_ADMIN"` | 全局 |

#### 1.2.3 用户（4 条路由，7 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/users` | `UserCollectionAPIView`（`users/views.py:197`） | `account:manage` | 视图内（`competitionId` 过滤） |
| POST | `/api/users` | 同上 | `account:manage` | 视图内 |
| GET | `/api/users/<int:pk>` | `UserItemAPIView`（`users/views.py:201`） | `account:manage` | 视图内 |
| PATCH | `/api/users/<int:pk>` | 同上 | `account:manage` | 视图内 |
| DELETE | `/api/users/<int:pk>` | 同上 | `account:manage` | 视图内 |
| PATCH | `/api/users/<int:pk>/password` | `UserPasswordView`（`users/views.py:142`） | `account:manage` | 视图内 |
| POST | `/api/users/<int:pk>/permissions` | `UserPermissionsView`（`users/views.py:169`） | `account:manage` | 视图内 |

#### 1.2.4 比赛与财年（4 条路由，9 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/competitions` | `CompetitionCollectionAPIView`（`competitions/views.py:253`） | —（仅登录） | 视图内（非超管强制 `pk=user.competition_id`，`competitions/views.py:94`） |
| POST | `/api/competitions` | 同上 | `competition:manage`（`:108`） | 全局 |
| GET | `/api/competitions/<int:pk>` | `CompetitionItemAPIView`（`competitions/views.py:257`） | —（仅登录） | 视图内 |
| PATCH | `/api/competitions/<int:pk>` | 同上 | `competition:manage`（`:134`） | 视图内 |
| DELETE | `/api/competitions/<int:pk>` | 同上 | `competition:manage`（`:157`） | 视图内 |
| GET | `/api/competitions/<int:cid>/fiscal-years` | `FiscalYearCollectionAPIView`（`competitions/views.py:263`） | —（仅登录） | 按 `cid` |
| POST | `/api/competitions/<int:cid>/fiscal-years` | 同上 | `competition:manage`（`:186`） | 按 `cid` |
| PATCH | `/api/competitions/fiscal-years/<int:pk>` | `FiscalYearItemAPIView`（`competitions/views.py:267`） | `competition:manage`（`:211`） | 按实体 |
| DELETE | `/api/competitions/fiscal-years/<int:pk>` | 同上 | `competition:manage`（`:245`） | 按实体 |

#### 1.2.5 通用 CRUD 资源（`base_crud` 视图：13 个资源 / 36 条路由 / 88 个方法级端点）

`crud_urlpatterns(resource, collection, item, impact=None)`（`base_crud.py:227-249`）生成固定三件套，权限取类属性：

| 资源 | GET 列表 | POST 创建 | GET 详情 | PUT | PATCH | DELETE | GET `/impact` | `view_permission` | `edit_permission` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/materials` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:material:view` | `data:material:edit` |
| `/api/parts` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:part:view` | `data:part:edit` |
| `/api/products` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:product:view` | `data:product:edit` |
| `/api/tech-nodes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:tech:view` | `data:tech:edit` |
| `/api/infrastructures` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **✗ 无此路由** | `data:infrastructure:view` | `data:infrastructure:edit` |
| `/api/fuels` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:fuel:view` | `data:fuel:edit` |
| `/api/vehicles` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:vehicle:view` | `data:vehicle:edit` |
| `/api/warehouses` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **✗ 无此路由** | `data:warehouse:view` | `data:warehouse:edit` |
| `/api/production-lines` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **✗ 无此路由** | `data:productionLine:view` | `data:productionLine:edit` |
| `/api/map-node-types` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:map:view` | `data:map:edit` |
| `/api/path-types` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:map:view` | `data:map:edit` |
| `/api/map-nodes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:map:view` | `data:map:edit` |
| `/api/map-edges` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `data:map:view` | `data:map:edit` |

`crud_urlpatterns` 被调用 **14 次**：`companies` 1 + `maps` 4 + 9 个基础资源。
14 个资源合计 **39 条路由** = 14×2（collection + item）+ 11 条 `impact`；**11 个资源传了 `impact_view`**，缺 `infrastructures` / `warehouses` / `production-lines` 三个 —— 这就是 §11.1 孤儿接口的根因。
上表 13 行是**使用 `base_crud` 视图类**的资源；第 14 个 `companies` 用自定义视图（见 1.2.7）。

**方法级端点明细（属于 `base_crud` 的 36 条路由 → 13×7 − 3 = 88 个方法级端点）：**

| 方法 | 路径 | 视图 | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/materials` | `CollectionAPIView` | `data:material:view` | 比赛 |
| POST | `/api/materials` | 同上 | `data:material:edit` | 比赛 |
| GET | `/api/materials/<int:pk>` | `ItemAPIView` | `data:material:view` | 比赛 |
| PUT | `/api/materials/<int:pk>` | 同上 | `data:material:edit` | 比赛 |
| PATCH | `/api/materials/<int:pk>` | 同上 | `data:material:edit` | 比赛 |
| DELETE | `/api/materials/<int:pk>` | 同上 | `data:material:edit` | 比赛 |
| GET | `/api/materials/<int:pk>/impact` | `ImpactView`（`materials/views.py`） | `data:material:view` | 比赛 |
| GET | `/api/parts` | `CollectionAPIView` | `data:part:view` | 比赛 |
| POST | `/api/parts` | 同上 | `data:part:edit` | 比赛 |
| GET | `/api/parts/<int:pk>` | `ItemAPIView` | `data:part:view` | 比赛 |
| PUT | `/api/parts/<int:pk>` | 同上 | `data:part:edit` | 比赛 |
| PATCH | `/api/parts/<int:pk>` | 同上 | `data:part:edit` | 比赛 |
| DELETE | `/api/parts/<int:pk>` | 同上 | `data:part:edit` | 比赛 |
| GET | `/api/parts/<int:pk>/impact` | `PartImpactView`（`parts/views.py`） | `data:part:view` | 比赛 |
| GET | `/api/products` | `CollectionAPIView` | `data:product:view` | 比赛 |
| POST | `/api/products` | 同上 | `data:product:edit` | 比赛 |
| GET | `/api/products/<int:pk>` | `ItemAPIView` | `data:product:view` | 比赛 |
| PUT | `/api/products/<int:pk>` | 同上 | `data:product:edit` | 比赛 |
| PATCH | `/api/products/<int:pk>` | 同上 | `data:product:edit` | 比赛 |
| DELETE | `/api/products/<int:pk>` | 同上 | `data:product:edit` | 比赛 |
| GET | `/api/products/<int:pk>/impact` | `ProductImpactView`（`products/views.py`） | `data:product:view` | 比赛 |
| GET | `/api/tech-nodes` | `CollectionAPIView` | `data:tech:view` | 比赛 |
| POST | `/api/tech-nodes` | 同上 | `data:tech:edit` | 比赛 |
| GET | `/api/tech-nodes/<int:pk>` | `ItemAPIView` | `data:tech:view` | 比赛 |
| PUT | `/api/tech-nodes/<int:pk>` | 同上 | `data:tech:edit` | 比赛 |
| PATCH | `/api/tech-nodes/<int:pk>` | 同上 | `data:tech:edit` | 比赛 |
| DELETE | `/api/tech-nodes/<int:pk>` | 同上 | `data:tech:edit` | 比赛 |
| GET | `/api/tech-nodes/<int:pk>/impact` | `ImpactView`（`tech_tree/views.py`） | `data:tech:view` | 比赛 |
| GET | `/api/infrastructures` | `CollectionAPIView` | `data:infrastructure:view` | 比赛 |
| POST | `/api/infrastructures` | 同上 | `data:infrastructure:edit` | 比赛 |
| GET | `/api/infrastructures/<int:pk>` | `ItemAPIView` | `data:infrastructure:view` | 比赛 |
| PUT | `/api/infrastructures/<int:pk>` | 同上 | `data:infrastructure:edit` | 比赛 |
| PATCH | `/api/infrastructures/<int:pk>` | 同上 | `data:infrastructure:edit` | 比赛 |
| DELETE | `/api/infrastructures/<int:pk>` | 同上 | `data:infrastructure:edit` | 比赛 |
| GET | `/api/fuels` | `CollectionAPIView` | `data:fuel:view` | 比赛 |
| POST | `/api/fuels` | 同上 | `data:fuel:edit` | 比赛 |
| GET | `/api/fuels/<int:pk>` | `ItemAPIView` | `data:fuel:view` | 比赛 |
| PUT | `/api/fuels/<int:pk>` | 同上 | `data:fuel:edit` | 比赛 |
| PATCH | `/api/fuels/<int:pk>` | 同上 | `data:fuel:edit` | 比赛 |
| DELETE | `/api/fuels/<int:pk>` | 同上 | `data:fuel:edit` | 比赛 |
| GET | `/api/fuels/<int:pk>/impact` | `ImpactView`（`fuels/views.py`） | `data:fuel:view` | 比赛 |
| GET | `/api/vehicles` | `CollectionAPIView` | `data:vehicle:view` | 比赛 |
| POST | `/api/vehicles` | 同上 | `data:vehicle:edit` | 比赛 |
| GET | `/api/vehicles/<int:pk>` | `ItemAPIView` | `data:vehicle:view` | 比赛 |
| PUT | `/api/vehicles/<int:pk>` | 同上 | `data:vehicle:edit` | 比赛 |
| PATCH | `/api/vehicles/<int:pk>` | 同上 | `data:vehicle:edit` | 比赛 |
| DELETE | `/api/vehicles/<int:pk>` | 同上 | `data:vehicle:edit` | 比赛 |
| GET | `/api/vehicles/<int:pk>/impact` | `VehicleImpactView`（`vehicles/views.py`） | `data:vehicle:view` | 比赛 |
| GET | `/api/warehouses` | `CollectionAPIView` | `data:warehouse:view` | 比赛 |
| POST | `/api/warehouses` | 同上 | `data:warehouse:edit` | 比赛 |
| GET | `/api/warehouses/<int:pk>` | `ItemAPIView` | `data:warehouse:view` | 比赛 |
| PUT | `/api/warehouses/<int:pk>` | 同上 | `data:warehouse:edit` | 比赛 |
| PATCH | `/api/warehouses/<int:pk>` | 同上 | `data:warehouse:edit` | 比赛 |
| DELETE | `/api/warehouses/<int:pk>` | 同上 | `data:warehouse:edit` | 比赛 |
| GET | `/api/production-lines` | `CollectionAPIView` | `data:productionLine:view` | 比赛 |
| POST | `/api/production-lines` | 同上 | `data:productionLine:edit` | 比赛 |
| GET | `/api/production-lines/<int:pk>` | `ItemAPIView` | `data:productionLine:view` | 比赛 |
| PUT | `/api/production-lines/<int:pk>` | 同上 | `data:productionLine:edit` | 比赛 |
| PATCH | `/api/production-lines/<int:pk>` | 同上 | `data:productionLine:edit` | 比赛 |
| DELETE | `/api/production-lines/<int:pk>` | 同上 | `data:productionLine:edit` | 比赛 |
| GET | `/api/map-node-types` | `CollectionAPIView` | `data:map:view` | 比赛 |
| POST | `/api/map-node-types` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/map-node-types/<int:pk>` | `ItemAPIView` | `data:map:view` | 比赛 |
| PUT | `/api/map-node-types/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| PATCH | `/api/map-node-types/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| DELETE | `/api/map-node-types/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/map-node-types/<int:pk>/impact` | `NodeTypeImpactView`（`maps/views.py:95`） | `data:map:view` | 比赛 |
| GET | `/api/path-types` | `CollectionAPIView` | `data:map:view` | 比赛 |
| POST | `/api/path-types` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/path-types/<int:pk>` | `ItemAPIView` | `data:map:view` | 比赛 |
| PUT | `/api/path-types/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| PATCH | `/api/path-types/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| DELETE | `/api/path-types/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/path-types/<int:pk>/impact` | `PathTypeImpactView`（`maps/views.py`） | `data:map:view` | 比赛 |
| GET | `/api/map-nodes` | `CollectionAPIView` | `data:map:view` | 比赛 |
| POST | `/api/map-nodes` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/map-nodes/<int:pk>` | `ItemAPIView` | `data:map:view` | 比赛 |
| PUT | `/api/map-nodes/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| PATCH | `/api/map-nodes/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| DELETE | `/api/map-nodes/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/map-nodes/<int:pk>/impact` | `MapNodeImpactView`（`maps/views.py`） | `data:map:view` | 比赛 |
| GET | `/api/map-edges` | `CollectionAPIView` | `data:map:view` | 比赛 |
| POST | `/api/map-edges` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/map-edges/<int:pk>` | `ItemAPIView` | `data:map:view` | 比赛 |
| PUT | `/api/map-edges/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| PATCH | `/api/map-edges/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| DELETE | `/api/map-edges/<int:pk>` | 同上 | `data:map:edit` | 比赛 |
| GET | `/api/map-edges/<int:pk>/impact` | `MapEdgeImpactView`（`maps/views.py`） | `data:map:view` | 比赛 |
| GET | `/api/maps/full` | `MapFullView`（`maps/views.py:42`） | `data:map:view`（类属性 + `CrudPermission`，`maps/views.py:38`） | 比赛（4 个 queryset 各自 `apply_competition_scope`，`maps/views.py:51-54`） |

#### 1.2.6 产业类型（4 条路由，9 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/industry-types` | `CollectionView`（`industry_types/views.py:352`） | `industryType:view`（`:355`）；支持 `updatedAfter` | 全局 |
| POST | `/api/industry-types` | 同上 | `industryType:manage`（`:375`） | 全局 |
| GET | `/api/industry-types/<int:pk>` | `ItemView`（`industry_types/views.py:403`） | `industryType:view`（`:406`） | 全局 |
| PATCH | `/api/industry-types/<int:pk>` | 同上 | `industryType:manage`（`:410`） | 全局 |
| DELETE | `/api/industry-types/<int:pk>` | 同上 | `industryType:manage`（`:430`） | 全局 |
| GET | `/api/industry-types/<int:pk>/fields` | `FieldListView`（`industry_types/views.py:466`） | `industryType:view`（`:469`） | 全局 |
| POST | `/api/industry-types/<int:pk>/fields` | 同上 | `industryType:manage`（`:477`） | 全局 |
| PATCH | `/api/industry-types/fields/<int:field_id>` | `FieldItemView`（`industry_types/views.py:534`） | `industryType:manage`（`:537`） | 全局 |
| DELETE | `/api/industry-types/fields/<int:field_id>` | 同上 | `industryType:manage` | 全局 |

⚠️ **路由顺序**：`industry-types/fields/<int:field_id>` 必须排在 `industry-types/<int:pk>` **之前**（`industry_types/urls.py:29-40` 的注释）。若被 `<int:pk>` 先匹配，`fields` 非整数 → 404。

#### 1.2.7 公司 / 公司产业字段（6 条路由，10 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/companies` | `CollectionAPIView`（`companies/views.py:45`） | `company:view`（`:50`）；支持 `updatedAfter` | 比赛 + `viewCompanyScopes` |
| POST | `/api/companies` | 同上 | `company:manage`（`:96`） | 比赛（`create_competition_id`，`:98-104`） |
| GET | `/api/companies/<int:pk>` | `ItemAPIView`（`companies/views.py:109`） | `company:view`（`:114`） | 比赛 |
| PATCH | `/api/companies/<int:pk>` | 同上 | `company:manage`（`:119`）；**仅接受 `name`/`status`/`regionId`**（`_UPDATE_FIELDS`） | 比赛 |
| DELETE | `/api/companies/<int:pk>` | 同上 | `company:manage`（`:129`）；引用保护（合同参与方 / 资金账户 / 股票 PE） | 比赛 + `?competitionId` 校验（`assert_same_competition`，`:137`） |
| GET | `/api/companies/<int:pk>/impact` | `ImpactView`（`companies/views.py:223`） | `company:view`（`:228`） | 比赛 |
| POST | `/api/companies/recompute-all` | `RecomputeAllAPIView`（`companies/views.py:166`） | —（仅登录）+ 视图内 `role=="SUPER_ADMIN"`（`:181`） | 按 `competitionId` |
| GET | `/api/company-fields/<int:company_id>` | `CompanyFieldsView`（`company_fields/views.py:109`） | `company:view` | 比赛 |
| PUT | `/api/company-fields/<int:company_id>` | 同上 | `company:manage` | 比赛 |
| PUT | `/api/company-fields/<int:company_id>/<int:field_id>` | `CompanyFieldItemView`（`company_fields/views.py`） | `company:manage` | 比赛 |

⚠️ **路由顺序**：`companies/recompute-all` 追加在 `crud_urlpatterns` 之后仍然安全 —— `<int:pk>` 不会吞非数字段 `recompute-all`（`companies/urls.py:20-26` 的注释）。

⚠️ `company_fields/urls.py` **只有 2 条路由**，没有「多公司批量读」端点。前端 `companyFieldsApi`（`frontend/src/api/index.ts:231-239`）也只有单公司 `get` / `set`。

#### 1.2.8 合同（11 条路由，17 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/contract-types` | `ContractTypeCollectionAPIView`（`contracts/views.py:56`） | `contractType:view`（`:65`）；**`@no_competition_scope`**（`:64`）；支持 `updatedAfter` | 全局 |
| POST | `/api/contract-types` | 同上 | `contractType:manage`（`:93`）；`@no_competition_scope`（`:92`） | 全局 |
| GET | `/api/contract-types/<int:pk>` | `ContractTypeItemAPIView`（`contracts/views.py:101`） | `contractType:view`（`:107`）；`@no_competition_scope`（`:106`） | 全局 |
| PATCH | `/api/contract-types/<int:pk>` | 同上 | `contractType:manage`（`:113`）；`@no_competition_scope`（`:112`） | 全局 |
| DELETE | `/api/contract-types/<int:pk>` | 同上 | `contractType:manage`（`:122`）；`@no_competition_scope`（`:121`） | 全局 |
| POST | `/api/contracts/trial` | `ContractTrialAPIView`（`contracts/views.py:581`） | `contractType:manage`（`:592`） | 按公司（非超管仅限本比赛公司，`:609`） |
| GET | `/api/contracts` | `ContractCollectionAPIView`（`contracts/views.py:150`） | `contract:view`（`:155`）；支持 `updatedAfter` | 比赛 |
| POST | `/api/contracts` | 同上 | `contract:manage`（`:244`） | 视图内（`serializer.validated_data["competitionId"]` 与自身比赛比对，`:250`） |
| GET | `/api/contracts/<int:pk>` | `ContractItemAPIView`（`contracts/views.py:271`） | `contract:view`（`:276`） | 比赛 |
| PATCH | `/api/contracts/<int:pk>` | 同上 | `contract:manage`（`:283`）；**仅草稿可改输入** | 比赛 |
| DELETE | `/api/contracts/<int:pk>` | 同上 | `contract:manage`（`:308`） | 比赛（`assert_same_competition`，`:325`） |
| POST | `/api/contracts/<int:pk>/execute` | `ContractExecuteAPIView`（`contracts/views.py:353`） | —（仅登录）+ **视图内 `role in ("SUPER_ADMIN","COMPETITION_ADMIN")`**（`:361`） | 比赛 + 公司范围 |
| POST | `/api/contracts/<int:pk>/recalculate` | `ContractRecalculateAPIView`（`contracts/views.py:504`） | —（仅登录）+ **视图内 `role=="SUPER_ADMIN"`**（`:516`） | 比赛 |
| PATCH | `/api/contracts/<int:pk>/party-numbers` | `ContractPartyNumbersAPIView`（`contracts/views.py:452`） | —（仅登录）+ **视图内 role in (SUPER_ADMIN, COMPETITION_ADMIN)**（`:460`） | 比赛 |
| POST | `/api/contracts/<int:pk>/precheck` | `ContractPrecheckAPIView`（`contracts/views.py:567`） | `contract:audit`（`:572`） | 比赛 + 公司范围 |
| PATCH | `/api/contracts/<int:pk>/status` | `ContractStatusAPIView`（`contracts/views.py:677`） | `contract:manage`（`:682`）；**只允许 `TERMINATED`** | 比赛 |
| GET | `/api/contracts/<int:pk>/impact` | `ContractImpactAPIView`（`contracts/views.py:721`） | `contract:view`（`:726`） | 比赛 |

⚠️ **三条写操作靠角色硬编码而非权限 key**：`execute`（`:361`）、`recalculate`（`:516`）、`party-numbers`（`:460`）**都没有 `@require_permissions`**，改用 `role in (...)` 判定。只有 `precheck` 用 `contract:audit`（`:572`），`status` 用 `contract:manage`（`:682`）。见 §13 的 D-05。
⚠️ **路由顺序**：`contracts/trial` 声明在 `contracts/<int:pk>` 之前（`contracts/urls.py:47-48` 的注释）。`<int:pk>` 不匹配非数字，故即使顺序颠倒也安全；新系统不要依赖这个巧合。

#### 1.2.9 区域 / 消费需求（7 + 2 = 9 条路由，14 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/regions` | `CollectionView`（`regions/views.py:272`） | `data:region:view`；支持 `updatedAfter` | 比赛 |
| POST | `/api/regions` | 同上 | `data:region:edit` | 比赛（`create_competition_id`） |
| GET | `/api/regions/map-overview` | `MapOverviewView`（`regions/views.py:321`） | `data:region:view` | 比赛 |
| PUT | `/api/regions/by-name/<str:name>/overview-cards` | `SaveByNameView`（`regions/views.py:335`） | `data:region:edit` | 比赛 |
| GET | `/api/regions/<int:pk>` | `ItemView`（`regions/views.py:359`） | `data:region:view`（含 `companies`） | 比赛 |
| PATCH | `/api/regions/<int:pk>` | 同上 | `data:region:edit` | 比赛 |
| DELETE | `/api/regions/<int:pk>` | 同上 | `data:region:edit` | 比赛（`assert_same_competition`，`:396`） |
| GET | `/api/regions/<int:pk>/companies` | `CompaniesView`（`regions/views.py:417`） | `data:region:view` | 比赛 |
| GET | `/api/regions/<int:pk>/overview` | `OverviewView`（`regions/views.py:429`） | `data:region:view` | 比赛 |
| PUT | `/api/regions/<int:pk>/overview-cards` | `SaveOverviewCardsView`（`regions/views.py:442`） | `data:region:edit` | 比赛 |
| GET | `/api/consumer-demands` | `CollectionView`（`consumer_demands/views.py:151`） | `data:region:view`（常量 `:37`） | 比赛 |
| POST | `/api/consumer-demands` | 同上 | `data:region:edit`（常量 `:38`） | 比赛 |
| PATCH | `/api/consumer-demands/<int:pk>` | `ItemView`（`consumer_demands/views.py:187`） | `data:region:edit` | 比赛 |
| DELETE | `/api/consumer-demands/<int:pk>` | 同上 | `data:region:edit` | 比赛（`assert_same_competition`，`:220`） |

⚠️ **路由顺序**：`regions/map-overview` 与 `regions/by-name/<str:name>/...` 必须在 `<int:pk>` 之前（`regions/urls.py:37-42`）。
⚠️ **`consumer-demands` 没有独立权限 key**：复用 `data:region:view` / `data:region:edit`（`consumer_demands/views.py:37-38`）。`permissions.py:30-203` 的 19 个域里没有 `consumerDemand`。

#### 1.2.10 消息中心（10 条路由，12 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/messages/inbox` | `InboxView`（`messages/views.py:143`） | `message:view` | 当前用户（**分页**） |
| GET | `/api/messages/sent` | `SentView`（`messages/views.py:166`） | `message:view` | 当前用户（**裸数组**，上限 `_SENT_TAKE = 500`，`:65,175`） |
| GET | `/api/messages/unread-count` | `UnreadCountView`（`messages/views.py:182`） | `message:view` | 当前用户 |
| GET | `/api/messages/selectable-users` | `SelectableUsersView`（`messages/views.py:193`） | `message:view` | 同比赛（超管可传 `competitionId`） |
| POST | `/api/messages/read-all` | `ReadAllView`（`messages/views.py:243`） | **`message:view`** | 当前用户 |
| POST | `/api/messages/upload-image` | `UploadImageView`（`messages/views.py:256`） | `message:manage` | 全局（落 `/uploads/message-images/`） |
| GET | `/api/messages` | `CollectionView`（`messages/views.py:304`） | `message:view`（当前用户已发布，分页） | 当前用户 |
| POST | `/api/messages` | 同上 | `message:manage` | 比赛（超管可指定） |
| GET | `/api/messages/<int:pk>/read-status` | `ReadStatusView`（`messages/views.py:452`） | `message:view`（仅发布者可查） | 当前用户 |
| PATCH | `/api/messages/<int:pk>/read` | `MarkReadView`（`messages/views.py:225`） | `message:view` | 当前用户 |
| GET | `/api/messages/<int:pk>` | `ItemView`（`messages/views.py:406`） | `message:view`（仅发布者或收件人） | 当前用户 |
| DELETE | `/api/messages/<int:pk>` | 同上 | `message:manage`（仅发布者或超管） | 当前用户 |

⚠️ **路由顺序铁律**：6 个静态子路径（`inbox` / `sent` / `unread-count` / `selectable-users` / `read-all` / `upload-image`）必须排在 `<int:pk>` 之前（`messages/urls.py:36-38` 的注释）。若 `<int:pk>` 在前，`messages/inbox` 会被吞成 404。

#### 1.2.11 股票（14 条路由，19 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/stocks/pb-sources` | `PbSourcesView`（`stock/views.py:335`） | `stock:view`（`:340`） | 比赛 |
| GET | `/api/stocks/accounts/list` | `AccountListView`（`stock/views.py:481`） | `stock:view`（`:486`） | 比赛 |
| GET | `/api/stocks/accounts/overview` | `AccountOverviewView`（`stock/views.py:499`） | `stock:view`（`:504`）+ **视图内 `_is_super` 判定（非超管 403，`:506-507`）** | 比赛 |
| POST | `/api/stocks/accounts` | `AccountCollectionView`（`stock/views.py:591`） | `stock:edit`（`:596`） | 比赛 |
| GET | `/api/stocks/accounts/<int:pk>` | `AccountItemView`（`stock/views.py:658`） | `stock:view`（`:673`） | 比赛 |
| PATCH | `/api/stocks/accounts/<int:pk>` | 同上 | `stock:edit`（`:680`） | 比赛 |
| DELETE | `/api/stocks/accounts/<int:pk>` | 同上 | `stock:manage`（`:731`） | 比赛 |
| GET | `/api/stocks/accounts/<int:pk>/holdings` | `AccountHoldingsView`（`stock/views.py:743`） | `stock:view`（`:748`） | 比赛 |
| GET | `/api/stocks/orders/list` | `OrderListView`（`stock/views.py:790`） | `stock:view` | 比赛 |
| POST | `/api/stocks/orders` | `OrderCollectionView`（`stock/views.py:858`） | `stock:view`（下单；账户归属另校验） | 比赛 |
| DELETE | `/api/stocks/orders/<int:pk>` | `OrderItemView`（`stock/views.py:969`） | `stock:view`（撤单） | 比赛 |
| GET | `/api/stocks/holdings/list` | `HoldingListView`（`stock/views.py:1007`） | `stock:view` | 比赛 |
| POST | `/api/stocks/advance-round` | `AdvanceRoundView`（`stock/views.py:1066`） | `stock:manage`；`?competitionId=` | 比赛 |
| GET | `/api/stocks` | `CollectionView`（`stock/views.py:274`） | `stock:view`（`:279`）；支持 `updatedAfter` | 比赛 |
| POST | `/api/stocks` | 同上 | `stock:manage`（`:316`） | 比赛 |
| GET | `/api/stocks/<int:pk>/candles` | `CandlesView`（`stock/views.py:435`） | `stock:view`（`:444`）；**支持 `?afterRound=` 增量**（`:439,451-457`） | 比赛 |
| GET | `/api/stocks/<int:pk>` | `ItemView`（`stock/views.py:393`） | `stock:view`（`:401`） | 比赛 |
| PATCH | `/api/stocks/<int:pk>` | 同上 | `stock:manage`（`:409`） | 比赛 |
| DELETE | `/api/stocks/<int:pk>` | 同上 | `stock:manage`（`:418`） | 比赛 |

⚠️ **路由顺序**：`stocks/pb-sources`、`stocks/accounts/list`、`stocks/accounts/overview`、`stocks/orders/list`、`stocks/holdings/list`、`stocks/advance-round` 必须排在 `stocks/<int:pk>` 之前（`stock/urls.py:25` 的注释）。
⚠️ `/api/stocks/orders` **只有 POST**（没有 GET 列表）；列表走 `/api/stocks/orders/list`。

#### 1.2.12 文件（3 条路由，5 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| POST | `/api/files/upload` | `UploadView`（`files/views.py:168`） | `data:map:edit`（`:173`） | 全局 |
| PATCH | `/api/files/map-background/transform` | `MapBackgroundTransformView`（`files/views.py:308`） | `data:map:edit`（`:313`） | 按 `competitionId`（`_resolve_target`） |
| GET | `/api/files/map-background` | `MapBackgroundView`（`files/views.py:211`） | `data:map:view`（`:216`） | 同上 |
| POST | `/api/files/map-background` | 同上 | `data:map:edit`（`:231`） | 同上 |
| DELETE | `/api/files/map-background` | 同上 | `data:map:edit`（`:280`） | 同上 |

⚠️ 声明顺序：`files/map-background/transform` 在 `files/map-background` **之前**（`files/urls.py:4` 的注释）。

#### 1.2.13 审计 / 公告 / 控件包（1 + 2 + 2 = 5 条路由，10 个方法级端点）

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/audit-logs` | `AuditLogListView`（`audit/views.py:20`） | `account:manage`（`:25`） | 全局（按 `competitionId` 查询参数过滤） |
| GET | `/api/announcements` | `CollectionView`（`announcements/views.py:32`） | —（仅登录）；非超管仅见 `isActive=true`（`:40`） | 全局 |
| POST | `/api/announcements` | 同上 | —（仅登录）+ 视图内 SUPER_ADMIN（`:45`） | 全局 |
| GET | `/api/announcements/<int:pk>` | `ItemView`（`announcements/views.py:71`） | —（仅登录）；未启用公告对非超管 404（`:84`） | 全局 |
| PATCH | `/api/announcements/<int:pk>` | 同上 | —（仅登录）+ 视图内 SUPER_ADMIN（`:89`） | 全局 |
| DELETE | `/api/announcements/<int:pk>` | 同上 | —（仅登录）+ 视图内 SUPER_ADMIN（`:107`） | 全局 |
| GET | `/api/widget-packages` | `CollectionView`（`widget_packages/views.py:48`） | —（仅登录）；非超管仅见 `isActive=true`（`:55`） | 全局 |
| POST | `/api/widget-packages` | 同上 | —（仅登录）+ 视图内 SUPER_ADMIN（`:60`）；zip ≤ 5MB | 全局 |
| PATCH | `/api/widget-packages/<int:pk>` | `ItemView`（`widget_packages/views.py:174`） | —（仅登录）+ 视图内 SUPER_ADMIN（`:186`） | 全局 |
| DELETE | `/api/widget-packages/<int:pk>` | 同上 | —（仅登录）+ 视图内 SUPER_ADMIN（`:197`） | 全局 |

#### 1.2.14 比赛准备（5 条路由，5 个方法级端点）

`apps/preparation/` 是 master 上的**建包（比赛准备）app**，7 个文件：`archive.py` / `plan.py` / `checklist.py` / `views.py` / `urls.py` / `apps.py` / `__init__.py`。路由声明在 `preparation/urls.py:23-36`。

| 方法 | 路径 | 视图（文件:行） | 权限 | 域 |
| --- | --- | --- | --- | --- |
| GET | `/api/preparations/plan` | `PreparationPlanAPIView`（`preparation/views.py:144`） | `competition:manage`（`_MANAGE_PERM`，`:42`；标注在 `:150`） | 按 `competitionId` |
| GET | `/api/preparations/plan/export` | `PreparationExportAPIView`（`preparation/views.py:167`） | `competition:manage`（`:177`） | 同上 |
| GET | `/api/preparations/scopes` | `PreparationScopesAPIView`（`preparation/views.py:157`） | `competition:manage`（`:162`） | 全局 |
| GET | `/api/preparations/archive/export` | `PreparationArchiveExportAPIView`（`preparation/views.py:198`） | `competition:manage`（`:203`） | 按 `competitionId` |
| POST | `/api/preparations/archive/import` | `PreparationArchiveImportAPIView`（`preparation/views.py:217`） | `competition:manage`（`:233`） | 按 `competitionId` |

⚠️ **两个导出端点是「附件下载」，不走统一信封**（见 §8.4）。前端用 `responseType: "blob"` 消费 → 撞上 §13 的 D-02。
⚠️ **必须复刻 `_IgnoreFormatParamNegotiation`**（`preparation/views.py:45-63`）：DRF 默认把查询参数 `format` 当响应格式后缀，取值 `markdown` 在渲染器里不存在 → **默认协商直接抛 404**（源码注释 `:48-52` 记录了这个现象）。重写时若省掉这个覆盖，`GET /api/preparations/plan/export?format=markdown` 会 404。
⚠️ `plan/export` 支持 `?format=markdown|json`（`_FORMATS`，`:75-78`）；`archive/export` 支持 `?scope=`（`_resolve_scope`，`:125`）；`archive/import` 的默认 `dryRun=true`（只预览不落库，`:245`）。

#### 1.2.15 静态托管（2 条 `re_path`，非 DRF 视图）

| 方法 | 路径 | 视图 | 鉴权 | 说明 |
| --- | --- | --- | --- | --- |
| GET | `/uploads/**` | `django.views.static.serve` | **无** | `document_root = settings.MEDIA_ROOT`（`settings.py:465`） |
| GET | `/static/**` | `django.views.static.serve` | **无** | `document_root = settings.STATIC_ROOT`（`settings.py:461`） |

### 1.3 日志查看器应用的 9 条路由（**独立服务，不在 `/api` 前缀下**）

`backend/logviewer/logviewer/urls.py`（35 行）是**另一个 Django 项目**，有自己的 `settings` / `ROOT_URLCONF`，主后端的解析器不含它。前端只从 `/api/version` 拿到 `log_viewer_url` 后**打开新标签页**，不走 axios。

| 行 | 方法 | 路径 | 视图 | 说明 |
| --- | --- | --- | --- | --- |
| `:16` | GET | `/` | `views.index` | 防直连网关入口（需 `?token=`） |
| `:17` | GET | `/api/health` | `health` | `{"status":"ok"}`，`@require_GET` |
| `:18` | GET | `/api/csrf/` | `views.csrf_cookie` | — |
| `:19` | GET | `/api/auth/whoami` | `views.whoami` | — |
| `:20` | POST | `/api/auth/login` | `views.login_view` | — |
| `:21` | POST | `/api/auth/logout` | `views.logout_view` | — |
| `:22` | GET | `/api/logs/files` | `views.log_files` | — |
| `:23` | GET | `/api/logs` | `views.logs_view` | — |
| `:30` | GET | `/static/**` | `static_serve` | `document_root = BASE_DIR/static` |

---

## 2. 统一响应信封

### 2.1 渲染规则（`apps/common/response.py:19-46`）

`JSONRenderer.render()` 在全局生效（`settings.py:407-409` 的 `DEFAULT_RENDERER_CLASSES`）：

| 视图返回 | 渲染结果 |
| --- | --- |
| `dict` / `list` / `None`（未同时含 `code`+`message`+`data` 三键） | 包成 `{code:0, message:"成功", data:<原值>}` |
| 已同时含 `code`+`message`+`data` 三键的 dict | **原样返回，不二次包装** |
| 异常处理器构造的 `error(...)` | 已包装，原样 |

**判定必须三键齐全**（`response.py:59-71` 的 `_is_wrapped`）。源码注释记录了这个坑：只判 `"code" in data` 会误伤「业务字段恰好叫 `code`」的单对象响应（如产业类型编号、股票代码），使前端拦截器拿到 `code=<业务值>` 而误报「请求失败」。

### 2.2 形态一：成功（对象）

`GET /api/health`（视图返回 `{"status": "ok"}`，`auth/views.py:73`）：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "status": "ok"
  }
}
```

### 2.3 形态二：成功（列表 + 分页）

`GET /api/materials?page=1&pageSize=2`（`base_crud.py:127-133` → `pagination.py:41-48`）：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "items": [
      { "id": 12, "name": "钢材", "competitionId": 3, "updatedAt": "2025-03-02T08:11:04.512Z" },
      { "id": 13, "name": "铝材", "competitionId": 3, "updatedAt": "2025-03-02T08:12:31.090Z" }
    ],
    "total": 37,
    "page": 1,
    "pageSize": 2
  }
}
```

**注意**：分页包装在 `data` 里，不在顶层。前端默认会把 `{items,total,page,pageSize}` **降维成裸数组**（`request.ts:312-324` 的 `normalizeListResponse`）；只有显式传 `normalize:false` 的调用（`auditApi.list`，`api/index.ts:506-510`）才能拿到 `total`。

### 2.4 形态三：成功（增量列表）

`GET /api/companies?updatedAfter=2025-03-02T08:00:00Z&previousIds=1,2,9`（`companies/views.py:79-89` → `sync.py:48-76`）：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "items": [{ "id": 3, "name": "甲公司", "updatedAt": "2025-03-02T08:31:00.000Z" }],
    "total": 1,
    "deletedIds": [9],
    "serverTime": "2025-03-02T08:32:10.482913Z",
    "incremental": true
  }
}
```

不带 `previousIds` 时字段换成 `existingIds`（当前全部 id）：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "items": [],
    "total": 0,
    "existingIds": [1, 2, 3],
    "serverTime": "2025-03-02T08:32:10.482913Z",
    "incremental": true
  }
}
```

⚠️ **`total` 语义**：`build_incremental_result` 的 `total` 是**本次变更条数**（调用方普遍传 `total=len(items)`），不是全表总数（`sync.py:65,72`）。

### 2.5 形态四：错误

`GET /api/materials/999999` → `_get_object` 抛 `BusinessError("请求的资源不存在", code=404, status_code=404)`（`base_crud.py:77`）→ `exceptions.py:58-59` → `_wrap(404, ...)`（`exceptions.py:68-71`）：

```json
{
  "code": 404,
  "message": "请求的资源不存在",
  "data": null
}
```

HTTP 状态码由 `_http_status(code)` 决定（`exceptions.py:74-78`）：`100 <= code < 600` 直接用该值，否则回退 `400`。

### 2.6 形态五：两种 429，形状不同

**（a）登录限流**（`common/middleware.py:252-273`）—— 由**中间件**直接返回 `JsonResponse`，不经 DRF 渲染器：

```json
{
  "code": 429,
  "message": "登录尝试过于频繁，请 15 分钟后再试",
  "data": null
}
```

触发条件：同一 `(客户端IP, 请求体 username)` 组合 **10 次失败 / 5 分钟** → 锁定 **15 分钟**（`middleware.py:206-208`）；成功登录清零（`:241-242`）。

**（b）按角色流量限制**（`common/rate_limit.py:149-156`）—— 同样是中间件 `JsonResponse`：

```json
{
  "code": 429,
  "message": "请求过于频繁，请稍后重试",
  "retryAfter": 12
}
```

⚠️ **（b）没有 `data` 键**，多一个 `retryAfter`。默认配额（`rate_limit.py:22-38`）：`SUPER_ADMIN` **不限制**、`COMPETITION_ADMIN` 300 次/60s、`PLAYER` 100 次/60s。
⚠️ **（b）在 master 上实际不会触发** —— 见 §9.6 与 §13 的 D-03（中间件跑在 DRF 认证之前，`request.user` 恒为 `AnonymousUser`）。

### 2.7 形态六：400 校验错误

DRF `ValidationError` 经 `_drf_message`（`exceptions.py:108-109`）取**首个**字段错误：

```json
{
  "code": 400,
  "message": "该字段是必填项。",
  "data": null
}
```

多字段同时失败时**只返回第一条**（`_first_validation` 递归取第一个字符串，`exceptions.py:115-133`）。

### 2.8 大数安全转换（`apps/common/renderers.py:21-40`）

渲染前递归扫描（`response.py:30` 调用），**任何加壳接口都适用**：

| 输入类型 | 出站形态 | 依据 |
| --- | --- | --- |
| `bool` / `None` | 原样 | `renderers.py:23-24` |
| `int`，`abs(v) > 2^53` | **字符串** | `renderers.py:25-27` |
| `int`，`abs(v) <= 2^53` | 数字（`id`、`version` 等不受影响） | 同上 |
| `Decimal`，整数值 | 转 `int` 后按上一条判定 | `renderers.py:28-33` |
| `Decimal`，非整数值 | `format(obj, "f")` → **字符串** | `renderers.py:33` |
| `Decimal`，非有限（`NaN`/`Inf`） | `null` | `renderers.py:29-30` |
| `float` | **原样返回**（无非有限兜底） | `renderers.py:34-35` |
| `list` / `dict` | 递归 | `renderers.py:36-39` |

⚠️ 背景（`renderers.py:4-6`）：系统需支持 10^23 级金额，而 JS `Number` 精确整数上限 2^53 ≈ 9.007×10^15。**重写铁律**：大整数与小数金额都是 **JSON string**，前端必须按字符串处理。
⚠️ `float` 分支没有兜底：若数据里出现 `inf` / `nan`，DRF 的 `JSONRenderer` 用 `allow_nan = api_settings.STRICT_JSON`（默认 `True`）→ `json.dumps` 抛 `ValueError` → **整个端点 500**。
⚠️ 附件下载响应**不经渲染器**，因此**不做大数转换**（见 §8.4）。

### 2.9 响应头（`apps/common/middleware.py:125-145`）

`SecurityHeadersMiddleware.process_response` 对**除 `/admin*` 之外**的全部响应设置：

| 头 | 值 |
| --- | --- |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Cross-Origin-Resource-Policy` | `/uploads*` → `cross-origin`；其余 → `same-origin` |

⚠️ `/admin*` **提前 return，不加任何头**（`middleware.py:132-133`）。原因写在注释里：`form-action 'none'` 会拦掉后台登录表单、`default-src 'none'` 会禁掉后台样式与脚本。

### 2.10 前端如何消费（`frontend/src/api/request.ts`，867 行）

| 行为 | 实现 | 行 |
| --- | --- | --- |
| baseURL | `getApiBaseUrl() + "/api"` | `:38` |
| 超时 | 全局 `15000` ms | `:21-23` |
| 鉴权头 | 有 token 时加 `Authorization: Bearer <token>` | `:34-37` |
| 成功解包 | `if (res.code !== 0) → 弹错并 reject；否则 return res.data` | `:88-95` |
| 列表降维 | `normalizeListResponse`：`{items,total}` → `items`；裸数组与详情对象原样 | `:312-324` |
| 特殊豁免 | `/maps/full`、`/company-fields/:id` 不做降维 | `:300-302,314,516` |
| 401 | 清 token、清缓存、跳 `#/login`、派发 `auth:kicked`；有「迟到 401」判定与改密窗口屏蔽 | `:108-149` |
| 错误提示 | 优先用 `response.data.message`，否则按状态码查中文表 | `:45-72` |

⚠️ **前端的第一条判定是 `if (res.code !== 0)`**（`:90`），**没有**「响应体不是信封」的分支。因此：
1. 任何 2xx 响应**必须有 `code` 字段**，且成功时**必须为 0**；
2. 若某端点的 2xx 体里 `code` 缺失（例如二进制 / 附件），`undefined !== 0` 为真 → 前端弹「请求失败」并 reject（即使 HTTP 200）。**这正是 §13 D-02 的成因。**

---

## 3. 分页与列表形状

来源：`apps/common/pagination.py`（48 行）。

| 项 | 值 | 依据 |
| --- | --- | --- |
| 查询参数 · 页码 | `page` | `pagination.py:22` |
| 查询参数 · 每页条数 | `pageSize`（**camelCase，不是 `page_size`**） | `pagination.py:26` |
| 默认 `page` | `1` | `pagination.py:10` |
| 默认 `pageSize` | `50` | `pagination.py:11` |
| `pageSize` 上限 | `200`（硬约束，注释说明「防止 DoS 全表扫描」） | `pagination.py:9,34-35` |
| 非法值处理 | 非整数 / `page < 1` / `pageSize < 1` → 回退默认；`pageSize > 200` → 截断为 200 | `pagination.py:21-35` |
| 偏移量 | `skip = (page - 1) * page_size` | `pagination.py:37` |
| 返回结构 | `{items, total, page, pageSize}` | `pagination.py:41-48` |
| DRF 内置分页 | `DEFAULT_PAGINATION_CLASS = None`（有意关闭，`PAGE_SIZE=50` 仅作后备） | `settings.py:405-406` |

**调用 `parse_pagination` 的 12 处（覆盖 23 个端点）**：

| 端点 / 模块 | 位置 |
| --- | --- |
| 通用 CRUD 列表（13 个资源） | `base_crud.py:130` |
| `GET /api/competitions` | `competitions/views.py:95` |
| `GET /api/competitions/:cid/fiscal-years` | `competitions/views.py:173` |
| `GET /api/users` | `users/views.py:64` |
| `GET /api/messages/inbox` | `messages/views.py:149` |
| `GET /api/messages`（当前用户已发布列表） | `messages/views.py:314` |
| `GET /api/stocks` | `stock/views.py:306`（带 `updatedAfter` 时改走增量分支） |
| `GET /api/companies` | `companies/views.py:91`（同上） |
| `GET /api/contracts`（无公司范围分支） | `contracts/views.py:222` |
| `GET /api/contracts`（有公司范围、内存过滤分支） | `contracts/views.py:239` |
| `GET /api/regions` | `regions/views.py:300`（同上） |
| `GET /api/audit-logs` | `audit/views.py:51` |

⚠️ `GET /api/contracts` **有两处** `parse_pagination`：是否走公司范围过滤（`_needs_scope_filter`）决定取哪一条分支；两条都返回标准分页对象，**对外形状一致**。

**第三种列表形状：`{items, total}` 但无 `page` / `pageSize`**

`GET /api/contract-types`（`contracts/views.py:89-90`）：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "items": [{ "id": 1, "code": "SALE", "enabled": true }],
    "total": 1
  }
}
```

它**不接受 `page` / `pageSize`**（不调 `parse_pagination`），一次返回全表。全仓库只有这一处（`grep '"items": items'` 仅命中 `contracts/views.py:90` 与 `pagination.py:44`）。
前端 `normalizeListResponse` 的判定是 `Array.isArray(rec.items) && "total" in rec` → 它**会**被降维成裸数组，所以页面正常。重写时**不能删掉 `items` 或 `total` 键**。

**真正的裸数组端点**（顶层是 JSON 数组）：

| 端点 | 依据 |
| --- | --- |
| `GET /api/announcements` | `announcements/views.py:42` |
| `GET /api/widget-packages` | `widget_packages/views.py:57` |
| `GET /api/industry-types` | `industry_types/views.py:373` |
| `GET /api/messages/sent` | `messages/views.py:179`（被 `[:_SENT_TAKE]` 截断，`_SENT_TAKE = 500`，`:65,175`） |
| `GET /api/messages/selectable-users` | `messages/views.py:210-220` |
| `GET /api/regions/map-overview` | `regions/views.py:330-331`（`_get_map_overview` 返回 `list`） |
| `GET /api/stocks/accounts/list` | `stock/views.py:465,471` |
| `GET /api/stocks/accounts/overview` | `stock/views.py:485,554` |
| `GET /api/stocks/orders/list` | `stock/views.py:765,786` |
| `GET /api/stocks/holdings/list` | `stock/views.py:982,996` |

**对象形状（既不是裸数组、也不是分页壳）**：

| 端点 | 形状 | 依据 |
| --- | --- | --- |
| `GET /api/stocks/pb-sources` | `{"companies": [...], "regionCards": [...]}` | `stock/views.py:334,380` |
| `GET /api/stocks/<pk>/candles` | `{"stock": {...}, "candles": [...]}` | `stock/views.py:477` |

→ 两者**不会**被 `normalizeListResponse` 降维（没有 `items` 键），前端拿到的是对象。**重写时不要"顺手"改成数组。**

**形状需要注意的一对**：

| 对比 | 事实 | 影响 |
| --- | --- | --- |
| `/api/messages/inbox`（**分页对象**，`messages/views.py:149-163`） vs `/api/messages/sent`（**裸数组**，`:170-179`） | 同一个「消息」模块内两种形状 | 前端**只是碰巧**靠 `normalizeListResponse` 把两者都吃下 |
| `/api/companies`、`/api/contracts`（分页对象） vs 前端注释说的「裸数组」 | `companies/views.py:94`、`contracts/views.py:226,243` 都返回 `paginated_response` | 前端 `request.ts` 内的注释不准确；**判断依据永远是服务端形状** |

→ **重写时不要「顺手统一」**：给 `announcements` / `widget-packages` / `industry-types` / `messages/sent` 加分页壳，或给 `contract-types` 去掉 `items`/`total`，都会改变这些页面的契约。

---

## 4. 错误表达

### 4.1 响应体里**没有**机器码

> **这是 master 上最容易做错的一条。**
> `response.py:54-56` 的 `error()` 只有三个参数 `(code, message, data)`，**没有** `error_code`；
> `Select-String -Path .baseline-master/backend -Include *.py -Pattern 'errorCode' -Recurse` → **0 命中**；
> `exceptions.py:65` 只做 `_wrap(response.status_code, message)`，**丢弃** DRF 异常自带的 code。

**结论**：客户端**只能靠 HTTP 状态码 + `message` 文案**区分错误语义。三种 401（会话过期 / 被顶号 / 未改初始密码）返回**同一个** `code` 字段值 `401`，只能靠中文 message 区分。

### 4.2 业务码字面量（`BusinessError(message, code=..., status_code=...)`）

228 个调用点，**7 个**不同 `code` 值（脚本 C 实测）：

| code | 次数 | 语义 | 典型 message |
| --- | --- | --- | --- |
| `400` | 122 | 入参 / 状态机 / 业务前置条件不满足 | 「用户名和密码不能为空」「新密码长度不能少于 8 位」「该数据不属于当前比赛，无法删除（可能属于其它比赛）」 |
| `401` | 1 | 登录失败（用户名或密码错误） | 「用户名或密码错误」（`auth/views.py:150`） |
| `403` | 36 | 角色 / 权限 / 比赛上下文不足 | 「仅超级管理员可执行全量重算」「该账号已被禁用，请联系管理员」「仅超级管理员可查看账户总览」 |
| `404` | 53 | 资源不存在（**含跨比赛越权读的伪装 404**） | 「请求的资源不存在」「公告不存在」 |
| `409` | 14 | 冲突（唯一性、名称重复、乐观锁） | 「名称已存在」「比赛名称已存在」「该财年已存在」「数据冲突，请刷新后重试」 |
| `500` | 1 | 不可恢复错误 | 「解压失败」（`widget_packages/views.py:108`） |
| `503` | 1 | 依赖不可用 | 见 `stock/views.py`（`Select-String -Pattern 'status_code=503'`） |

**全部 228 个调用点的 `code` 与 `status_code` 一一相等** → **业务码即 HTTP 状态码**。

### 4.3 DRF 内部 code（**不出站**，但决定 message）

`apps/auth/authentication.py`（156 行）给 `AuthenticationFailed` 传了机器码，**但这些 code 只用于日志与异常对象，不写进响应体**：

| DRF `code` | 行 | 抛出的 message | 出站 HTTP |
| --- | --- | --- | --- |
| `expired` | `authentication.py:100-102` | 「登录已过期，请重新登录」 | 401 |
| `invalid_user` | `authentication.py:106-108` | 「登录已过期，请重新登录」 | 401 |
| `token_version_mismatch` | `authentication.py:112-114` | 「账号已在其他设备登录」 | 401 |
| `must_change_password` | `authentication.py:120-122` | 「账号需先修改初始密码」 | 401 |
| （无凭据时 DRF `NotAuthenticated` 的默认 code `not_authenticated`） | DRF 内置 | 「登录已过期，请重新登录」 | 401 |
| `field_write_conflict` | `exceptions.py:21-26` | 「数据冲突，请刷新后重试」 | 409 |

⚠️ `FieldWriteConflictException` **确实在用** —— 它是 `PUT /api/company-fields/<cid>` 的**乐观锁**出口（`company_fields/views.py:99`），见 §8.5。

### 4.4 DRF 默认异常 → 中文 message 映射（`exceptions.py:81-112`）

| HTTP | message | 规则 |
| --- | --- | --- |
| 400 | 「请求参数错误，请检查输入」 | 取 DRF 校验结构的**首个**字面量消息；无则用兜底文案 |
| 401 | 见 §4.3 | **按异常类型**判定：`isinstance(exc, NotAuthenticated)` → 「登录已过期，请重新登录」；`AuthenticationFailed` 且 `detail` 是字符串 → **原样返回** |
| 403 | 「没有权限执行此操作」 | **固定文案**（`PermissionDenied` 的自定义 message 被丢弃） |
| 404 | 「请求的资源不存在」 | 固定文案 |
| 409 | 「数据冲突，请刷新后重试」 | 固定文案 |
| 422 | 「请求参数校验失败」 | 取首个字段错误 |
| 未捕获异常 | 「服务器内部错误，请稍后重试」 | `exceptions.py:52-55`：不暴露堆栈，同时写 `logger.error` |

✅ 401 分支用的是**异常类型比对**（`exceptions.py:93-94`），源码注释（`:89-92`）记录了这个修复：原写法比对英文 detail 字符串，在 `USE_I18N=True` + `LANGUAGE_CODE="zh-hans"`（`settings.py:453,455`）下 DRF 抛出的已是中文，比对恒假 → 中文原文直接泄露给用户。

### 4.5 实际会出站的 HTTP 状态码全集

`200`（全部成功；**没有 201**）· `400` · `401` · `403` · `404` · `409` · `429` · `500` · `503`

**产生非 DRF 渲染器响应的地方**（4 类）：
1. `middleware.py:269-272` 的登录限流 429（`JsonResponse`）；
2. `rate_limit.py:149-156` 的角色限流 429（`JsonResponse`）；
3. `preparation/views.py:118` 的**附件下载** `HttpResponse`（见 §8.4）；
4. `backend_gate.py:115,124,127` 的 302（`HttpResponseRedirect`，仅 `/admin/` 前缀）。

---

## 5. 通用 CRUD 基类（`apps/common/base_crud.py`，249 行）

### 5.1 类结构

| 类 | 行 | 职责 | 方法 |
| --- | --- | --- | --- |
| `CrudPermission` | 27-43 | 按 HTTP 方法读 `view_permission`(GET) / `edit_permission`(非 GET) | `has_permission` |
| `CrudMixin` | 50-120 | 查询 / 取对象 / 冲突检测 / 删除影响 | 见 §5.2 |
| `CrudListView` | 124-133 | 列表 + 分页 | `get` |
| `CrudCreateView` | 136-149 | 创建 | `post` |
| `CrudDetailView` | 152-157 | 详情 | `get` |
| `CrudUpdateView` | 160-190 | PUT / PATCH | `put` / `patch` / `_update` |
| `CrudDeleteView` | 193-199 | 删除 | `delete` |
| `CrudImpactView` | 202-207 | 删除影响 | `get` |
| `make_collection_view` | 211-213 | 组合 list + create → `CollectionAPIView` | — |
| `make_item_view` | 216-218 | 组合 detail + update + delete → `ItemAPIView` | — |
| `make_impact_item_view` | 221-223 | 直接返回影响视图 | — |
| `crud_urlpatterns` | 227-249 | 生成 2~3 条路由 | — |

`_PERM_CLASSES = (IsAuthenticated, CrudPermission)`（`base_crud.py:46`）。

### 5.2 钩子方法（子类可覆盖）

| 钩子 | 签名 | 默认行为 | 被调用的时机 |
| --- | --- | --- | --- |
| `get_queryset` | `(self, request) -> QuerySet` | `model.objects.all()` 经 `apply_competition_scope(qs, user, request.query_params.get("competitionId"))` | 仅列表 |
| `filter_queryset` | `(self, qs, params) -> QuerySet` | 恒等返回 `qs` | 列表，`get_queryset` 之后 |
| `serialize` | `(self, instance, many=False)` | `serializer_class(instance, many=many).data` | 所有要序列化实例的路径 |
| `_get_object` | `(self, pk, request) -> Model` | 见 §5.3 | 详情 / 更新 / 删除 / 影响 |
| `_check_conflict` | `(self, data, exclude_id=None)` | 按 `unique_fields` 查重，命中抛 `BusinessError("名称已存在", 409)` | 创建 / 更新 |
| `get_delete_impact` | `(self, instance) -> dict` | `{"name": str(instance), "children": []}` | 影响端点 |
| `_camel_to_snake` | static `(name) -> str` | `regionId → region_id` | 冲突检测的字段名映射 |

类属性：`model` / `serializer_class` / `view_permission` / `edit_permission` / `unique_fields`（camelCase 列表）/ `order_by`（默认 `-updated_at`）。

### 5.3 调用顺序（重写时最容易做漏的部分）

**列表 `GET /<res>`**（`base_crud.py:127-133`）：

```
CrudPermission.has_permission(GET → view_permission)
→ get_queryset(request)                       # 含 apply_competition_scope
→ filter_queryset(qs, request.query_params)   # 子类扩展点
→ parse_pagination(request.query_params) → (page, page_size, skip)
→ total = qs.count()
→ items = serialize(qs.order_by(order_by)[skip : skip+page_size], many=True)
→ Response(paginated_response(items, total, page, page_size))
```

顺序细节：`filter_queryset` 在 `parse_pagination` **之前**；`order_by` 只在切片时应用（`count()` 用未排序的 queryset）。

**创建 `POST /<res>`**（`base_crud.py:139-149`）：

```
CrudPermission.has_permission(POST → edit_permission)
→ serializer = serializer_class(data=request.data); serializer.is_valid(raise_exception=True)
→ data = dict(serializer.validated_data)
→ data["competitionId"] = create_competition_id(request.user, data)   # 非超管强制归属自身比赛
→ self._check_conflict(data)                                         # 唯一性 → 409
→ instance = serializer.create(data)                                  # 用 serializer.create，不是 .save()
→ Response(self.serialize(instance))                                  # 200，不是 201
```

⚠️ **顺序不可换**：`create_competition_id` 必须在 `_check_conflict` 之前 —— 唯一元组含 `competitionId`，否则跨比赛重名检测失效。

**详情 `GET /<res>/<pk>`**（`base_crud.py:155-157`）：`_get_object(pk, request)` → `serialize(instance)`。

`_get_object` 的越权语义（`base_crud.py:73-83`）：

```
model.objects.get(pk=pk)  --DoesNotExist--> BusinessError("请求的资源不存在", 404, 404)   # :77
if user.role != "SUPER_ADMIN"
   and instance.competition_id is not None
   and instance.competition_id != user.competition_id:
        BusinessError("请求的资源不存在", 404, 404)     # :82 伪装成 404，不暴露资源存在性
```

**更新 `PUT` / `PATCH /<res>/<pk>`**（`base_crud.py:169-190`）：

```
_get_object(pk, request)                        # 先做比赛域校验
serializer = serializer_class(instance, data=request.data, partial=(PATCH))
serializer.is_valid(raise_exception=True)
data = {k: v for k, v in validated_data.items()
        if k not in ("competitionId", "competition_id")}    # 禁止跨比赛迁移：静默丢弃，不报错
conflict_data = { 每个 unique_field: 实例当前值 }            # PATCH 时用现值补齐唯一元组
for k, v in data.items(): if k in conflict_data: conflict_data[k] = v
conflict_data["competitionId"] = instance.competition_id
_check_conflict(conflict_data, exclude_id=pk)                # → 409
serializer.update(instance, data)                            # 用 serializer.update，不是 .save()
Response(serialize(instance))
```

⚠️ `competitionId` 是**静默丢弃**而非报错 → 前端的「跨比赛迁移」表现为「提交成功但没变」。
⚠️ 冲突检测只在**唯一元组完整**时生效：`_check_conflict` 开头 `if data.get(f) is None: return`（`base_crud.py:109-110`）。这是为了让「地图节点拖动只发 x/y」不被误判成重名 —— **重写时不能省这个早退**。

**删除 `DELETE /<res>/<pk>`**（`base_crud.py:196-199`）：`_get_object` → `instance.delete()` → `Response({"ok": True})`。

⚠️ **`?competitionId=` 对基类删除无效**：`CrudDeleteView.delete` 完全不读 `request.query_params`。前端的 `materialsApi.remove(id, competitionId)`（`api/index.ts:83-84`）传的 `competitionId` 在基类 CRUD 上是**空转**；隔离完全靠 `_get_object` 的 404 伪装。
反例：`DELETE /api/companies/<pk>` **会**读 `?competitionId=` 并走 `assert_same_competition`（`companies/views.py:130-137`），返回 400「该数据不属于当前比赛，无法删除（可能属于其它比赛）」。**同一个 UI 交互，两种语义。**

**影响 `GET /<res>/<pk>/impact`**（`base_crud.py:205-207`）：`_get_object` → `get_delete_impact(instance)`。

### 5.4 路由生成（`base_crud.py:227-249`）

```python
path(resource, collection_view.as_view())                       # GET/POST
path(f"{resource}/<int:pk>", item_view.as_view())               # GET/PUT/PATCH/DELETE
path(f"{resource}/<int:pk>/impact", impact_view.as_view())      # 仅当 impact_view 非 None
```

`impact_view` 是**可选参数**：`infrastructures` / `warehouses` / `production-lines` 的 `urls.py` 没传，所以**没有** `impact` 路由 —— 而前端调了，见 §11.1。

---

## 6. 比赛域隔离：`scope.py` 与 `guards.py` 的分工

master 上这两个文件是**两个独立机制**：

| 文件 | 行数 | 提供什么 | 何时生效 |
| --- | --- | --- | --- |
| `apps/common/scope.py` | 16 | `assert_same_competition(entity_cid, requested_cid)` | **只在调用方显式调用时**生效 |
| `apps/common/guards.py` | 195 | `require_permissions` / `no_competition_scope` / `CompetitionScopePermission` / `create_competition_id` / `strip_competition_fields` / `_normalize_competition_id` / `apply_competition_scope` | 见下逐条 |

### 6.1 `apply_competition_scope(queryset, user, competition_id)`

（`guards.py:179-195`）

| 角色 | 传入 `competitionId` | 结果 |
| --- | --- | --- |
| `SUPER_ADMIN` | 归一化后非空 | `queryset.filter(competition_id=cid)` |
| `SUPER_ADMIN` | 空 / 非法 | **不过滤**（看全部比赛） |
| 其它角色 | 任何值 | **强制** `filter(competition_id = user.competition_id)`；**忽略前端传入值** |
| 其它角色 | 且 `user.competition_id` 为空 | **`queryset.none()`** —— 返回空集，**不是报错** |

归一化函数 `_normalize_competition_id`（`guards.py:153-176`）把 `None` / `bool` / `""` / `"null"` / 不可转 int 的值统一变 `None`，避免 `filter(competition_id="null")` 抛 500（注释 `:156-159` 说明这是防御性修复）。
→ 前端在「未选比赛」时传 `competitionId="null"` 是**被支持的合法输入**（账号页用 `usersApi.list({ competitionId: "null" })` 拉系统账号）。

**调用点（10 处，覆盖 8 个端点）**：

| 位置 | 覆盖 |
| --- | --- |
| `base_crud.py:64` | 13 个基础 / 地图资源的**列表** GET（14 条路由） |
| `maps/views.py:51-54` | `GET /api/maps/full`（4 个 queryset 各调一次） |
| `companies/views.py:53` | `GET /api/companies` |
| `contracts/views.py:158` | `GET /api/contracts` |
| `regions/views.py:279` | `GET /api/regions` |
| `stock/views.py:272` | `GET /api/stocks` |
| `consumer_demands/views.py:111` | `GET /api/consumer-demands` |

### 6.2 `create_competition_id(user, data)`

（`guards.py:130-145`）

| 角色 | 行为 |
| --- | --- |
| `SUPER_ADMIN` | 取 `data["competitionId"]`；**为空则抛 `PermissionDenied("缺少比赛上下文，请先选择比赛")`**（`:140`） |
| 其它角色 | **一律**返回 `user.competition_id`，**忽略请求体**；为空则抛 `PermissionDenied("当前账号未归属任何比赛")`（`:144`） |

**调用点（9 处）**：`base_crud.py:146`（13 个资源的 POST）、`companies/views.py:104`、`consumer_demands/views.py:131`、`parts/views.py:112`、`products/views.py:114`、`regions/views.py:313`、`stock/views.py:311`、`vehicles/views.py:119`。

⚠️ **抛的是 DRF `PermissionDenied`**，经异常处理器变成 **403 + 固定文案「没有权限执行此操作」**（`exceptions.py:99-100` 丢弃自定义 message）。所以真实用户看不到「缺少比赛上下文，请先选择比赛」这句话。
⚠️ **合同创建是特例**：`POST /api/contracts` **不用** `create_competition_id`，而是自取 `serializer.validated_data["competitionId"]`，非超管与自身不符时抛 `BusinessError("无权限在该比赛下创建合同", 403)`（`contracts/views.py:244-254`）—— 文案能透出（走 `BusinessError`，不是 `PermissionDenied`）。

### 6.3 `strip_competition_fields(data)`

（`guards.py:148-150`）从字典里剔除 `competitionId` / `competition_id`。
**master 上没有任何调用点**（`base_crud.py:174-177` 是内联实现的同一逻辑）。

### 6.4 `CompetitionScopePermission` 的挂载方式与实际生效范围

**它确实被挂载了**，两道证据：

1. `settings.py:397-404`：

```python
"DEFAULT_PERMISSION_CLASSES": (
    "rest_framework.permissions.IsAuthenticated",
    # 比赛域全局兜底：非超管的写操作必须有比赛上下文 ...
    "apps.common.guards.CompetitionScopePermission",
),
```

2. DRF 把这份默认值**绑定在 `APIView` 类本身上**（导入期求值）。脚本 B 实测打印：

```
APIView.permission_classes = ('IsAuthenticated', 'CompetitionScopePermission')
```

**它的行为**（`guards.py:105-127`）：

| 条件 | 结果 |
| --- | --- |
| 方法上标了 `@no_competition_scope`（`guards.py:39-43`） | 放行 |
| 类属性 `_no_competition_scope_class = True` | 放行 |
| `user.role == "SUPER_ADMIN"` | 放行 |
| 写方法（POST/PUT/PATCH/DELETE）且 `body.competitionId is None` 且 `user.competition_id is None` | `PermissionDenied("缺少比赛上下文，请先选择比赛")` |
| **其它情况（含所有 GET）** | 放行 —— **它不做任何 queryset 过滤** |

**它是否真的在跑？—— 结论：121 条 `/api/*` 路由里，没有一条会走到它。**

DRF 的解析顺序是「子类 `permission_classes` 覆盖 `APIView` 的类属性」。因此它只在**视图类自己没有定义 `permission_classes`** 时才生效。脚本 B 逐条枚举 121 条路由各自的 `permission_classes` **归属类**，输出：

```
routes_falling_through_to_APIView = 0 []
```

**0 条回落** —— 即没有任何一条路由的 `permission_classes` 来自 `APIView` 的类属性，因此该 permission 在这些路由上不会被求值。
`guards.py:75` 的注释（「比赛域隔离由 `CompetitionScopePermission` 全局兜底」）与实际执行路径不符：真正的隔离完全来自各视图**显式**调用 `apply_competition_scope` / `_get_object` / `create_competition_id` / `assert_same_competition`（§6.1、§6.2、§6.5 与 §5.3）。

⚠️ **新增的 `RateLimitMiddleware` 不影响这个结论**：它是 Django **中间件**，与 DRF 的 `permission_classes` 是两个层面；它只在请求进入视图前做计数/拒绝，不改 `permission_classes` 的解析（见 §9.6 与 §13 D-03）。

**但它不等于没用** —— 它是**当前未激活的兜底**，重写时三种取法：

| 取法 | 做法 | 代价 |
| --- | --- | --- |
| 保留现状 | 每个视图继续显式声明 `permission_classes`（现状） | 新增视图若忘了写 `permission_classes`，会**突然**获得该 permission 的写操作粗校验（行为不一致） |
| 让它真正兜底 | 业务视图**不再**自定义 `permission_classes`，改以 `IsAuthenticated` + `CompetitionScopePermission` 为基线，差异用方法级装饰器表达 | 需逐个视图核对，且会改变未标注权限端点的组合语义（见 §10.2） |
| 删掉它 | 删除 `DEFAULT_PERMISSION_CLASSES` 里的第二项 | 与现状等价（因为它不生效），但失去「将来接上」的可能 |

⚠️ **不要把它写成"不存在"或"无定义"** —— 它定义在 `guards.py:105`、挂在 `settings.py:403`、并且真的被绑定到 `APIView` 上。准确表述是「**已挂载但当前无路由回落到它**」。

### 6.5 `assert_same_competition`

（`scope.py:10-16`）**仅在请求方提供了 `competitionId`**（`requested is not None`）**且实体确实绑定了 `competitionId`**（`entity is not None`）**且两者不等**时抛错：

```python
raise BusinessError("该数据不属于当前比赛，无法删除（可能属于其它比赛）", code=400, status_code=400)   # scope.py:16
```

调用点（5 处）：`companies/views.py:137`、`contracts/views.py:325`、`consumer_demands/views.py:220`、`regions/views.py:396`、`stock/views.py:416`。**全部在 DELETE 分支**。
→ 语义：**不传 `?competitionId=` 就不校验**；传了就必须一致。而基类 CRUD 的 DELETE（13 个资源）**根本不看这个参数** —— 见 §5.3 的 ⚠️。

### 6.6 哪些端点是「全局域」

`competitions`、`users`、`industry-types`、`company-fields`、`contract-types`、`audit-logs`、`announcements`、`widget-packages`、`auth/*`、`files/upload`、`system/rate-limit*`。
→ **重写时不要给它们「顺手加上」比赛过滤**：`industry-types` 是跨比赛的产业定义，`announcements` / `widget-packages` 是全局配置，速率配置是全局系统参数。

---

## 7. 增量同步协议（`apps/common/sync.py`，76 行）

### 7.1 请求参数

| 参数 | 语义 | 依据 |
| --- | --- | --- |
| `updatedAfter` | ISO 8601 时间戳基线；**无效值静默退化为全量**（`parse_baseline` 返回 `None`） | `sync.py:12-26,29-40` |
| `previousIds` | 逗号分隔的 id 列表；用于计算 `deletedIds` | `helpers.py` 的 `parse_previous_ids` |
| `requireExistingIds` | 强制返回 `existingIds`（不计算 `deletedIds`） | `regions/views.py:291`、`contracts/views.py:79` |

`updatedAfter` 兼容 `Z` 后缀（`sync.py:18-19`）；无时区信息按 UTC 处理（`sync.py:24-25`）。

### 7.2 响应字段（`sync.py:48-76`）

在标准 `{items, total}` 之上追加：

| 字段 | 何时出现 | 含义 |
| --- | --- | --- |
| `incremental` | 恒为 `true` | 标识增量结果 |
| `serverTime` | 恒有 | `datetime.now(UTC).isoformat()` 把 `+00:00` 换成 `Z`（`sync.py:43-45`）。**客户端用它推进下一次 `updatedAfter`** |
| `existingIds` | `previousIds` **为空**时 | 当前全部 id，客户端自行 diff |
| `deletedIds` | `previousIds` **非空**时 | `previousIds` 中已不存在的 id |

⚠️ `total` 是**本次变更条数**（`sync.py:65,72`），不是全表总数。

### 7.3 支持 `updatedAfter` 的端点（**6 个**）

| 端点 | 位置 | 备注 |
| --- | --- | --- |
| `GET /api/contract-types` | `contracts/views.py:73-86` | `@no_competition_scope` |
| `GET /api/contracts` | `contracts/views.py:177-192` | 比赛域 |
| `GET /api/companies` | `companies/views.py:79-88` | 比赛域 + `viewCompanyScopes` |
| `GET /api/regions` | `regions/views.py:285-296` | 比赛域；`requireExistingIds` |
| `GET /api/stocks` | `stock/views.py:280-293` | 比赛域 |
| `GET /api/industry-types` | `industry_types/views.py:361-370` | 全局域 |

⚠️ **`GET /api/competitions/:cid/fiscal-years` 不支持增量**（`competitions/views.py:165-178` 只有分页分支），尽管「财年更迭」是天然适合轮询的信号源。见 §13 的 D-06。
⚠️ **`/api/preparations/*` 不支持增量**；它是「一次性导出/导入」语义。

### 7.4 前端如何驱动增量

`frontend/src/api/request.ts` 的本地全量副本层负责：
- `fetchFullSync` 拉全量时必须**剥离** `updatedAfter` 与 `requireExistingIds`（否则服务端走增量分支、只返回 delta，被当成全量覆盖写 → 列表被清空）；
- 增量刷新时带上 `updatedAfter`，并用 `serverTime` 推进基线。

---

## 8. 文件上传、附件下载与 `/uploads/` 托管

### 8.1 上传端点

| 端点 | 字段名 | 传输 | 大小上限 | 类型校验 | 返回 | 源码 |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /api/files/upload` | `file` | `multipart/form-data` | 10 MB | 先看客户端 `content_type` ∈ {png,jpeg,jpg,gif,webp,bmp}，**再**校验魔数 | `{url, filename}` | `files/views.py:168-207` |
| `POST /api/files/map-background` | `file` + 可选 `competitionId` | multipart | 无显式上限 | 同上 | `{url, filename, width, height, transform}` | `files/views.py:231-278` |
| `POST /api/messages/upload-image` | `file` | multipart | 10 MB（`messages/views.py:67` 的 `_MAX_IMAGE_BYTES`） | **只读前 12 字节魔数**，只支持 PNG / JPEG / GIF / WebP（**不信任 `content_type`**） | `{url, filename}` | `messages/views.py:256-300` |
| `POST /api/widget-packages` | `file` | multipart | 5 MB | 文件名必须 `.zip`，且含合法 `manifest.json` | 控件包对象 | `widget_packages/views.py:59-108` |

**鉴权**：全部走 `Authorization: Bearer <jwt>`，权限见 §1.2.12 / §1.2.10 / §1.2.13。

### 8.2 落盘位置与 URL（`settings.py:464-465`：`MEDIA_URL = "/uploads/"`、`MEDIA_ROOT = UPLOAD_DIR`）

| 子目录 | 出站 URL 前缀 | 生产者 |
| --- | --- | --- |
| `uploads/` | `/uploads/uploads/` | `files/views.py:194,206`（`url = MEDIA_URL + "uploads/" + name`） |
| `map-backgrounds/` | `/uploads/map-backgrounds/` | `files/views.py:253,269` |
| `message-images/` | `/uploads/message-images/` | `messages/views.py:299`（硬编码相对路径） |
| `widget-packages/<uid>/` | `/uploads/widget-packages/<uid>/component.js` | `widget_packages/views.py:43` |

⚠️ **`/uploads/uploads/` 是真实现状，不是笔误**：`MEDIA_URL` 已是 `/uploads/`，再拼 `subdir = "uploads"`（`files/views.py:194`）就得到双段路径。重写时若「修正」成 `/uploads/xxx`，**已存的 `url` 字段会全部失效**。
⚠️ `widget_packages` 的 `componentUrl` 是前端动态 `import()` 的地址，必须保持可公开 GET。

### 8.3 静态托管

`backend/urls.py:59,65` 用 `re_path` + `django.views.static.serve` **无条件**托管 `/uploads/**` 与 `/static/**`。
源码注释（`backend/urls.py:55-58`）说明原因：`django.conf.urls.static.static()` 在 `DEBUG=False` 时不挂载 → 生产静默 404（症状：地图背景图上传成功但加载失败）。

| 路径 | document_root | 鉴权 | CORP |
| --- | --- | --- | --- |
| `/uploads/**` | `settings.MEDIA_ROOT`（`UPLOAD_DIR`，默认 `./uploads`） | **无** | `cross-origin`（`middleware.py:141-142`） |
| `/static/**` | `settings.STATIC_ROOT`（`BASE_DIR/staticfiles`） | **无** | `same-origin` |

⚠️ **上传受权限保护，下载完全公开**：`/uploads/` 是裸静态托管，任何人拿到 URL 即可下载（地图背景、消息图片、控件包 JS）。文件名含时间戳 / UUID，属于「不可枚举但不安全」的弱保护。见 §12 ⚠️ 第 10 条。

⚠️ **两套 MIME 判定口径不一致**：`files/views.py:182-193` 用客户端声明的 `content_type` **先**判、再验魔数；`messages/views.py:278-287` **完全不用** `content_type`，只看魔数。

### 8.4 附件下载（`/api/preparations/*`）—— **唯一不加壳的响应族**

`apps/preparation/views.py:116-122` 的 `_attachment_response`：

```python
resp = HttpResponse(body.encode("utf-8"), content_type=content_type)     # :118
resp["Content-Disposition"] = f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}"   # :120
resp["Cache-Control"] = "no-store"                                        # :121
```

| 端点 | 查询参数 | 响应 | Content-Type | 源码 |
| --- | --- | --- | --- | --- |
| `GET /api/preparations/plan/export` | `format=markdown`（默认）或 `json`；`competitionId` 可选 | **附件**（不经渲染器，**无 `{code,message,data}`**） | `text/markdown; charset=utf-8` / `application/json; charset=utf-8`（`_FORMATS`，`:75-78`） | `:167-195` |
| `GET /api/preparations/archive/export` | `scope=all\|<分组>`；`competitionId` 可选 | **附件**（同上） | `application/json; charset=utf-8` | `:198-214` |

`Content-Disposition` 同时给出 ASCII 回退名与 RFC 5987 的 `filename*=UTF-8''`（文件名含中文，如 `比赛准备_<比赛名>_比赛3_<时间戳>.md`）。
前端用 `responseType: "blob"` 消费（`api/index.ts:570-577,582-589`）。

⚠️ **这两个端点的响应体里没有 `code` 字段**，而前端响应拦截器的第一条判定是 `if (res.code !== 0)`（`request.ts:90`），对 `Blob` 而言 `res.code === undefined` → **前端必然报「请求失败」并 reject**。详见 §13 的 D-02。
⚠️ 因为不经渲染器，附件内容**不做大数转换**（§2.8）；导出 JSON 里的大整数按 Python `json` 原样输出。

### 8.5 公司产业字段的乐观锁（`version`）

公司产业字段是全系统**唯一**带并发控制写语义的资源（`company_fields/views.py:71-99` 的 `_write_field_value`）：

| 场景 | 行为 | 行 |
| --- | --- | --- |
| 该 `(company_id, industry_field_id)` 尚无记录 | `INSERT`，`version = 1` | `:83-90` |
| 已有记录、请求体带了 `version` | `UPDATE ... WHERE pk=? AND version=<期望>`；命中则 `version = 期望 + 1` | `:91-97` |
| 已有记录、请求体**没带** `version` | `expected_version = fv.version`（当前值）→ **等价无条件更新** | `:91` |
| `UPDATE` 影响行数为 0（并发修改） | 抛 `FieldWriteConflictException` → **409 + 「数据冲突，请刷新后重试」** | `:98-99` |

**读侧**：`GET /api/company-fields/<cid>` 与 `PUT` 的响应里，每个字段都带 `version`（`:63`），前端可回传它做 CAS。

⚠️ **`version` 是可选参数**（docstring `:78` 自述「缺省取当前 version，即无条件更新」）：前端若不回传，并发写会静默覆盖（last-write-wins），**用户看不到 409**。见 §13 的 D-19。

---

## 9. 特例端点

### 9.1 `GET /api/health`

- 鉴权：`AllowAny`（`auth/views.py:70`）。**无鉴权**。
- 响应恒定：`{"code":0,"message":"成功","data":{"status":"ok"}}`（`auth/views.py:72-73`）。
- **不触碰数据库、磁盘、迁移状态** —— 是纯 liveness 探针，不是 readiness。
- 前端**从不调用它**（全量 grep `frontend/src` 无命中）。消费方只有运维探针。
- ⚠️ 重写时保持无鉴权，并保持 `data.status` 字段名。

### 9.2 `GET /api/version`（**全局硬依赖**）

- 鉴权：`AllowAny`（`auth/views.py:86`），但**字段分级**。
- 版本号来源：**项目根 `VERSION.json`** 的 `version` 字段（`auth/views.py:32-41`，路径 = `__file__/../../../../VERSION.json`）；读取失败回退 `"0.0.0"`（`:44` 计算 `VERSION`）。

**未认证响应**：

```json
{ "code": 0, "message": "成功", "data": { "version": "1.0.0" } }
```

**已认证响应**（`auth/views.py:94-114`）：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "version": "1.0.0",
    "port": 8000,
    "log_viewer_port": 8120,
    "log_viewer_url": "https://log.comp.example.com/"
  }
}
```

`port` / `log_viewer_port` 来自 `settings.PORT`（默认 8000，`settings.py:149`）与 `settings.LOG_VIEWER_PORT`（默认 8120，`settings.py:152`），分别在 `auth/views.py:95,96` 赋值。
`log_viewer_url` 推导优先级（`auth/views.py:101-113`，赋值在 `:114`）：
1. 环境变量 `LOG_VIEWER_PUBLIC_URL`（非空即用）；
2. 否则按请求 `Host` 派生：纯 IP / IPv6 字面量 → `http://<host>:<LOG_VIEWER_PORT>/`；域名 → `https://log.<host>/`；
3. Host 为空 → `http://127.0.0.1:<LOG_VIEWER_PORT>/`。

**前端硬封锁语义**（必须原样保持）：

| 项 | 事实 | 源码 |
| --- | --- | --- |
| 请求方式 | **裸 axios**，不经业务实例：`axios.get(getApiBaseUrl() + "/api/version", { headers: {}, bypassVersionBlock: true })` | `frontend/src/stores/version.ts:18-21` |
| 不一致后果 | `versionBlocked.value = true` → 请求拦截器**拒绝发出任何业务请求** | `request.ts:27-33` |
| 逃生口 | 仅带 `config.bypassVersionBlock` 的调用（版本校验自身）可通过 | `request.ts:29` |

→ **重写铁律**：`/api/version` 必须**保持无鉴权**、**保持 `data.version` 字段名**、**值等于前端内置常量**。任何拼写变化或加鉴权，都会导致「页面能开、所有业务请求静默失败」。
⚠️ 该端点是**加壳的**（`version` 在 `data` 里），不是裸对象。

### 9.3 `/admin/`（Django admin + 防直连网关）

`backend/urls.py:16` 挂 `admin.site.urls`，共 **257 条**子路由。
DB 表是 `django.contrib.auth.User`，**与业务 `apps.users.User` 是两张不同的表**（`settings.py:376-380` 的注释解释了为什么 `PASSWORD_HASHERS` 必须保留 pbkdf2）。

**网关实现**：`apps/common/backend_gate.py`（127 行），通过 `settings.py:283` 挂在中间件链上，**仅对 `/admin/` 前缀生效**：

| 请求状态 | 行为 | 行 |
| --- | --- | --- |
| 非 `/admin/` 前缀 | 原样放行（`/api`、`/socket.io`、`/static`、`/uploads` 不受影响） | `:93-94` |
| `/admin/logout/` | 清除网关标记后放行（交由 Django 处理登出） | `:98-102` |
| 已登录（`session["_auth_user_id"]` 存在） | 直接放行，不受 TTL 影响 | `:107-108` |
| 携带有效 `?token=...` | 写入带时间戳的会话标记 → **302 到不带 token 的干净路径** | `:111-115` |
| 标记未过期且路径 ∈ {`/admin/`, `/admin/login/`} | 放行（进入登录流程） | `:119-121` |
| 标记未过期但路径更深 | 清标记 + 302 回前端 | `:122-124` |
| 无令牌、无标记（直连 / 书签 / 过期链接） | **302 回前端 SPA** | `:127` |

- 令牌：`POST /api/auth/backend-token`（仅 SUPER_ADMIN）签发，`TimestampSigner(key=LOGVIEWER_SECRET_KEY, salt="backend-gate")`（`auth/views.py:211`），TTL = `settings.BACKEND_GATE_MAX_AGE`（默认 120s，`settings.py:54`；`backend_gate.py:61`）。
- 会话标记键 `"bk_gate"`（`backend_gate.py:30`）；相关常量在 `:56,58,61`。
- 回跳目标 `_resolve_gate_redirect_to()`（`:33-51`，结果缓存于 `:54`）：`DJANGO_ALLOWED_HOSTS` 中有非回环主机 → `https://<host>/`；否则 `http://127.0.0.1:5173/`（本地 vite）。
- 安全头豁免：`SecurityHeadersMiddleware` 对 `/admin*` **直接返回、不加任何头**（`middleware.py:132-133`）。
- 前端入口：`SettingsView.vue:315` 取 token 后拼 `/admin/?token=...` 打开。

### 9.4 日志查看器（独立服务）

`backend/logviewer/` 是**另一个 Django 项目**（自己的 `settings` / `ROOT_URLCONF`），9 条路由见 §1.3。
与主后端的耦合点：
1. `POST /api/auth/logviewer-token`（仅 SUPER_ADMIN）签发一次性令牌，`TimestampSigner(key=LOGVIEWER_SECRET_KEY, salt="logviewer-gate")`（`auth/views.py:188`）；
2. `/api/version` 下发 `log_viewer_url`；
3. 两者共用 `LOGVIEWER_SECRET_KEY`（`settings.py:50`，未配置时回退 `JWT_SECRET`）。

前端只用它做**新标签页跳转**（`SettingsView.vue:335`），不走 axios —— 因此它的 9 条路由**不属于 HTTP API 契约**，但重写时需要保证 (1)(2)(3) 三项可用。

### 9.5 `/api/system/rate-limit*`（仅超管）

| 端点 | 方法 | 请求体 | 响应（加壳后 `data` 的形状） |
| --- | --- | --- | --- |
| `/api/system/rate-limit` | GET | — | `{"config": {ROLE: {enabled, requests, window}}, "usage": {ROLE: {currentRequests, maxRequests}}}`（`rate_limit_views.py:48-51`） |
| `/api/system/rate-limit` | PUT | `{"role": "SUPER_ADMIN"\|"COMPETITION_ADMIN"\|"PLAYER", "config": {enabled?, requests?, window?}}` | `{"message": "配置已更新", "config": {...}}`（`:82-85`） |
| `/api/system/rate-limit/reset` | POST | `{"action": "config"\|"records"\|"all"}`（默认 `config`，`:98`） | `{"message": "..."}` |

校验细节（`rate_limit_views.py`）：`role` 三选一否则 400「无效的角色」（`:63-64`）；`enabled` 必须 bool；`requests` / `window` 必须 ≥ 1（会 `int()` 归一）；`action` 非法 → 400「无效的 action」（`:111`）。非超管 → `BusinessError("仅超级管理员可访问", 403)`（`:27,55,95`）。
`permission_classes = (IsAuthenticated,)`（`:23,91`）—— **只有登录要求，超管判定在视图内**。
消费方：`frontend/src/api/index.ts:627-637` 的 `systemApi`。

### 9.6 `RateLimitMiddleware`（**已挂载但不生效**）

`settings.py:288` 把它挂在**第 12 位**（`AuthenticationMiddleware` 之后、`MessageMiddleware` 之前）：

```
 1 corsheaders.CorsMiddleware                       8 BackendGateMiddleware
 2 apps.common.cors.DynamicCorsMiddleware           9 CommonMiddleware
 3 SecurityHeadersMiddleware                       10 CsrfViewMiddleware
 4 OperatorContextMiddleware                       11 django.contrib.auth.AuthenticationMiddleware
 5 LoginRateLimitMiddleware                        12 apps.common.rate_limit.RateLimitMiddleware  ← 新增
 6 SecurityMiddleware                              13 MessageMiddleware
 7 SessionMiddleware                               14 XFrameOptionsMiddleware
```

**它的逻辑**（`rate_limit.py:106-161`）：

| 步骤 | 行为 | 行 |
| --- | --- | --- |
| 1 | 非 `/api/` 前缀 → 放行 | `:111-112` |
| 2 | 路径 ∈ `_EXEMPT_PATHS` → 放行 | `:115-116` |
| 3 | **`request.user` 不存在或 `is_authenticated` 为假 → 放行** | `:119-120` |
| 4 | 按 `user.role` 取配额；`enabled=False` → 放行 | `:126-128` |
| 5 | 计数 ≥ 配额 → 429 `{code, message, retryAfter}` | `:136-156` |
| 6 | 否则记录一次并放行 | `:159` |

配额默认值（`:22-38`）：`SUPER_ADMIN` `enabled=False`（不限制）；`COMPETITION_ADMIN` 300 次 / 60s；`PLAYER` 100 次 / 60s。
豁免路径（`:47-52`）：`/api/auth/login`、`/api/auth/refresh`、`/health`、`/healthz`。

> ⚠️ **第 3 步使整个中间件在 master 上永不生效。**
> 该中间件跑在所有中间件的 `process_request` 阶段，而 **DRF 的 JWT 认证发生在视图派发时**（`APIView.initial()`），晚于全部中间件。
> Django 的 `AuthenticationMiddleware`（第 11 位）设的 `request.user` 来自 **session**；本项目的 API 用 **JWT**，全仓库 `AUTHENTICATION_BACKENDS` 未覆盖、也没有任何代码给 `request.user` 赋值（`Select-String -Pattern 'request\.user\s*='` → 0 命中）。
> → 中间件看到的 `request.user` 恒为 `AnonymousUser`，`:119-120` 恒成立 → **每次都在第 3 步放行**。
> 结论：`_rate_limit_store` 永远是空的，`[rate_limit] ... 触发流量限制` 日志永不出现，`429(retryAfter)` 永不返回。见 §13 的 D-03。

**其余两个问题**（即使认证时序修好也仍然存在）：

| 问题 | 位置 | 说明 |
| --- | --- | --- |
| 豁免名单三条无效 | `rate_limit.py:47-52` | 真实健康检查路径是 **`/api/health`**（`backend/urls.py:18`），不在名单里；名单里的 `/health`、`/healthz` 没有对应路由；`/api/auth/refresh` **不是本项目的端点**（认证只有 login / me / change-password / 两条 token） |
| 计数键与注释不符 | `rate_limit.py:41-42,100-103` | 注释写「`{user_id: {role: [...]}}`」，实际类型是 `dict[int, list[tuple[float, int]]]`，且 `_record_request` 只按 `user_id` 记账 —— 切换角色后配额判定会串 |

---

## 10. 无鉴权 / 白名单端点清单

### 10.1 完全无鉴权（`AllowAny`）—— **只有 3 个**

| 端点 | 方法 | 依据 |
| --- | --- | --- |
| `/api/health` | GET | `auth/views.py:70` |
| `/api/version` | GET | `auth/views.py:86` |
| `/api/auth/login` | POST | `auth/views.py:123` |

外加**非 DRF 视图**（不走 DRF 认证链）：

| 路径 | 鉴权 |
| --- | --- |
| `/uploads/**` | **无** |
| `/static/**` | **无** |
| `/admin/**` | Django session（+ 网关令牌） |
| 日志查看器全部 9 条 | 它自己的会话 + 网关令牌 |

**其余 118 条 `/api/*` 路由全部要求 `Authorization: Bearer <jwt>`。**

### 10.2 「仅登录即可」端点（有鉴权、方法级无权限标注）

`PermissionsPermission.has_permission` 的显式契约（`guards.py:72-76`）：

> 「未标注 `@require_permissions` 的视图，默认仅『已登录』即可访问。**这并非越权缺口，而是设计基线。**」

| 端点 | 方法 | 补充的视图内校验 |
| --- | --- | --- |
| `/api/competitions` | GET | 非超管强制 `pk = user.competition_id`（`competitions/views.py:92-94`） |
| `/api/competitions/<pk>` | GET | `_get_competition` 比赛域校验 |
| `/api/competitions/<cid>/fiscal-years` | GET | `_get_competition` |
| `/api/announcements`、`/api/announcements/<pk>` | 全部 | 写操作视图内判 `role == "SUPER_ADMIN"` |
| `/api/widget-packages`、`/api/widget-packages/<pk>` | 全部 | 写操作视图内判 SUPER_ADMIN |
| `/api/companies/recompute-all` | POST | 视图内判 SUPER_ADMIN（`companies/views.py:181`） |
| **`/api/contracts/<pk>/execute`** | POST | 视图内判 `role in ("SUPER_ADMIN","COMPETITION_ADMIN")`（`contracts/views.py:361`） |
| **`/api/contracts/<pk>/recalculate`** | POST | 视图内判 SUPER_ADMIN（`:516`） |
| **`/api/contracts/<pk>/party-numbers`** | PATCH | 视图内判 `role in (SUPER_ADMIN, COMPETITION_ADMIN)`（`:460`） |
| `/api/system/rate-limit`、`/api/system/rate-limit/reset` | GET/PUT/POST | 视图内判 SUPER_ADMIN（`rate_limit_views.py:27,55,95`） |

⚠️ **重构陷阱**：不要「顺手加上权限」。例如给 `GET /api/competitions` 加 `competition:view`，会让只持有基础查看权限的选手看不到比赛列表 → 整个前端无法选比赛。

### 10.3 强制改密门禁的白名单 —— **只有 1 条路径**

`apps/auth/authentication.py:23`：

```python
_CHANGE_PASSWORD_PATHS = ("/api/auth/change-password",)
```

判定用 `path.endswith(...)` 尾匹配（`authentication.py:153-156`）。
→ 当 `must_change_password = true` 时，**只有** `/api/auth/change-password` 免于 401；**其它一切请求**（含 `/api/auth/me`、`/api/version`、全部业务接口）都会被 `AuthenticationFailed("账号需先修改初始密码", code="must_change_password")`（`:120-122`）拦成 **401**。

`ChangePasswordView` 另有类属性 `_allow_must_change_password = True`（`auth/views.py:234`）配合 `MustChangePasswordPermission`（`guards.py:47-59`）—— **该 permission 不在任何视图的 `permission_classes` 里**，是死代码（见 §13 D-17）。

⚠️ **可用性后果**：`/api/auth/me` 在强改密期间返回 401，而前端 20s 心跳正是打 `/api/auth/me`（`frontend/src/stores/auth.ts:176`）。心跳 401 → 全局拦截器清 token → 跳登录页。见 §13 的 D-01。

---

## 11. 前端调用路径 vs 后端路由的差异

**方法**：把 `frontend/src/api/index.ts`（637 行，全部 API 封装）+ 全仓库 `frontend/src/**/*.{ts,vue}` 里所有 `api.get/post/put/patch/delete(...)` 与 `axios.get(...)` 的路径字面量抽出来，与 §1.2 的 121 条路由逐一对照。

### 11.1 孤儿接口（前端调了、后端没有）—— **3 条，都会真实 404**

| 前端调用点 | 路径 | 后端事实 | 用户可见后果 |
| --- | --- | --- | --- |
| `frontend/src/views/data-management/InfrastructureManager.vue:248` → `infrastructuresApi.impact`（`api/index.ts:203`） | `GET /api/infrastructures/<id>/impact` | `infrastructures/urls.py` 的 `crud_urlpatterns` **未传 `impact_view`** | 404 → 删除确认框**不显示级联影响** |
| `frontend/src/views/data-management/ProductionLinesManager.vue:252` | `GET /api/production-lines/<id>/impact` | `production_lines/urls.py` 同样未传 | 同上 |
| `frontend/src/views/data-management/WarehousesManager.vue:286` | `GET /api/warehouses/<id>/impact` | `warehouses/urls.py` 同样未传 | 同上 |

三条都会走 `frontend/src/components/common/DataManager.vue` 的 `impact = await (props.api as any).impact(id)`，异常被吞后按「无影响」处理。

### 11.2 历史孤儿（前端注释提到的端点，后端从未实现）

| 位置 | 内容 |
| --- | --- |
| `frontend/src/stores/auth.ts:38-41` | 注释记载：权限目录改为**本地镜像**（`frontend/src/permissions/catalog.ts`），不再请求后端 |

复核实测：121 条 `/api/*` 路由里没有 `/permissions/catalog`。

### 11.3 僵尸接口（后端有、前端从不调）—— **12 条**

| 端点 | 方法 | 后端 | 前端事实 | 建议 |
| --- | --- | --- | --- | --- |
| `/api/regions` | GET | `regions/views.py:272`，分页 + `updatedAfter` | `regionsApi`（`api/index.ts:289-306`）只有 `create` / `remove` / `mapOverview` / `saveOverviewCardsByName` | 可删；先确认无外部脚本 |
| `/api/regions/<pk>` | GET | `regions/views.py:359` | 同上 | 同上 |
| `/api/regions/<pk>` | PATCH | 同上 | 同上 | 同上 |
| `/api/regions/<pk>/companies` | GET | `regions/views.py:417` | 同上（公司枚举走 `GET /api/companies?regionId=`） | 同上 |
| `/api/regions/<pk>/overview` | GET | `regions/views.py:429` | 同上 | 同上 |
| `/api/regions/<pk>/overview-cards` | PUT | `regions/views.py:442` | 前端走 `/api/regions/by-name/<name>/overview-cards`（按名 find-or-create） | 同上 |
| `/api/competitions/fiscal-years/<pk>` | DELETE | `competitions/views.py:240-249`，`competition:manage` | `CompetitionListView.vue:463` 只 PATCH（置 `CLOSED`），不删 | **保留**：删财年是管理动作 |
| `/api/users/<pk>/permissions` | POST | `users/views.py:169`，`account:manage` | `usersApi`（`api/index.ts:52-76`）**无对应方法**；账号页通过 `PATCH /api/users/:id` 带 `permissions` 数组赋权 | **保留**：它是唯一支持 `permissions=null`（按角色继承）语义的入口；`PATCH` 也支持但语义更宽 |
| `/api/company-fields/<cid>/<fid>` | PUT | `company_fields/views.py`（`CompanyFieldItemView`），`company:manage` | `companyFieldsApi` 只有 `get`（单公司）与 `set`（批量 PUT，`api/index.ts:237-238`） | **保留**：单字段写入是细粒度扩展点 |
| `/api/messages/<pk>` | GET | `messages/views.py:406`，`message:view`（仅发布者或收件人） | `messagesApi` 只用 `remove`（DELETE） | **保留**：该 GET 有完整的越权限制逻辑，是详情页的现成入口 |
| `/api/files/upload` | POST | `files/views.py:168`，`data:map:edit` | 前端**无 `filesApi`**，从不调用（地图背景走 `/files/map-background`） | **保留**：通用上传是扩展点 |
| `/api/health` | GET | `auth/views.py:67` | 前端从不调用 | **必须保留**：运维探针 |

**纯前端不调（10 条）**：上表前 10 行。
**前端不调但别的东西会调（2 条）**：`/api/health`（运维探针）、`/api/files/upload`（扩展点）。

### 11.4 前端「绕过 api 层」直连的路径

这些不在 `frontend/src/api/index.ts` 里，但在页面里直接发请求 —— 重写时容易漏：

| 路径 | 调用点 |
| --- | --- |
| `GET /api/competitions` | `MessageCenterView.vue:459`、`CompetitionListView.vue:307` |
| `POST /api/competitions`、`PATCH /api/competitions/:id`、`DELETE /api/competitions/:id` | `CompetitionListView.vue:377,374,416` |
| `GET/POST /api/competitions/:id/fiscal-years`、`PATCH /api/competitions/fiscal-years/:id` | `CompetitionListView.vue:346,447,463` |
| `POST /api/companies`、`DELETE /api/companies/:id` | `CompanyListView.vue:253,288` |
| `POST /api/contracts/trial` | `frontend/src/components/contracts/ContractTypeGraphEditor.vue:1317` |
| `POST /api/auth/backend-token`、`POST /api/auth/logviewer-token` | `SettingsView.vue:315,335` |
| `GET /api/version` | `frontend/src/stores/version.ts:18`（裸 axios） |
| `GET /api/auth/me` | `frontend/src/stores/auth.ts:176`（心跳） |

---

## 12. 重构关注点

### ✅ 必须保持的契约（外部可观测行为）

1. **响应信封**：成功 `{code:0, message:"成功", data}`；错误 `{code:<http码>, message:"中文", data:null}`；业务负载在 `data` 里。**2xx 时顶层 `code` 必须存在且为 0**（前端第一条判定是 `res.code !== 0`，`request.ts:90`）。
2. **分页元字段名**：请求 `page` / `pageSize`（camelCase），响应 `items` / `total` / `page` / `pageSize`；默认 1 / 50，上限 200。
3. **四种列表形状的分工**：§3 的「分页对象 / `{items,total}` 无页码 / 裸数组 / 对象」四类，各自端点必须保持原状。
4. **业务码 = HTTP 状态码**：228 个 `BusinessError` 调用点的 `code` 与 `status_code` 全部相等。
5. **错误 message 是唯一语义载体**：没有机器码。三种 401 的区分完全依赖中文文案，且前端**直接展示** `response.data.message`（`request.ts:52-53`）。
6. **比赛域隔离语义**：非超管**忽略**前端传来的 `competitionId`；无比赛上下文时列表返回**空集**、详情返回 **404**（不是 403）。
7. **`_get_object` 的 404 伪装**：跨比赛读详情必须返回「请求的资源不存在」，不能暴露资源存在性。
8. **`create_competition_id` 的 403**：超管不传 `competitionId`、非超管无归属比赛时都必须拒绝创建。
9. **`_check_conflict` 的早退**：唯一元组不完整时跳过查重。
10. **大数转换**：`abs(int) > 2^53` 出站为 **JSON string**；`Decimal` 非整数值为字符串；`Decimal` 非有限值为 `null`。
11. **`/api/version` 无鉴权 + `data.version` 字段名与值**（版本硬封锁的硬依赖）。
12. **`/uploads/**` 无鉴权托管 + `CORP: cross-origin`**：地图背景图与控件包 `component.js` 依赖它。
13. **`/api/health` 无鉴权**。
14. **强制改密只放行 1 条路径**：`/api/auth/change-password`。若把 `/api/auth/me` 也放行，会**改变可见行为**（心跳不再 401）—— 需与前端一起决策。
15. **路由顺序约束**：§1 各表共 5 处 ⚠️（messages 6 条静态子路径 / regions 2 条 / industry-types 1 条 / stock 6 条 / files 1 条）。这是**行为契约**，不是实现细节。
16. **无尾随斜杠**：`/api/materials` 有效，`/api/materials/` 404。
17. **200 而非 201**：创建成功统一 200。
18. **路径段名不变**：`/api` 全局前缀；`contract-types`（连字符）、`map-node-types`、`stocks/accounts/list`、`preparations/plan/export` 等段名不能改。
19. **`/preparations/*` 的两个导出端点是附件**（无信封、`Content-Disposition` 双写、不做大数转换）；且 `?format=` 必须被排除在 DRF 内容协商之外（§1.2.14）。
20. **`GET /api/stocks/<pk>/candles?afterRound=` 增量参数必须支持**（`stock/views.py:451-457`）。

### 🔄 可以自由重设计的部分

1. **语言 / 框架**：Django + DRF 的实现方式（`APIView` 子类、自定义渲染器、异常处理器）可完全替换，只要信封、状态码、字段名一致。
2. **路由注册方式**：`crud_urlpatterns` 这种「代码生成路由」可以换成显式声明 —— 反而更可审计。
3. **`CompetitionScopePermission` 的挂载方式**：当前已挂载但无路由回落到它。可以删掉、也可以**真正接上**。三种取法与代价见 §6.4。
4. **`strip_competition_fields`**：master 上无人调用，可删；或与 `base_crud.py:174-177` 的内联实现合并。
5. **`MustChangePasswordPermission`**：不在任何 `permission_classes` 里，可删（改密门禁实际由 `JWTAuthentication` 承担）。
6. **按角色限流的实现**：master 是进程内 `defaultdict` + `threading.Lock`（`rate_limit.py:42,44`），**不跨进程**。可以换成共享存储 —— 但要先修好 §13 的 D-03（认证时序），否则换了也没用。
7. **`_check_conflict` 的实现**：可以改成数据库唯一索引 + 捕获 `IntegrityError`，只要错误仍是 409 + 「名称已存在」。
8. **分页实现**：LIMIT/OFFSET 可以换成 keyset pagination（参数名与元字段名不能变）。
9. **`apply_competition_scope` 的「返回空集」策略**：可以改成 403 —— 但**会改变可见行为**，需前端同步改。
10. **`middleware.py`（275 行）拆分**：安全头 / 运维上下文 / 登录限流 / UA 精简混在一个文件里，可以拆开。
11. **`assert_same_competition` 的不一致语义**：可以统一成「DELETE 一律校验 `?competitionId`」或「一律不校验」，但必须**两边一致**（现状是 `companies` 校验、`base_crud` 不校验）。
12. **给错误响应加机器码**：是纯增量字段（前端目前忽略未知键）——**只有前端同步接入才有效**。
13. **`/uploads/uploads/` 的双段路径**：新系统可以改成单段，但这要求同时迁移已存数据里的 `url` 字段。
14. **`_IgnoreFormatParamNegotiation` 这类「DRF 行为覆盖」**：可以用别的方式实现（例如显式声明 `format` 不参与协商），只要保证 `?format=markdown` 不触发 404。

### ⚠️ 重构陷阱（新系统最容易踩的坑）

1. **给 2xx 响应省掉 `code` 字段** → 前端 `undefined !== 0` → 弹「请求失败」并 reject（`request.ts:90`）。**附件下载就踩这个坑**（D-02）。
2. **给 `/api/version` 加鉴权或改字段名** → 前端版本硬封锁 → 「页面能开、所有业务请求静默失败」。
3. **「顺手统一」列表形状** → `announcements` / `widget-packages` / `industry-types` / `messages/sent` 加分页壳，或给 `contract-types` 去掉 `items`/`total`，都会改变页面契约。
4. **`pageSize` 写成 `page_size`** → 前端不传时命中默认 50；一旦某页传 `pageSize=200`，服务端按默认 50 截断 → **静默少数据**。
5. **路由顺序**：把 `messages/<int:pk>` 或 `stocks/<int:pk>` 写在静态子路径前面 → 一批 404。Django 按**声明顺序**匹配，不是按具体度排序。
6. **尾随斜杠方向**：给路由加 `/` 会让前端全部 404；`APPEND_SLASH` 只处理相反方向。
7. **`PUT` 与 `PATCH` 的 partial 语义**：`CrudUpdateView` 的 PUT 是 `partial=False`（全量覆盖），PATCH 是 `partial=True`。前端只用 PATCH；PUT 也在契约里。
8. **删掉 `_check_conflict` 的早退** → 地图节点拖动（只发 x/y）会被判成「同比赛下重名」。
9. **比赛域用 403 而不是 404 / 空集** → 暴露资源存在性；`_get_object` 的 404 伪装是可观测行为。
10. **`/uploads/` 加鉴权** → 地图背景图、消息图片、控件包 `component.js` 全部加载失败（`<img src>` / 动态 `import()` 不带 Authorization 头）。
11. **`/admin` 也加 CSP 安全头** → 后台登录表单被 `form-action 'none'` 拦掉。
12. **用 201 表达创建成功**：前端只看 body 的 `code`，201 也能过；风险在于回归测试基线。保持 200 最省事。
13. **在响应里塞 `NaN` / `Infinity`** → DRF `STRICT_JSON=True` → `json.dumps` 抛 `ValueError` → 整个端点 500。`renderers.py:34-35` 对 `float` 没有兜底。
14. **以为 `contract:manage` 就能执行合同**：`execute` / `party-numbers` / `recalculate` 三条写操作**都不看权限 key**，改用 `role in (...)` 硬编码（`contracts/views.py:361,460,516`）。
15. **漏掉 `/api/competitions` 的非超管过滤**：非超管只能看到自己的那个（`competitions/views.py:92-94`），无归属时返回 `qs.none()`。
16. **省掉 `_IgnoreFormatParamNegotiation`** → `GET /api/preparations/plan/export?format=markdown` 直接 404（DRF 把 `format=markdown` 当渲染器后缀）。
17. **在中间件里读 `request.user` 做鉴权/限流判定** → 拿到的是 `AnonymousUser`，逻辑静默失效（D-03 就是这个模式）。

---

## 13. 已知缺陷与不确定性

| 编号 | 描述 | 证据/位置 | 影响 | 置信度 |
| --- | --- | --- | --- | --- |
| D-01 | 强制改密期间 `/api/auth/me` 返回 401，而前端 20s 心跳正是打这个端点 | `authentication.py:23,117-122` + `frontend/src/stores/auth.ts:176` + `request.ts:108-149` | 心跳 401 → 清 token → 跳登录页；新部署的超管可能**永远改不了初始密码** | 高（三处链路均已回源码确认） |
| D-02 | **两个附件下载端点的响应是 `Blob`，而前端响应拦截器只做 `res.code !== 0`** → `Blob.code === undefined` → 判为错误 | 后端 `preparation/views.py:116-122,195,214`（无信封）；前端 `request.ts:88-95`（无二进制分支）+ `api/index.ts:570-577,582-589`（`responseType: "blob"`） | `GET /api/preparations/plan/export` 与 `/archive/export` **在前端必然报「请求失败」并 reject**，导出功能不可用 | 中高（静态推断链路完整；建议实跑确认，见 Q-10） |
| D-03 | **`RateLimitMiddleware` 永不生效**：它在中间件阶段读 `request.user`，而 DRF 的 JWT 认证在视图派发时才发生 → 恒为 `AnonymousUser` → `:119-120` 恒放行 | `rate_limit.py:119-120`；`settings.py:273-291`（位置 12，在 `AuthenticationMiddleware` 之后但仍在视图之前）；全仓 `request.user =` 0 命中、无 `AUTHENTICATION_BACKENDS` 覆盖 | 按角色限流**完全没起作用**；`/api/system/rate-limit*` 的三个端点能改配置但不影响任何请求 | 高（代码路径 + 中间件/DRF 时序均可验证；`[rate_limit]` 日志永不出现即可实测） |
| D-04 | `CompetitionScopePermission` 已挂载（`guards.py:105` + `settings.py:403` + 绑定在 `APIView` 类属性上）但**无路由回落到它**：`routes_falling_through_to_APIView = 0`（121 条路由） | 脚本 B 实测输出；`guards.py:75` 的注释 | 注释声称的「全局兜底」与实际执行路径不符；新增视图若忘了写 `permission_classes` 会**突然**获得写操作粗校验 | 高（命令可复现） |
| D-05 | `POST /api/contracts/<pk>/execute`、`/recalculate`、`PATCH /party-numbers` **不用权限 key**，改用 `role in (...)` 硬编码 | `contracts/views.py:361,460,516`（三处都无 `@require_permissions`） | 无法通过权限配置调整；同一「合同」域内两套鉴权机制并行 | 高 |
| D-06 | `GET /api/competitions/:cid/fiscal-years` 不支持 `updatedAfter` 增量 | `competitions/views.py:165-178` 只有分页分支 | 「财年更迭」这个天然信号只能全量轮询 | 高 |
| D-07 | 3 条 `/impact` 孤儿接口 404，前端静默降级为「无级联影响」 | §11.1 | 删除基建 / 生产线 / 仓库时看不到级联影响，可能误删 | 高 |
| D-08 | `assert_same_competition` 语义在 `companies`（校验 `?competitionId`）与 `base_crud`（完全忽略该参数）之间不一致 | `companies/views.py:130-137` vs `base_crud.py:196-199` | 同一交互两种行为，前端无法统一处理 | 高 |
| D-09 | 登录限流中间件的用户名口径与登录视图不一致 | `middleware.py:258-266` 用**原始** body username 查锁；`auth/views.py:126` 用 **strip 后**的用户名记账 | `"admin "` 这类尾随空格变体查不到锁定记录，限流可被绕过 | 高 |
| D-10 | 登录限流中间件**只解析 JSON** | `middleware.py:260-265` 直接 `json.loads(request.body)`，异常即 `username = ""` | 改 `Content-Type: application/x-www-form-urlencoded` 即可绕过限流 | 高 |
| D-11 | 登录限流表无容量上限 | `middleware.py:203-205` 的 `defaultdict`，只有按时间的清理（`:213-225`） | 攻击者可控的用户名可持续撑大内存 | 中高（代码无上限分支；未压测） |
| D-12 | `renderers.py` 对 `float` 无非有限兜底 | `renderers.py:34-35` + DRF `strict = api_settings.STRICT_JSON`（默认 True） | 一行 `inf` / `nan` 脏数据会让该模块**所有读接口 500** | 中高（依赖数据里确实可能出现非有限 float） |
| D-13 | 两套上传 MIME 判定口径不一致 | `files/views.py:182-193`（先信 `content_type`）vs `messages/views.py:278-287`（只信魔数） | 安全强度不一致，审计口径难统一 | 高 |
| D-14 | `/uploads/**` 无鉴权裸托管，上传内容任何人可下载 | `backend/urls.py:59`、`middleware.py:141-142` | 弱保护（文件名不可枚举）；赛事期间图片可被本地转发 | 高 |
| D-15 | `/api/health` 是纯 liveness（不碰 DB / 磁盘 / 迁移），却被当作健康判据 | `auth/views.py:72-73` | DB 只读 / 磁盘满 / 迁移缺失时健康检查仍 `ok` | 高 |
| D-16 | `/api/messages/inbox` 返回分页对象，`/api/messages/sent` 返回裸数组（且被 `_SENT_TAKE = 500` 静默截断） | `messages/views.py:149-163` vs `:170-179`、上限见 `:65,175` | 同模块内两种形状；`sent` 超过 500 条时**无任何提示**地丢数据 | 高 |
| D-17 | `MustChangePasswordPermission`（`guards.py:47-59`）与 `strip_competition_fields`（`guards.py:148-150`）**无任何调用点** | `Select-String -Pattern 'MustChangePasswordPermission\|strip_competition_fields'` 只命中定义处与模块 docstring | 死代码；让人误以为改密守卫 / 跨比赛字段剔除有统一入口在生效 | 高 |
| D-18 | 大数转换把 >2^53 的整数变字符串，但 `id` 仍是数字 —— 两条形态并存 | `renderers.py:25-27` | 前端类型定义若统一声明为 `number` 会在金额字段上出错 | 高 |
| D-19 | `GET /api/company-fields/<cid>` 每个字段都返回 `version`，但 `PUT` 的 `version` **可选**：缺省时取当前值（等价无条件更新），乐观锁形同虚设 | `company_fields/views.py:63,91`（docstring `:78` 自述「缺省取当前 version，即无条件更新」） | 前端若不回传 `version`，并发写会静默覆盖（last-write-wins），用户看不到 409 | 高 |
| D-20 | `RateLimitMiddleware` 的豁免名单三条无效：`_EXEMPT_PATHS` 含 `/health`、`/healthz`（无此路由）与 `/api/auth/refresh`（无此端点），却**不含**真实的 `/api/health` | `rate_limit.py:47-52` vs `backend/urls.py:18` | 即使 D-03 修好，健康检查探针也会消耗登录用户的配额 | 高 |
| D-21 | `_rate_limit_store` 的类型与注释不符：注释写 `{user_id: {role: [...]}}`，实际是 `dict[int, list]`，`_record_request` 只按 `user_id` 记账 | `rate_limit.py:41-42,100-103` | 角色切换后配额判定串用（若 D-03 修好会显现） | 高 |
| D-22 | `preparation/views.py` 的导入端点默认 `dryRun=true`，但 `_resolve_bool` 同时读 `body.config` 与 query，两个来源不一致时的优先级未在本章核实 | `preparation/views.py:245-246` | 用户可能误判「预览」与「已落库」 | 中（需读 `_resolve_bool` 全文，见 Q-11） |

### 【待确认】清单

| 编号 | 待确认事项 | 确认方法 |
| --- | --- | --- |
| Q-01 | 各 CRUD 资源的 `unique_fields` 具体取值（决定 409 的触发条件） | `Select-String -Path .baseline-master/backend/apps/*/views.py -Pattern 'unique_fields'` 逐个核对 |
| Q-02 | `/api/users` 的 `competitionId="null"` 语义（系统账号列表） | 读 `users/views.py:45-70`；前端账号页传字符串 `"null"` |
| Q-03 | `AuditLogListView` 支持的查询参数全集（`kind` / `model` / `operatorId` / `competitionId`） | 读 `audit/views.py` 全文；前端 `AuditLogQuery`（`api/index.ts:491-498`）列了 6 个 |
| Q-04 | `POST /api/contracts/<pk>/execute` 的请求体字段与「公司范围」判定逻辑 | 读 `contracts/views.py:353-450`；前端 `contractsApi.execute(id, data)`（`api/index.ts:259`） |
| Q-05 | `GET /api/stocks/accounts/overview` 的元素字段全集（**已核实**：非超管 403、`cid` 为空返回 `[]`、正常返回裸数组，元素含 `holdings` 子数组；`stock/views.py:499-554`）。待确认的是 `holdings` 内字段是否全部被前端消费 | 读 `stock/views.py:499-554` 逐字段对照 `frontend/src/views/stocks/` |
| Q-06 | `POST /api/companies/recompute-all` 的响应字段 | 读 `companies/views.py:166-220`；前端只 `await` 不取字段（`api/index.ts:286`） |
| Q-07 | `GET /api/regions/map-overview` 的**元素**结构（**已核实**：顶层是 `list`，见 `regions/views.py:330-331`）。待确认字段名 | 读 `regions/views.py` 的 `_get_map_overview` |
| Q-08 | `messages` 的 `class CollectionView` GET 是否真的只返回「当前用户已发布」 | 读 `messages/views.py:304-330`（docstring `:309` 自述「当前用户已发布消息列表」） |
| Q-09 | `/api/preparations/*` 各响应体的稳定字段（`plan` 的统计结构、`scopes` 的元素、`import` 的结果结构） | 读 `preparation/{plan,archive}.py` 的 `collect` / `scope_options` / `apply_import` 返回结构；前端类型在 `frontend/src/types/api.ts` |
| Q-10 | **D-02 是否真实可复现**（附件下载在浏览器里是否真的报错） | 起一个只读实例，登录后点「导出 Markdown」，看是否弹「请求失败」；或看 Network 面板 200 但控制台有 reject |
| Q-11 | **D-22 的 `_resolve_bool` 优先级**（`body.config` vs query） | `git show origin/master:backend/apps/preparation/views.py` 读 `_resolve_bool` 定义 |
| Q-12 | `POST /api/preparations/archive/import` 在 `dryRun=false` 时的事务边界与失败回滚粒度 | 读 `preparation/archive.py` 的 `apply_import` |

---

## 14. 跨章依赖

### 14.1 本章依赖的章节

| 内容 | 归属章节 | 本章为何只引用不展开 |
| --- | --- | --- |
| 39 个权限 key 的完整目录、动作蕴含等级、角色模板与授予上限 | [03-认证权限与安全.md](03-认证权限与安全.md) | 本章只列 key 字符串与「在哪个端点上生效」 |
| JWT 的签发 / 校验、`token_version` 顶号语义、强改密门禁的完整设计 | [03-认证权限与安全.md](03-认证权限与安全.md) | 本章只写它对 HTTP 响应（401 + 中文 message）的影响 |
| Socket.IO 事件名、房间模型、断线重连 | [04-实时通信协议.md](04-实时通信协议.md) | 本章只在 §8 / §9 提「上传 / 改背景会广播」 |
| 各实体的字段全集与 JSON 列的隐含结构 | [01-领域模型与数据库.md](01-领域模型与数据库.md) | 本章表格里的字段只列到「契约相关」的键 |
| 前端响应解包、本地全量副本、增量对账、`normalize` / `cache` 选项 | [06-前端架构.md](06-前端架构.md) | 本章只写「前端会怎么消费这个形状」 |
| 合同 / 股票 / 建包引擎的算法与效果 | [05-核心引擎与算法.md](05-核心引擎与算法.md) | 本章只写端点的输入输出形状 |
| 端口、环境变量（`PORT` / `LOG_VIEWER_PORT` / `LOG_VIEWER_PUBLIC_URL` / `BACKEND_GATE_MAX_AGE`） | [07-部署运维与环境变量.md](07-部署运维与环境变量.md) | §9.2 / §9.3 只写它们如何影响响应字段 |
| §11 差异与 §13 缺陷的修复优先级 | [08-技术债与风险.md](08-技术债与风险.md)、[09-重构方案与实施路线.md](09-重构方案与实施路线.md) | 本章只列事实与影响，不定优先级 |

### 14.2 别章需要本章提供的数据

| 章节 | 需要本章的什么 |
| --- | --- |
| 03 认证权限 | §1.2 全量表「权限」列（各端点实际需要哪些 key）、§10 白名单清单、§10.3 强改密唯一放行路径、§9.6 的限流时序（D-03） |
| 04 实时通信 | §8.1 上传成功的广播触发点、§9.4 日志查看器令牌的签发方式 |
| 05 核心引擎 | §8.4 附件下载的响应契约（引擎输出经 `plan/export` 出站时**不做大数转换**）、§1.2.14 建包 5 端点 |
| 06 前端架构 | §2 信封判定（`code !== 0`，含 D-02 的二进制盲区）、§3 分页降维、§7 增量协议字段、§8 上传/下载契约 |
| 07 部署运维 | §9.1 `/api/health` 无鉴权、§9.3 `/admin` 网关与回跳推导、§8.3 `/uploads` 无鉴权托管 |
| 08 技术债与风险 | §11 前后端差异、§13 全部 D-01 ~ D-22 |
| 09 重构路线 | §12 的 ✅ 必须保持 / ⚠️ 陷阱两栏 |

---

*本章依据 `docs/refactor/_写作规范.md`（基准 `origin/master` = `fca118c`）写作。所有计数均给出可复现命令；所有断言均带 `.baseline-master/` 内的文件路径与行号。*
