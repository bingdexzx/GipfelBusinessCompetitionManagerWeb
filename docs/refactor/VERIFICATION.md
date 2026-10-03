# 独立校验报告（VERIFICATION）· **origin/master 基准版**

> 校验方：`verifier`（未参与任何章节写作）。职责：用可复现的命令**证伪**，不点头。
>
> ⚠️ **本报告的唯一基准是 `origin/master`（`fca118c`）**，一切测量均针对只读导出目录 **`.baseline-master/`**
> （相对仓库根；如需复现请执行 `git archive origin/master | tar -x -C .baseline-master`）。
>
> **基准演进史（本报告为第 3 版，前两版均作废）**：
> 1. v1（1050 行）验的是工作树 `bugfix-merged`（比 master 领先 256 提交）→ **作废**；
> 2. v2（752 行）验的是**本地 `master`（`97e117e`）**，它**落后 `origin/master` 123 个提交** → **作废**；
> 3. **v3（本报告）以 `origin/master`（`fca118c`）为准** —— 这是最终基准。
>
> 校验：`git rev-parse --short origin/master` = `fca118c`；`git rev-list --count master..origin/master` = **123**；
> `git rev-list --count origin/master..master` = **0**（本地 master 是 origin/master 的**祖先**）。
>
> 报告状态：**终审完成**。

---

## 0. 方法与口径

### 0.1 ⚠️ 行数两种口径（沿用前版结论，仍然成立）

规范/各章**混用两种口径**，本报告逐处标注：

| 对象 | 非空行（`Measure-Object -Line`） | 原始行（`(Get-Content).Count`） |
| --- | --- | --- |
| 后端 Python 总行（306 文件） | **26,143** | 30,629 |
| 前端 `.vue`（46 文件） | **26,449** | 27,772 |
| 前端 `.ts`（39 文件） | **7,702** | 8,229 |
| `apps/preparation/`（7 文件） | 4,563 | **5,215** ← 规范用此 |
| `contracts/engine.py` | 2,384 | **2,723** ← 规范用此 |
| `stock/engine.py` | 1,820 | **2,003** ← 规范用此 |
| `preparation/archive.py` | 2,363 | **2,701** ← 规范用此 |

**规律**：**汇总类用非空行、单文件用原始行**。两者都可复现。

### 0.2 严重度

**P0 红线** = 把 origin/master 上**不存在**的东西当作现状写；**P0 外引** = 指向其它文档的链接/文字提及/派生段落；
**P0 虚构** = 发明源码中不存在的接口/字段/事件/权限键/变量；**P1** = 断言与 baseline 冲突（计数错、行为错、**行号是旧基准的行号**）；**P2** = 自相矛盾；**P3** = 规范符合性；**P4** = 口径。

### 0.3 R6 合规

全部命令**只读**：文件枚举 / 行数统计 / `Select-String` / Django 只读取值（需临时注入 `JWT_SECRET`，仅子进程内存，**未写任何文件**）。
**未执行任何 git 写命令**（提交与推送由 Lead 统一执行），未改源码、未改他人章节。

---

## 1. origin/master 独立基准数字表（**校验方自己实测**）

### 1.1 规范给出的 15 项：**逐项复算，全部一致** ✅

| # | 指标 | 规范 | 我的测量 | 判定 |
| --- | --- | --- | --- | --- |
| 1 | Django app | 28 | **28** | ✅ |
| 2 | `preparation` app | 7 文件 / 5,215 行 | **7 文件 / 5,215 RAW**（非空 4,563） | ✅ |
| 3 | model 类 | 41（42 类 − `UserManager`） | `^class` **42**；运行时 concrete **41**；唯一非模型类 = `UserManager` | ✅（双向印证） |
| 4 | `path()` 注册 | 120 | **120** | ✅ |
| 5 | `/api/*` pattern | 121 | **121** | ✅ |
| 6 | 方法级端点 | 216（G90/P46/P32/D30/P18） | **216**，直方图 **`{get:90, post:46, patch:32, delete:30, put:18}`** | ✅（六项全中） |
| 7 | 后端规模 | 306 文件 / 26,143 非空 | **306 / 26,143**；`apps/` = **24,417** | ✅ |
| 8 | 前端 `.vue` | 46 / 26,449 | **46 / 26,449 非空** | ✅ |
| 9 | 前端 `.ts` | 39 / 7,702 | **39 / 7,702 非空** | ✅ |
| 10 | 权限键 / 域 | 39 / 19 | **39 / 19**（等级表 **2** 套；`SUPER_ADMIN_ONLY` **3**） | ✅ |
| 11 | 中间件 | 14（新增 `RateLimitMiddleware`） | **14**，第 **12** 位为 `apps.common.rate_limit.RateLimitMiddleware` | ✅ |
| 12 | 实时事件 | 8 + 3 = 11 | **11**（S→C 8 / C→S 3；`system:*` = 0） | ✅ |
| 13 | `MODEL_TO_RESOURCE` | 39 = 29 + 10 None | **39**（`None` = 10，映射 = 29） | ✅ |
| 14 | 环境变量 | `settings.py` 29 / `.env.example` 26 | **29 / 26** | ✅ |
| 15 | 关键单文件 | engine 2,723 / stock 2,003 / archive 2,701 | **2,723 / 2,003 / 2,701**（RAW） | ✅ |

### 1.2 补充测量（供各章比对）

| 指标 | 值 |
| --- | --- |
| 运行时 URL pattern 总数 | **380** |
| `urls.py` 文件数 | **28**（`apps/` 下 **26**） |
| 含端点的方法级展开（含自动 OPTIONS） | 337 |
| `models.py` 文件数 | 24 |
| `.scss` / `.jpg` / `.bak` | 2 / 749 非空；1 / 927；1 / 0 字节 |
| 默认数据库引擎（未设环境变量时） | `django.db.backends.sqlite3`（PG 分支存在，见 §3） |
| `common/middleware.py` | 275 RAW |
| `backend/settings.py` | **546 RAW**（非空 469） |

---

## 2. 红线表核对（**本轮规范已修订，我逐项实测**）

### 2.1 上一轮**误列**为红线、实际**存在**于 origin/master 的（各章**不得**写成"不存在"）

| 项 | `Test-Path` | 结论 |
| --- | --- | --- |
| `backend/apps/preparation/` | **True** | ✅ 存在（7 文件 / 5,215 RAW） |
| `backend/apps/common/rate_limit.py` | **True** | ✅ 存在 |
| `backend/apps/common/rate_limit_views.py` | **True** | ✅ 存在 |
| `scripts/dev.py` | **True** | ✅ 存在（且 `scripts/` 共 **23 文件**：含 `stop-dev.bat`、`stress-test.*`、`quick-test.*`） |
| `deploy/gipfel-daphne.service` | **True** | ✅ 存在（见 §4.3） |
| `migrate_to_postgresql.sh`（仓库根）/ `deploy/migrate-to-postgresql.sh` | **True** | ✅ 存在 |
| PostgreSQL / `DB_*` 支持 | **存在** | ✅ `settings.py` 有 PG 分支（见 §3） |

### 2.2 仍为真红线（origin/master 上**确实不存在**）

`apps/snapshots`、`realtime/bus.py`、`realtime/internal.py`、`contracts/builder/`、`common/db_pragmas.py`、
`common/fields.py`、`backend/examples/`、`docs/audit/`、`tests/fix_verify/`、`tests/ops_check/`、
`tests/snapshot_tools/`、`backend/tests_fix_verify/`、`contract_watcher/`、`code_audit/`
—— **`Test-Path` 全部 False** ✅（逐项实测）。

外加机制级红线（本轮实测）：**423 门禁 / `dataVersion` / `SystemGate` / `system:*` 事件 / `ExactDecimalField`** —— 命中 **0**（见 §5.1）。

### 2.3 全书红线扫描结论：**0 违规** ✅

对 00–09 + README 共 11 个文件、18 类红线关键词逐一计数（详见 §5.1）。所有命中均为**显式否定句**或**明示建议围栏**。

---

## 3. PostgreSQL / `DB_*`：origin/master **有完整能力**

```
backend/backend/settings.py   有 DB_ENGINE 分支；未设环境变量时回落到 django.db.backends.sqlite3
```
- 运行时实测：`settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"`（**因为未设 `DB_ENGINE`**，不是"没有 PG 支持"）。
- `migrate_to_postgresql.sh`（仓库根）与 `deploy/migrate-to-postgresql.sh` 均**存在**。
- `deploy/` 共 **15 个文件**：含 `postgresql-migration-guide.md`、`README-POSTGRESQL-MIGRATION.md`、`mysql-migration-guide.md` 等。

→ **各章写"master 无 PostgreSQL"即为 P0 红线**（本轮扫描未发现此类表述，见 §5.1）。

---

## 4. 高价值发现的独立复核

### 4.1 ④a「建包导出在前端必然失败」—— ✅ **独立证实**

**后端侧**（`.baseline-master/backend/apps/preparation/views.py`）：
```
:116  def _attachment_response(body: str, filename: str, content_type: str) -> HttpResponse:
:118      resp = HttpResponse(body.encode("utf-8"), content_type=content_type)
:120      resp["Content-Disposition"] = f"attachment; filename=..."
:167  class PreparationExportAPIView(APIView):        # GET /api/preparations/plan/export
:195      return _attachment_response(body, filename, content_type)
:198  class PreparationArchiveExportAPIView(APIView): # GET /api/preparations/archive/export
:214      return _attachment_response(body, filename, "application/json; charset=utf-8")
```
用的是 **`django.http.HttpResponse`**，**不是 DRF `Response`** → **绕过 `JSONRenderer`** → 响应体**没有 `{code,message,data}` 信封**。

**前端侧**：拦截器第一条判定是 `if (res.code !== 0)`，且**无"响应体不是信封"的分支**；对 `Blob` 而言 `res.code === undefined` → **必然 reject**。

**两章独立得出同一结论** ✓：`02:479`、`02:1195-1201`（附 D-02 交叉引用）、`06` 的 F-05。
→ **判定：成立，且是本轮最有价值的交付之一**（一个必然失效的用户功能，只有跨 02/06 两章才能看出来）。

### 4.2 ④b「`RateLimitMiddleware` 恒放行」—— ✅ **独立证实（机制链完整）**

```
rate_limit.py:106  class RateLimitMiddleware(MiddlewareMixin):
rate_limit.py:109      def process_request(self, request):
rate_limit.py:111          if not request.path.startswith("/api/"): return None
rate_limit.py:115          if request.path in _EXEMPT_PATHS: return None
rate_limit.py:119          if not hasattr(request, "user") or not request.user.is_authenticated:
rate_limit.py:120              return None                     ← ★ 恒在此处返回
rate_limit.py:127      if not role_config.get("enabled", False): return None   ← 第二道闸（默认关闭）
```
**运行时中间件顺序**（我实测打印）：`… 11 django.contrib.auth.middleware.AuthenticationMiddleware` → **`12 apps.common.rate_limit.RateLimitMiddleware`**。

**机制链**：`/api/*` 走 **DRF `JWTAuthentication`**，它在 **视图派发期**（`APIView.initial()`）执行，
**晚于全部中间件**；Django 的 `AuthenticationMiddleware`（第 11 位）只解 **session**，而 JWT 客户端无 session
→ 第 12 位处 `request.user` 恒为 `AnonymousUser` → `is_authenticated` 为 False → **`:120 return None` 恒放行**。

→ **判定：成立**。推论「按角色限流从未生效」正确；登录限流（另一套，`LoginRateLimitMiddleware`）是独立机制，不受此影响。
**建议各章注明**：这是"配置/注释描述的能力 ≠ 运行时实际生效的能力"的**第二个实例**（第一个是 `CompetitionScopePermission`）。

### 4.3 ④c「deploy/ 有两个互相冲突的 daphne 模板」—— ✅ **独立证实**

| 模板 | 关键内容 |
| --- | --- |
| `deploy/gipfel.service` | `Type=simple`；`ExecStart=daphne -u /run/gipfel/gipfel.sock -b 127.0.0.1 -p 8000` → **单进程** |
| `deploy/gipfel-daphne.service` | `Type=forking`；`After=/Requires=mysql.service`；`ExecStart=/opt/gipfel/deploy/start-daphne-workers.sh` |
| `deploy/start-daphne-workers.sh` | `:18 WORKERS=4`、`:19 BASE_PORT=8000`、`:64-66 nohup daphne -p $PORT` → **8000–8003 四个 worker** |

→ **判定：成立**。四 worker 会**切碎六类进程内状态**（seq 环、登录失败计数、`RateLimitMiddleware` 计数、
`_advance_locks`、`OperatorContext`/`logfilter` 的 contextvar、快照门禁类缓存若存在）。
**注意**：`gipfel-daphne.service` 依赖 `mysql.service`，而本项目用 SQLite/PG —— 该模板**根本起不来**，属废弃产物。

### 4.4 ② 两个"被删除的 bug"：**删除都正确** ✅

| 原断言（旧基准） | origin/master 实测 | 判定 |
| --- | --- | --- |
| `build_candle` 的 `Decimal / float` 在平盘轮抛 `TypeError` | `stock/engine.py:245-247` 已加 **`open_ = float(open_)` / `close = float(close)`**（注释：「确保 open_ 和 close 是 float 类型（避免 Decimal 和 float 混合运算）」）；`:273 price = float(open_)`；`:287 abs(close - open_) / price` 两侧均为 float | ✅ **bug 不存在，删除正确**（该修复是在 `origin/master` 才有的） |
| `apply_leaf` 不读 `default_value` | `company_fields/calc.py:381 stored = field.default_value`（`:371-374` 有专门的回退说明）；另 `timer.py:109`、`views.py:54,62` 均读 | ✅ **bug 不存在，删除正确** |

> **这两条删除不是漏报**：它们在**旧基准**（工作树 / 本地 master）上确为真缺陷，在 `origin/master` 上已被修复。
> 作者按新基准删除是**正确的**。

### 4.5 ③ 05 章的因果链修复：**10 个行号全部在 origin/master 上成立** ✅

| 05 章引用 | origin/master 实际内容 |
| --- | --- |
| `:1899` = `raise`（非持有者退出） | `1899: raise BusinessError(` |
| `:1902` = `try` | `1902: try:` |
| `:2002-2003` = `finally` / **全文件唯一释放点** | `2002: finally:` / `2003: _release_advance_lock(competition_id)` |
| `:1864` = `with _advance_locks_guard`（覆盖两次 release） | `1864: with _advance_locks_guard:` |
| `:1868` / `:1872` = 两次 `lock.release()` | `1868: lock.release()` / `1872: lock.release()` |
| `:1843` / `:1854` = 同一把非重入锁（acquire 侧） | `1843: _advance_locks_guard = threading.Lock()` / `1854: with _advance_locks_guard:` |
| `:1852` = docstring「本锁本身不跨进程」 | `1852: 本锁本身不跨进程。写操作的原子性已由 advance_round 内的 transaction.atomic() 兜底。` |

→ **三条反证与全部行号均成立**；T2 已改、D-02 已降级、**D-02b 已新增（严重度高）** ✅

---

## 5. 全书级扫描（终审）

### 5.1 ① 红线 —— **0 违规** ✅

18 类关键词对 11 个文件计数，全部为 **0**，或以**显式否定句**出现：

| 关键词 | 全书命中 | 说明 |
| --- | --- | --- |
| `snapshots` / `realtime/bus.py` / `internal.py` / `contracts/builder` / `db_pragmas` / `fields.py` / `examples` / `fix_verify` / `ops_check` / `contract_watcher` / `code_audit` | **0** | ✅ |
| `423` / `强制暂停` / `dataVersion` / `SystemGate` / `system:*` / `/_internal` / 总线四模式 | **0** | ✅ |
| `ExactDecimalField` | 少数命中 | 均为「master **没有** `ExactDecimalField`」的否定句 |
| 按角色限流 | 少数命中 | 均为否定句或对 §4.2 的**缺陷描述**（描述一个"存在但不生效"的机制**不是**红线） |

**本轮新增核对**：`preparation`、`rate_limit`、`dev.py`、`gipfel-daphne`、`migrate-to-postgresql`、`PostgreSQL/DB_*`
—— 各章**均未**把它们当作"不存在"来写（本轮扫描未发现此类表述）✅

### 5.2 ② 零外部文档引用 —— **0 违规** ✅

- **链接**：全书 markdown 链接**全部**指向本套内文件（`00-…`～`09-…`、`README.md`、`VERIFICATION.md`、`_写作规范.md`），**非本套 0 个、失效 0 个**。
- **文字提及**：仅 `_写作规范.md` 出现被禁文档名（其职责所在）；`05` 的 `MIGRATION` 命中是 `migrations/` **目录名**（该章自查了这点）；「缺陷台账」是本套 08 章**小节名**；「事故」是普通行文用词（`03` 的出处是 master 源码注释）。
- **派生段落**：未发现事故档案 / 审计台账 / 赛务分析 / 未落地设计稿式段落。

### 5.3 ④ `errorCode` —— 全书统一为「master 无」✅

master 后端 `errorCode` 字面量 **0 命中**。全书仅 4 个文件提到它，且**全部是"没有"的表述**
（`02:46`「**0 个**」+ 可复现命令、`02:750`「→ 0 命中」、`03:365`、`03:1166`、`09` Z2「2xx 必须带 `code:0`，错误语义靠状态码 + `message`，401 四类只能靠文案」、`README:162`）。
旧稿「8 个机器码字面值」式表述**已清零**。

### 5.4 `CompetitionScopePermission` 口径：**口径差异、结论一致，不构成跨章冲突** ✅

各章数字不同（02 的 65「按路由去重的提供者」/ 03 的 131「全仓视图类含未路由」/ 我的 88「URLconf 可达去重」），
但**核心不变量完全一致**：02 明确给出 **`fallthrough_to_APIView = 0`**，我的实测为 `0 / 88` 命中，03/08 均写「0 个视图回落到它」。
**判定：不构成冲突**。建议（P4 可选）各章统一引用 `fallthrough_to_APIView = 0` 作为唯一判据。

### 5.5 ⑥ 骨架与链接

- **骨架**：00–08 全部具备 `✅/🔄/⚠️` 三小节；09 为方案章，以骨架映射行替代（**可接受**）。
- **链接**：全部同目录相对链接，**0 失效**。
- **绝对路径**：全书 **0 处**绝对路径（`.baseline-master/...` 均为相对仓库根写法，基准目录删除后仍可读）。

---

## 6. 跨章冲突表

| # | 事实点 | 各章说法 | 裁定 |
| --- | --- | --- | --- |
| C-01 | app 数 / model 数 | 全书 28 / 41 | 一致 ✅（基准 28 / 41） |
| C-02 | 权限键 / 域 | 全书 39 / 19 | 一致 ✅ |
| C-03 | 实时事件 | 全书 S→C 8 / C→S 3 / 合计 11；`system:*` = 0 | 一致 ✅ |
| C-04 | `errorCode` | 全书「master 无」 | 一致 ✅ |
| C-05 | `CompetitionScopePermission` | 65 / 131 / 88 三口径 | **口径差异、结论一致**，非冲突 ✅ |
| C-06 | 两个导出端点无信封 | 02 D-02 与 06 F-05 独立同结论 | 一致 ✅（互为佐证） |
| C-07 | `select_for_update` SQLite no-op | 01 / 05 / 08 / 09 一致 | 一致 ✅ |

**跨章冲突：0**。

---

## 7. 终审判定

> **红线 0、外引 0、虚构 0、冲突 0、待修 0 —— 这套以 `origin/master`（`fca118c`）为基准的 `docs/refactor/` 文档集可用于完全重构。**

**依据**
1. **基准精确**：规范给出的 **15 项数字我全部独立复算，15/15 一致**（含最易错的六项端点直方图 `G90/P46/P32/D30/P18`、`MODEL_TO_RESOURCE 39 = 29+10`、中间件 14 且 `RateLimitMiddleware` 位次 12）。**未采信规范任何数字**。
2. **红线表已修正到位**：上一轮 6 项误列（`preparation`/`rate_limit`×2/`dev.py`/`gipfel-daphne`/PG）经我实测**确实存在**于 origin/master；13 类真红线经我实测**确实不存在**。全书**没有**再把存在的当不存在、或把不存在的当存在。
3. **3 个高价值发现全部独立证实**：导出端点无信封（跨 02/06 两章交叉验证）、`RateLimitMiddleware` 恒放行（中间件位次 + DRF JWT 时序链完整）、两个冲突 daphne 模板（含 `mysql.service` 依赖，起不来）。三者都**只有在新基准下才成立**，且都影响重构决策。
4. **2 条删除经我独立核实为正确**：`build_candle` 已在 `:245-247` 做 float 归一；`apply_leaf` 已读 `default_value`（`calc.py:381`）。**不是漏报**。
5. **05 章因果链修复的 10 个行号全部在 origin/master 上成立**。

**必须修清单：0 条待修。**
（唯一 **P4 级可选建议**：各章统一用 `fallthrough_to_APIView = 0` 表述权限落地判据。）

**残留限制（须随文档告知使用者）**
- **L-1**：三个高价值发现均为**静态源码/导入期**判定，未在真实运行实例上端到端复现（origin/master 无 app 级测试）。
- **L-2**：`deploy/` 存在**互相冲突的两套 daphne 模板**；文档已指出，但**哪一套是生产实际使用**需运维确认（`gipfel-daphne.service` 依赖 `mysql.service`，多半是废弃产物）。
- **L-3**：行数有**两种口径**（汇总=非空行 / 单文件=原始行），换口径复算会得到不同数字。
- **L-4**：`.baseline-master/` 为临时只读导出，交付后将被删除；复现需 `git archive origin/master`。
- **L-5**：`DB_ENGINE` 分支存在但**默认回落 SQLite**；"是否已迁移到 PG"取决于部署时的 `.env`，**代码本身无法判定**。

**累计断言 168 条**：基准 62（15 项规范核对 + 补充测量 + 红线逐项）+ 红线/外引/口径全书级 42 + 高价值发现与删除核实 34 + 05 章修复 10 + 骨架/链接 20。
**不成立 0 项**（本版）；**P0 虚构 0**；**红线 0**；**外引 0**；**跨章冲突 0**；**链接 0 失效**。
