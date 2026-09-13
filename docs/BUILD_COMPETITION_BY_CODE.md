# 用代码创建比赛内容（建包库）

> 目标：把「为一场比赛录入公司、地图、物资、科技树、合同、股票、账号……」从**手工点界面**
> 变成**写一段简单 Python 代码**，同时保证与现有功能 100% 兼容。
>
> 📖 **本文适合先读**（讲清思路与工作流）；需要逐个方法、逐个参数的完整说明时看
> [**《比赛建包库 · 完整 API 手册》**](BUILD_COMPETITION_API_REFERENCE.md)。

---

## 1. 它是什么 / 不是什么

| | 说明 |
| --- | --- |
| **是什么** | 一个纯 Python 建包库 `apps.preparation.builder`，用链式方法把比赛内容描述出来，产出**与现有「导出归档」完全同构的 JSON**；再用一条管理命令（或前端导入）把它装进目标比赛。 |
| **不是什么** | 它**不直接写数据库**。所有落库仍走 `apps.preparation.archive.apply_import`——也就是「比赛准备 → 导入归档」用的那套引擎。 |

这样设计的直接好处：**没有新增任何写库路径**。外键映射、跨分组按名兜底、追加/覆盖策略、
空比赛保护、dry-run 回滚这些已经存在并被验证过的逻辑全部原样复用，因此不可能影响现有功能。

```
你的脚本  ──build()──▶  归档 JSON  ──apply_import()──▶  目标比赛
（链式 API）           （与导出同构）    （既有导入引擎）
```

---

## 2. 三分钟上手

```python
# my_competition.py（放在任意位置）
from apps.preparation.builder import CompetitionBuilder

def build():
    b = CompetitionBuilder("2026 春季赛")

    east = b.region("东区")
    steel = b.industry_type(1, "钢铁")                      # code 全局唯一
    b.add_field(steel, "所在地", "location", field_type="STRING")
    b.add_field(steel, "现金", "cash", field_type="NUMBER", default_value="0")

    b.company("甲钢铁", industry_type=steel, region=east,
              field_values={"location": "东区港", "cash": "800000"})
    b.fiscal_year(2026)
    return b
```

在 `backend/` 目录下执行：

```powershell
# 1) 只看会建出什么（不连数据库、不写任何东西）
python manage.py build_competition my_competition.py --inspect

# 2) 导出归档 JSON（也可以拿去让前端「导入归档」上传）
python manage.py build_competition my_competition.py --out my.json

# 3) 预演导入（事务回滚，结果与真实导入一致，但一行都不落库）
python manage.py build_competition my_competition.py --competition 7 --dry-run

# 4) 真正导入
python manage.py build_competition my_competition.py --competition 7
```

> 命令退出码：`0` 成功；`1` 出现 problem（部分数据没落地）；`2`/`CommandError` 被拒绝
> （例如目标比赛已有数据却没加 `--allow-non-empty`）。适合放进 CI。

完整可运行示例见 [`backend/examples/competitions/demo_competition.py`](../backend/examples/competitions/demo_competition.py)
——它覆盖**全部 35 类资源**，可直接照抄改数。

---

## 3. 命令参数一览

| 参数 | 作用 |
| --- | --- |
| `<source>` | 建包脚本（`.py`）或归档文件（`.json`）。给 `.json` 时跳过建包，直接走导入。 |
| `--competition <id>` | 目标比赛 id（导入必需） |
| `--dry-run` | 预演：事务回滚，返回与真实导入一致的结果 |
| `--mode append\|overwrite` | 追加（默认，已存在的保留不动）/ 覆盖（已存在的按本包更新） |
| `--resources a,b,c` | 只导入指定资源（如 `companies,companyFieldValues`） |
| `--scope <分组>` | 只产出/导入某个分组（`competition`/`industry`/`company`/`supply`/`geo`/`tech`/`market`/`access`） |
| `--allow-non-empty` | 允许导入到已有业务数据的比赛（默认拒绝，避免污染） |
| `--out <path>` | 把产出的归档 JSON 写文件（不连数据库） |
| `--inspect` | 只打印产出摘要，不导入 |
| `--schema [资源名]` | 打印字段字典（不给资源名则打印全部） |

脚本里只要能拿到下列任意一种即可：`def build()`（推荐）、模块级 `BUILDER`、
模块级 `ARCHIVE`、或「最后一行是一个构建器表达式」。

---

## 4. 比赛内容的建包方法

按「比赛准备」的九个分组排列；方括号里是产出的归档资源名。
**本节是速览；每个参数的完整说明见 [API 手册第 4 节](BUILD_COMPETITION_API_REFERENCE.md#4-构建器方法逐个讲透)。**

### ① 比赛基础

```python
b = CompetitionBuilder("比赛名", status="ACTIVE", map_background={"url": "...", "width": 1920, "height": 1080})
b.fiscal_year(2026)                       # [fiscalYears]
b.stock_config_set({"limitPct": 0.1, "maxMovePct": 0.08, "mmMinQty": 100, "mmMaxQty": 5000})  # [stockConfig]
```

- 比赛名**不会被导入改写**（避免全局重名冲突），只同步状态与缺失的地图背景图；
- 新建财年 / 把财年从非 ACTIVE 改为 ACTIVE 会触发 `FY_START` 定时器，改写启用了该时机的字段；
- `stock_config_set` 不调用就完全不产出该资源，目标比赛沿用原配置。

### ② 行业口径（全局资源）

```python
steel = b.industry_type(1, "钢铁", description="钢铁冶炼")            # [industryTypes]
b.add_field(steel, "所在地", "location", field_type="STRING")          # [industryFields]
b.add_field(steel, "现金", "cash", field_type="NUMBER", default_value="0")
b.add_field(steel, "货币资金", "total_cash", is_calculated=True,        # 计算字段
            graph=calc_graph(calc_node("add", node_id="sum"),
                             calc_node("field", node_id="a", fieldKey="cash"),
                             calc_node("field", node_id="b", fieldKey="bank_deposit")))
b.add_field(steel, "年度预算", "annual_budget", timer_enabled=True,     # 财年定时器
            timer_trigger="FY_START", timer_value="1000000")
```

- **全局资源**：产业类型按 `code`、产业字段按 `(code, fieldKey)` 复用/更新，不会重复新建；
- 每个产业类型都应该有一个 `field_key="location"` 的「所在地」字段——地图、运费、
  区域总览都依赖它；
- `is_calculated` 与 `timer_enabled` **互斥**（库会直接报错拦下）；
- 计算图助手：`calc_node("add"|"sub"|"mul"|"div"|"field"|"const"|"sum"|"avg"|"max"|"min", ...)`
  + `calc_graph(*nodes)`（不传 `edges` 时按传入顺序自动串成一条链）。

### ③ 参赛主体

```python
east = b.region("东区", description="沿海产业带")                       # [regions]
a = b.company("甲钢铁", industry_type=steel, region=east, status="ACTIVE",
              field_values={"location": "东区港", "cash": "800000"})    # [companies] + [companyFieldValues]
b.add_field_value(a, "bank_deposit", "200000")                        # 也可单独追加
```

- `field_values` 的键是产业字段 `fieldKey`，且必须是**本包内已 `add_field` 登记过**的字段
  （否则导入时会因找不到字段而跳过，库会提前报错）；
- 字段值一律以文本写入，NUMBER 字段也建议传字符串以保留精度；
- `region` 可以传区域引用或名称；本包内没有该区域时导入侧会按名称自动建一个。

### ④ 物资与产能

```python
diesel = b.fuel("柴油", price_per_liter="7.5")                          # [fuels]
iron = b.material("铁矿石", origin="北山矿", carbon_emission_coefficient=0.52,
                  node_prices={"北山矿": "120", "东区港": "138"})        # [materials]（地点价按节点名）
t1 = b.tech("高炉冶炼", tier=1, research_cost="5000")                   # [techNodes]
t2 = b.tech("热轧工艺", tier=2, prerequisites=[t1])                     # [techPrerequisites]
p1 = b.part("铁锭", materials={iron: 2}, tech=[t1])                     # [parts][partMaterials][partTechRequirements]
pr = b.product("热轧钢板", parts={p1: 3}, tech=[t2])                    # [products][productParts][productTechRequirements]
b.line("一号线", price="1200000", labor_count=40, max_per_year="5000")   # [productionLines]
b.infrastructure("自备电厂", footprint=120, price="900000",
                 activation_price="50000", carbon_reduction_bonus=0.05)  # [infrastructures]
b.warehouse("原料仓", "MATERIAL", capacity="20000", price="300000")      # [warehouses]
b.vehicle("卡车", fuel=diesel, path_types=[road], max_cargo=30,
          fuel_consumption_per_km=0.35, price="260000")                  # [vehicles][vehiclePathTypes]
```

- **依赖方向固定**：`原料 → 零件 → 产品`。零件配比只能引用原料（模型里没有「零件用零件」），
  写错会被库直接拦下；
- 载具必须绑定燃料，且建议至少给一条可通行路径类型（否则运输路径校验会失败）；
- 仓库四种种类（MATERIAL/PART/PRODUCT/FUEL）建议都有覆盖。

### ⑤ 地理与物流

```python
city = b.node_type("城市", color="#3b82f6")            # [mapNodeTypes]
road = b.path_type("公路", color="#94a3b8")            # [pathTypes]
n1 = b.node("东区港", city, region="东区", x=320, y=180)  # [mapNodes]
n2 = b.node("西区站", city, region="西区", x=760, y=260)
b.edge(n1, n2, 420, road)                              # [mapEdges]
```

- 节点的 `region` 是**文本列**（不是外键），区域总览按它聚合；
- 连线唯一约束是 `(起点, 终点)`：同一对节点只能有一条，方向不同算两条；起终点不能相同；
- 孤立节点（没有任何连线）不可达，`validate()` 会提醒。

### ⑥ 科技与需求

见上面的 `tech(...)`；消费者需求：

```python
b.demand("东区", pr, 1200, note="基建用钢")             # [consumerDemands]
```

- 导入按 `(比赛, 区域, 产品, 数量)` 幂等去重，因此「改需求量」等于新增一条；
- 产品必须在本包登记过（否则玩家无法交付）。

### ⑦ 市场与规则

```python
b.card(east, a, "cash", display_name="现金")            # [overviewCards]

ct = b.contract_type("steel-sale", "钢材销售合同",       # [contractTypes]
                     party_roles=[{"role": "seller", "label": "卖方"},
                                  {"role": "buyer", "label": "买方"}],
                     input_schema=[{"key": "amount", "label": "金额", "type": "NUMBER", "required": True}],
                     conditions=[{"kind": "FIELD", "party": "buyer", "fieldKey": "cash",
                                  "op": "GTE", "value": {"from": "input", "key": "amount"}}],
                     effects=[{"kind": "FIELD", "party": "buyer", "fieldKey": "cash",
                               "op": "SUB", "value": {"from": "input", "key": "amount"}},
                              {"kind": "FIELD", "party": "seller", "fieldKey": "cash",
                               "op": "ADD", "value": {"from": "input", "key": "amount"}}])
b.contract(contract_type=ct,                            # [contractInstances]
           parties=[{"role": "seller", "company": a, "contractNumber": "S-001"},
                    {"role": "buyer", "company": c, "contractNumber": "B-001"}],
           inputs={"amount": 960000}, status="DRAFT")

b.stock("600001", "甲钢铁", company=a, total_shares="12000",
        init_net_profit="8000", init_price="12.5")       # [stocks]
b.account("甲钢铁资金户", owner=a, cash_balance="1000000")  # [stockFundsAccounts]
b.account("操盘手备用金", username="player_a", cash_balance="200000")
b.message("开局公告", "欢迎参赛", to_all=True)              # [messages]
```

- `contract_type` 的四个 JSON 结构沿用合同引擎既有口径（[`apps/contracts/engine.py`](../backend/apps/contracts/engine.py)）：
  `party_roles` / `input_schema` / `effects` / `conditions`；
- **合同名缺省取合同类型名**，与导入侧的判重口径一致；同一合同类型在一场比赛里通常只预置一份，
  区分实例请用参与方的 `contractNumber`；
- `status="DRAFT"` 只预置不落账；`EXECUTED` 会立刻改写公司字段，开赛前请保持草稿；
- 卡片的 `industryFieldId` 是数据库主键，需要回填（见第 6 节）。

### ⑧ 账号与权限

```python
pa = b.user("player_a", role="PLAYER", display_name="甲钢铁操盘手",
            company_scopes=[a], view_company_scopes=[a],
            contract_view_company_scopes=[a], stock_company_scopes=[a])   # [users]
```

- 四套公司范围为空会导致该账号「登录后什么都看不到」，玩家账号至少要给公司范围；
- 导出不含密码：新建账号密码为随机值且强制首次登录改密，需超管重置后交付选手；
- 用户名**全局**唯一：目标库已有同名账号时不覆盖密码、不抢归属，只并入公司范围。

---

## 5. 引用与链式写法

登记方法返回一个 `Ref`，可直接当参数传给别的方法；也可以直接传**名称字符串**
（适用于引用目标比赛里已存在、但不在本包内的对象）：

```python
east = b.region("东区")
b.company("甲", industry_type=steel, region=east)   # 用 Ref
b.company("乙", industry_type=1, region="东区")      # 传 code / 名称也可以
```

构建期的硬错误会立刻抛 `BuilderError`（不会污染数据库）：

- 同类资源重名（与数据库唯一约束一致）；
- 引用了没登记的对象、绑定了没登记的产业字段；
- 连线起终点相同、同一对节点重复连线；
- 计算字段缺计算图、计算字段与定时器互斥；
- 枚举值写错（如仓库种类写成 `"PRODUCTS"`）；
- 产出行里出现列定义之外的字段名（拦住最难查的「字段名打错 → 静默用默认值」）。

`b.validate()` 另外给**提醒**（不阻断）：

- 产业类型缺 `location` 字段；
- 地图节点孤立；
- 科技前置成环；
- 载具没有可通行路径类型；
- 区域总览卡片的字段 id 还是占位 0；
- 消息用了指定收件人（受导入顺序限制，见下）。

---

## 6. 需要知道的既有语义（不是本库的缺陷）

| 现象 | 原因 / 处理 |
| --- | --- |
| 比赛名没被改成脚本里的名字 | 导入侧刻意不改名（避免全局重名冲突），只同步状态与缺失的背景图 |
| 产业类型 / 产业字段 / 合同类型「没新建」 | 它们是**全局资源**，按 `code` / `(code, fieldKey)` / `key` 复用已有记录 |
| 卡片的 `industryFieldId` 是 0，卡片没数据 | 该列是数据库主键，纯代码建包无法凭空得知。用 `b.resolve_field_ids(导出的归档)` 回填后再导一次 |
| 账号导入后登不上 | 密码是随机值且强制首次登录改密，需超管重置 |
| 消息的指定收件人丢了 | 账号在导入顺序里排在消息**之后**，单次导入无法落地收件人；要保留请先导账号、再单独导消息 |
| 跨比赛搬运合同实例 | append 模式会照常导入合同实例（按「比赛 + 合同类型 + 实例名」判重，重复导入不会重复建）。旧版本因把合同实例当作全局「合同类型」的子资源而整类跳过，现已修正（审计 R-02） |
| 股票的 PE 联动字段、资金账户的绑定字段没搬过来 | `pbFieldId` / `bindFieldId` 指向具体主键，跨比赛不搬运，需重新选择 |

### 回填总览卡片字段 id 的完整流程

```powershell
# 1) 先导一次（会把产业类型与字段建出来）
python manage.py build_competition my_competition.py --competition 7

# 2) 从目标库导出「行业口径」分组
#    GET /api/preparations/archive/export?competitionId=7&scope=industry  → industry.json

# 3) 在脚本里回填（build() 里加一行）
#    import json; from pathlib import Path
#    b.resolve_field_ids(json.loads(Path("industry.json").read_text(encoding="utf-8")))

# 4) 再导一次刷新卡片
python manage.py build_competition my_competition.py --competition 7 --mode overwrite
```

---

## 7. 查字段：`--schema`

```powershell
python manage.py build_competition --schema            # 全部资源
python manage.py build_competition --schema companies  # 单个资源
```

也可以看 [`apps/preparation/builder/schema.py`](../backend/apps/preparation/builder/schema.py)
里的 `RESOURCE_SCHEMA`——它是「每类资源有哪些列、哪些必填、哪些是引用、哪些是辅助列」的
自描述表，同时被自动化测试用来双向校验（既拦拼错列名，也保证导出侧新增列时不会漏登记）。

---

## 8. 与其它导入方式的关系

| 方式 | 适用场景 |
| --- | --- |
| `manage.py build_competition <脚本> --competition <id>` | 本地/服务器上用代码建包（推荐） |
| 前端「比赛准备 → 导入归档」 | 手工上传一份归档 JSON |
| `POST /api/preparations/archive/import` | 由外部程序调用（需 `competition:manage` 权限） |
| `manage.py build_competition <归档.json> --competition <id>` | 导入已有归档 |

四者最终都调用同一个 `archive.apply_import`，行为完全一致。

---

## 9. 测试与验证

```powershell
cd backend
.\.venv\Scripts\python.exe manage.py test apps.preparation -v 2
```

测试覆盖（41 条）：

- **对拍**：库的资源顺序与 `archive.IMPORT_ORDER` 完全一致；示例比赛产出的每一列都在 schema 里；
- **零 problem 全量导入**：把覆盖 35 类资源的示例 dry-run 导入，断言没有任何 problem
  ——导入引擎对「引用缺失 / 必填缺失 / 结构不对」都会记 problem，因此这一条等价于
  端到端验证了全部资源的字段口径；
- **dry-run 不留痕**、**真实导入全部落地**、**二次导入幂等**、**全局资源不重复建**；
- **往返**：库 → 导入 → 导出 → 再导入，并断言导出侧的列都在 schema 里有说明（反向查漏）；
- **构建期校验**：重名、引用缺失、字段未登记、计算字段与定时器互斥、零件引用零件、
  科技自环/成环、孤立节点、载具缺路径、连线自环、分组过滤、未知分组等；
- **卡片字段 id 回填**：未回填时报提醒、回填后指向真实字段 id、参照归档不匹配时报错；
- **管理命令**：`--inspect` 不碰库、`--out` 落文件、导入落地、非空比赛默认拒绝、`--schema` 输出。

---

## 10. 新增一类资源时怎么改

1. `apps/preparation/archive.py` 里先有导出/导入函数（本库不改它）；
2. `apps/preparation/builder/core.py`：加进 `RESOURCE_ORDER`（顺序与 `IMPORT_ORDER` 一致）、
   `RESOURCE_LABELS`、`SCOPES`，再写一个登记方法与一个 `_rows_of` 分支；
3. `apps/preparation/builder/schema.py`：加一份 `ResourceSchema`（列定义 + 说明）；
4. 跑测试：`test_resource_order_matches_importer` 与 `test_every_resource_has_label_and_schema`
   会立刻告诉你有没有漏。

导入期还有一道 `_assert_archive_parity()`：一旦资源顺序与 `archive.IMPORT_ORDER` 不一致，
进程启动就会 fail-fast 报错，不会静默丢数据。
