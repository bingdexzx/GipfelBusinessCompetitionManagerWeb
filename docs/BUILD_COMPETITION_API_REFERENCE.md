# 比赛建包库 · 完整 API 手册

> 面向使用者：**每一个方法、每一个参数、每一个取值**都在这份文档里。
> 配套阅读：[用代码创建比赛内容（总览与工作流）](BUILD_COMPETITION_BY_CODE.md)、
> 可直接运行的全量示例 [`backend/examples/competitions/demo_competition.py`](../backend/examples/competitions/demo_competition.py)。
>
> 本文档与代码同步：所有参数名、默认值、枚举取值、归档列名都取自
> `apps/preparation/builder/`，可用 `python manage.py build_competition --schema <资源>` 现场核对。

---

## 目录

1. [30 秒看懂](#1-30-秒看懂)
2. [四个核心概念](#2-四个核心概念)
3. [API 总览](#3-api-总览)
4. [构建器方法逐个讲透](#4-构建器方法逐个讲透)
   - [4.0 构造与比赛基础](#40-构造与比赛基础)
   - [4.1 行业口径（全局资源）](#41-行业口径全局资源)
   - [4.2 参赛主体](#42-参赛主体)
   - [4.3 地理与物流](#43-地理与物流)
   - [4.4 物资与产能](#44-物资与产能)
   - [4.5 科技与需求](#45-科技与需求)
   - [4.6 市场与规则](#46-市场与规则)
   - [4.7 账号与权限](#47-账号与权限)
   - [4.8 对外产出方法](#48-对外产出方法)
5. [命令行 `build_competition`](#5-命令行-build_competition)
6. [辅助函数与常量](#6-辅助函数与常量)
7. [归档列名对照表（35 类资源）](#7-归档列名对照表35-类资源)
8. [报错对照表](#8-报错对照表)
9. [已知边界与注意事项](#9-已知边界与注意事项)
10. [速查卡](#10-速查卡)

---

## 1. 30 秒看懂

```python
# my_competition.py
from apps.preparation.builder import CompetitionBuilder

def build():
    b = CompetitionBuilder("2026 春季赛")
    east  = b.region("东区")
    steel = b.industry_type(1, "钢铁")
    b.add_field(steel, "所在地", "location", field_type="STRING")
    b.company("甲钢铁", industry_type=steel, region=east,
              field_values={"location": "东区港"})
    b.fiscal_year(2026)
    return b
```

```powershell
cd backend
python manage.py build_competition my_competition.py --inspect                  # 只看会建出什么
python manage.py build_competition my_competition.py --competition 7 --dry-run  # 预演（不落库）
python manage.py build_competition my_competition.py --competition 7            # 真正导入
```

一行代码做三件事的规律：**登记一个对象 → 校验必填与引用 → 记住它的名字供别处引用**。
所以方法有两种返回：

| 返回 | 含义 | 能做什么 |
| --- | --- | --- |
| `Ref` | 这个对象的引用（如 `east`、`steel`） | 当参数传给别的方法；`ref.name` 取名字 |
| `self`（构建器本身） | 用于链式调用 | 继续 `.xxx().yyy()`，或作为 `build()` 的返回值 |

---

## 2. 四个核心概念

### 2.1 引用（`Ref`）——怎么把对象连起来

任何「A 引用 B」的参数都接受三种写法，效果完全一样：

```python
east = b.region("东区")

b.company("甲", industry_type=steel, region=east)   # ① Ref：推荐，拼错会立刻报错
b.company("乙", industry_type=1,     region="东区")  # ② 自然键：产业类型用 code
b.company("丙", industry_type=steel, region="东区")  # ③ 名称字符串：区域用名称
```

规则：

- 传 `Ref` 时会检查**类型是否匹配**——把零件的引用传给需要原料的参数会直接报
  「需要 materials 的引用，但拿到的是 parts 的引用」，避免张冠李戴；
- 传字符串时，**必须是本构建器里登记过的名字**（少数例外见 4.2 的 `region`、
  `map_node.region`：它们允许目标库里已存在但不在本包内的名称）；
- 引用目标比赛里已存在、但本包不打算重建的对象时，直接用名称字符串即可。

### 2.2 全局资源 vs 比赛级资源

| 类型 | 有哪些 | 导入时怎么处理 |
| --- | --- | --- |
| **全局**（不属于任何比赛） | 产业类型、产业字段、合同类型 | 按自然键（`code` / `(code, fieldKey)` / `key`）**复用已有记录**，不会重复新建 |
| **比赛级** | 其余 32 类 | 按 `(比赛, 名称)` 幂等：已存在则按模式更新或保留 |

这解释了两个常见疑问：为什么「导入两次没有建出两份产业类型」，以及为什么
「换一场比赛导入，产业字段的 id 没变」。

### 2.3 数值怎么写

金额、股本、价格这类字段是 `Decimal`（60 位精度），**建议写成字符串**：

```python
b.fuel("柴油", price_per_liter="7.5")        # ✅ 字符串，精度可控
b.stock("600001", "甲钢铁", init_price="12.5")
```

传 `int` / `float` 也可以（库原样透传，不强制转换），但 `0.1 + 0.2` 这类浮点误差会
一路带进比赛数据。数量系数（配比 `ratio`）、坐标、加成比例用数字更自然，按需即可。

### 2.4 三重校验

| 时机 | 检查 | 结果 |
| --- | --- | --- |
| **登记时** | 名称重复、必填缺失、引用不存在、枚举值非法、互相矛盾的配置 | 立即抛 `BuilderError`（不碰数据库） |
| **`build()` 时** | 产出行里是否出现列定义之外的字段名（拼错字段名会让导入侧静默用默认值） | 立即抛 `BuilderError` |
| **`validate()`** | 配置风险（缺所在地字段、孤立节点、科技成环、卡片字段 id 未回填…） | 返回提醒列表，不阻断 |

`build()` 内部会自动调用一次 `validate()`，所以在导入前你就有机会看到全部提醒。

---

## 3. API 总览

### 3.1 登记方法（按比赛准备顺序）

| 分组 | 方法 | 产出资源 |
| --- | --- | --- |
| ① 比赛基础 | `CompetitionBuilder(name, ...)` | `competitionMeta` |
| | `fiscal_year(year, ...)` | `fiscalYears` |
| | `stock_config_set(config)` | `stockConfig` |
| ② 行业口径 | `industry_type(code, name, ...)` | `industryTypes` |
| | `add_field(industry_type, name, field_key, ...)` | `industryFields` |
| ③ 参赛主体 | `region(name, ...)` | `regions` |
| | `company(name, ...)` / `add_field_value(...)` | `companies` / `companyFieldValues` |
| ④ 物资与产能 | `fuel` `material` `set_node_prices` `tech` `add_prerequisite` | `fuels` `materials` `techNodes` `techPrerequisites` |
| | `line` `infrastructure` `warehouse` | `productionLines` `infrastructures` `warehouses` |
| | `part` `add_material_ratio` `product` `add_part_ratio` `add_tech_requirement` | `parts` `partMaterials` `partTechRequirements` `products` `productParts` `productTechRequirements` |
| | `vehicle` `add_path_type` | `vehicles` `vehiclePathTypes` |
| ⑤ 地理与物流 | `node_type` `path_type` `node` `edge` | `mapNodeTypes` `pathTypes` `mapNodes` `mapEdges` |
| ⑥ 科技与需求 | （`tech` / `add_prerequisite` 见上） `demand(...)` | `consumerDemands` |
| ⑦ 市场与规则 | `card(...)` | `overviewCards` |
| | `contract_type(...)` / `contract(...)` | `contractTypes` / `contractInstances` |
| | `stock(...)` / `account(...)` | `stocks` / `stockFundsAccounts` |
| | `message(...)` | `messages` |
| ⑧ 账号与权限 | `user(...)` | `users` |

### 3.2 产出与查询方法

| 方法 | 返回 | 用途 |
| --- | --- | --- |
| `build(scope=..., resources=...)` | `dict` | 产出归档 JSON（结构同 `archive.build_export`） |
| `to_json(indent=2, scope=...)` | `str` | 归档 JSON 文本 |
| `save(path, indent=2, scope=...)` | `Path` | 写到文件 |
| `validate()` | `list[str]` | 自检，返回提醒 |
| `resolve_field_ids(reference_archive)` | `self` | 回填总览卡片的 `industryFieldId` |
| `rows(resource)` | `list[dict]` | 看某资源当前产出的行（副本） |
| `names(resource)` | `list[str]` | 看某资源已登记的名字 |

---

## 4. 构建器方法逐个讲透

约定：**加粗**是参数名，`→` 后面是产出的归档列名（见第 7 节）；「必填」表示不传就报错。

---

### 4.0 构造与比赛基础

#### `CompetitionBuilder(name, *, status="ACTIVE", map_background=None, stock_config=None)`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 比赛名。**导入不会改写目标比赛名**（避免全局重名冲突），只在结果里提示差异 |
| **status** | str | `"ACTIVE"` | `ACTIVE` / `CLOSED`，导入时会同步到目标比赛 |
| **map_background** | dict | `None` | 地图背景图 `{"url", "filename", "width", "height"}`；只在目标为空时写入 |
| **stock_config** | dict | `None` | 等价于调用 `stock_config_set()`，一般不用在这里传 |

→ `competitionMeta`：`name` `status` `mapBackground`

```python
b = CompetitionBuilder("2026 春季赛", status="ACTIVE",
                       map_background={"url": "/uploads/map.png", "width": 1920, "height": 1080})
```

#### `fiscal_year(year, *, status="ACTIVE") → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **year** | int | 必填 | 正整数；同一场比赛内年号唯一 |
| **status** | str | `"ACTIVE"` | `ACTIVE` / `CLOSED` |

→ `fiscalYears`：`year` `status`

> **会触发副作用**：新建财年、或把财年从非 `ACTIVE` 改为 `ACTIVE`，会触发 `FY_START`
> 定时器，改写所有「启用了财年开始定时器」的产业字段。请先把字段配好再开财年。

```python
b.fiscal_year(2026)                     # 第 2026 财年，进行中
b.fiscal_year(2025, status="CLOSED")    # 补一个已结束的历史财年
```

#### `stock_config_set(config) → self`

| 参数 | 说明 |
| --- | --- |
| **config** | 非空 dict，键名与 `apps.stock.engine.DEFAULT_STOCK_CONFIG` 一致 |

常用键：`limitPct`（单轮限幅）、`maxMovePct`（单轮最大波动）、`mmMinQty` / `mmMaxQty`
（做市商数量区间）。**约束**：`limitPct ≥ maxMovePct`、`mmMinQty ≤ mmMaxQty`。

→ `stockConfig`：`isDefault`（本库恒为 `False`）、`custom`

> 不调用本方法 = 完全不产出该资源 = 目标比赛沿用原配置。传空字典会报错，
> 因为「什么都不改」的正确表达就是不要调用它。

```python
b.stock_config_set({"limitPct": 0.1, "maxMovePct": 0.08, "mmMinQty": 100, "mmMaxQty": 5000})
```

---

### 4.1 行业口径（全局资源）

#### `industry_type(code, name, *, description=None, icon=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **code** | int | 必填 | 正整数，**全局唯一**，也是跨比赛复用的自然键 |
| **name** | str | 必填 | 显示名 |
| **description** | str | `None` | 描述 |
| **icon** | str | `None` | 图标 |

→ `industryTypes`：`code` `name` `description` `icon`

> 目标库已有同 `code` 的产业类型时：复用该记录；`overwrite` 模式下按本包更新名称/描述/图标，
> `append` 模式下原样保留。**因此 code 不要重复用于不同行业**。

```python
steel = b.industry_type(1, "钢铁", description="钢铁冶炼与加工")
```

#### `add_field(industry_type, name, field_key, *, ...) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **industry_type** | Ref/str | 必填 | 所属产业类型 |
| **name** | str | 必填 | 字段显示名 |
| **field_key** | str | 必填 | 字段键；合同、图表、股票都按它绑定，**开赛后改名会让既有引用失效** |
| **field_type** | str | `"NUMBER"` | `STRING` / `NUMBER` / `BOOLEAN` / `DICTIONARY` / `LIST` |
| **config** | dict | `None` | 类型配置：`DICTIONARY` → `{"entries": [...], "valueType": "..."}`；`LIST` → `{"itemType": "..."}` |
| **default_value** | Any | `None` | 默认值（转成文本存储） |
| **is_calculated** | bool | `False` | 是否由计算图自动推导；**为 `True` 时必须给 `graph`** |
| **graph** | dict | `None` | 计算图（GGraph JSON），见 [6.1](#61-计算图助手) |
| **sort_order** | int | `0` | 界面排序，非 0 才写入 |
| **visible** | bool | `True` | 是否在界面展示；`False` 才写入 |
| **timer_enabled** | bool | `False` | 启用财年定时器；**与 `is_calculated` 互斥** |
| **timer_trigger** | str | `None` | `FY_START` / `FY_END`；`timer_enabled=True` 时必填 |
| **timer_value** | Any | `None` | 定时器写入的值；`timer_enabled=True` 时必填 |

→ `industryFields`：`industryTypeCode` `fieldKey` `name` `fieldType` `config` `defaultValue`
`isCalculated` `calcGraph` `sortOrder` `visible` `timerEnabled` `timerTrigger` `timerValue`

三条硬规则（违反立即报错）：

1. `is_calculated=True` 必须有 `graph`；
2. `is_calculated` 与 `timer_enabled` 不能同时为 `True`；
3. `timer_enabled=True` 必须有 `timer_trigger` 和 `timer_value`。

```python
# 普通字段
b.add_field(steel, "所在地", "location", field_type="STRING", sort_order=1)
b.add_field(steel, "现金", "cash", field_type="NUMBER", default_value="0")

# 计算字段：货币资金 = 现金 + 银行存款
b.add_field(steel, "货币资金", "total_cash", is_calculated=True,
            graph=calc_graph(calc_node("add", node_id="sum"),
                             calc_node("field", node_id="a", fieldKey="cash"),
                             calc_node("field", node_id="b", fieldKey="bank_deposit")))

# 财年定时器字段：每年开始把年度预算重置为 100 万
b.add_field(steel, "年度预算", "annual_budget", timer_enabled=True,
            timer_trigger="FY_START", timer_value="1000000")
```

> **强烈建议**：每个产业类型保留一个 `field_key="location"` 的「所在地」字段。
> 地图与运费逻辑依赖它，区域总览也按它的值（地图节点名）把公司归到区域。
> 缺了它，`validate()` 会提醒。

---

### 4.2 参赛主体

#### `region(name, *, description=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 区域名，同一场比赛内唯一 |
| **description** | str | `None` | 描述 |

→ `regions`：`name` `description`

```python
east = b.region("东区", description="沿海钢铁产业带")
```

#### `company(name, *, industry_type, region=None, status="ACTIVE", field_values=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 公司名，同一场比赛内唯一 |
| **industry_type** | Ref/int | 必填 | 所属产业类型（传 `Ref` 或 `code`）。**决定这家公司有哪些字段** |
| **region** | Ref/str | `None` | 所属区域。本包内没有该区域时，导入侧会**按名称自动建一个** |
| **status** | str | `"ACTIVE"` | `ACTIVE` / `INACTIVE` |
| **field_values** | dict | `None` | `{fieldKey: 值}`，**只能填本包已 `add_field` 登记过的字段** |

→ `companies`：`name` `industryTypeCode` `regionName` `status`
→ `companyFieldValues`（由 `field_values` 自动派生）：`companyId` `companyName` `industryTypeCode` `fieldKey` `value`

```python
a = b.company("甲钢铁集团", industry_type=steel, region=east,
              field_values={"location": "东区港", "cash": "800000", "bank_deposit": "200000"})
c = b.company("丙机械", industry_type=steel, region="西区", status="INACTIVE")
```

> 字段值一律以**文本**写入，NUMBER 字段也建议写字符串（`"800000"`）以保精度。
> 导入按 `(公司, 产业字段)` 幂等：值变了就更新并把乐观锁 `version` +1。

#### `add_field_value(company, field_key, value) → self`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| **company** | Ref/str | 目标公司 |
| **field_key** | str | 产业字段 `fieldKey`（需已登记） |
| **value** | Any | 值，转成文本存储 |

```python
b.add_field_value(a, "bank_deposit", "200000")   # 相当于 company(..., field_values={...}) 的单条版
```

---

### 4.3 地理与物流

#### `node_type(name, *, description=None, color=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 类型名（城市 / 港口 …），同比赛内唯一 |
| **description** | str | `None` | 描述 |
| **color** | str | `None` | 颜色（如 `"#3b82f6"`） |

→ `mapNodeTypes`：`name` `description` `color`

#### `path_type(name, *, description=None, color=None) → Ref`

参数含义同 `node_type`。→ `pathTypes`：`name` `description` `color`

> 路径类型（公路 / 铁路 / 航线）决定**载具能走哪些边**，合同里也有
> 「存在的路径类型」聚合端点。

#### `node(name, node_type, *, region="", x=0, y=0) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 节点名，同比赛内唯一；也是合同里「起始/目的地节点」的展示依据 |
| **node_type** | Ref/str | 必填 | 节点类型（需已登记） |
| **region** | str | `""` | **文本**区域名——注意它不是外键，只是节点上的一个字符串 |
| **x** / **y** | float | `0` | 画布坐标 |

→ `mapNodes`：`name` `nodeTypeName` `region` `x` `y`

```python
port = b.node_type("港口", color="#0ea5e9")
p1 = b.node("东区港", port, region="东区", x=320, y=180)
```

#### `edge(from_node, to_node, distance, path_type) → self`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| **from_node** | Ref/str | 起点节点（需已登记） |
| **to_node** | Ref/str | 终点节点（需已登记）；**不能与起点相同** |
| **distance** | float | 距离 |
| **path_type** | Ref/str | 路径类型（需已登记） |

→ `mapEdges`：`fromNodeName` `toNodeName` `distance` `pathTypeName`

```python
road = b.path_type("公路")
b.edge(p1, p2, 420, road)
b.edge(p2, p1, 430, road)   # 反向是另一条独立连线（唯一约束是「起点+终点」）
```

> 同一对节点**只允许一条**连线；重复登记会报错。
> 没有任何连线的节点不可达，`validate()` 会提醒。

---

### 4.4 物资与产能

#### 依赖方向（重要）

```
原料 material  ──配比──▶  零件 part  ──配比──▶  产品 product  ──▶  消费者需求 demand
```

模型里**没有**「零件用零件」或「产品用产品」的关系，所以：

- `part(materials=...)` 的键只能是**原料**；
- `product(parts=...)` 的键只能是**零件**；
- 写反了会立即报「需要 materials 的引用，但拿到的是 parts 的引用」。

#### `fuel(name, price_per_liter=0) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 燃料名，同比赛内唯一 |
| **price_per_liter** | 数值/字符串 | `0` | 每升单价，参与运费计算 |

→ `fuels`：`name` `pricePerLiter`

> 燃料被载具以外键 `PROTECT` 引用：有载具绑定时不能删除。

#### `material(name, *, origin="", carbon_emission_coefficient=0, type="NORMAL", node_prices=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 原料名，同比赛内唯一；是配比/库存字典的键 |
| **origin** | str | `""` | 产地（通常填地图节点名） |
| **carbon_emission_coefficient** | float | `0` | 碳排放系数 |
| **type** | str | `"NORMAL"` | `NORMAL` / `SPECIAL` |
| **node_prices** | dict | `None` | 地点价 `{地图节点: 价格}`，键可以是 `Ref` 或节点名；节点必须已登记 |

→ `materials`：`name` `origin` `carbonEmissionCoefficient` `type` `nodePricesByName`

```python
iron = b.material("铁矿石", origin="北山矿", carbon_emission_coefficient=0.52,
                  node_prices={mine: "120", port: "138"})
```

#### `set_node_prices(material, prices) → Ref`

给已登记的原料补/改地点价，参数与 `node_prices` 相同。

```python
b.set_node_prices(iron, {"北山矿": "118", "东区港": "140"})   # 整份替换
```

> 导入侧**按节点名**重建为 `{地图节点id: 价格}`，所以地点价能跨比赛独立导入；
> 目标比赛里没有同名节点时，该条地点价会被丢弃并在结果里提示。

#### `tech(name, *, tier=0, research_cost=0, description=None, prerequisites=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 节点名，同比赛内唯一 |
| **tier** | int | `0` | 层级（非负整数） |
| **research_cost** | 数值/字符串 | `0` | 研发费用 |
| **description** | str | `None` | 说明 |
| **prerequisites** | 列表 | `None` | 前置科技节点（`Ref` 或名称）列表 |

→ `techNodes`：`name` `tier` `researchCost` `description`
→ `techPrerequisites`（由 `prerequisites` 自动派生）：`nodeId` `prerequisiteId`

```python
t1 = b.tech("高炉冶炼", tier=1, research_cost="5000")
t2 = b.tech("热轧工艺", tier=2, research_cost="12000", prerequisites=[t1])
```

#### `add_prerequisite(node, prerequisite) → self`

追加一条「`node` 依赖 `prerequisite`」。同一条不重复登记；自环报错；成环由 `validate()` 提醒。

> **口径差异**：科技前置在导入侧**只认旧 id，没有按名兜底**，所以本库产出的
> `techPrerequisites` 里写的是 `nodeId` / `prerequisiteId`（登记时自动换算），
> 不是名字。这也是唯一一处与其他资源不同的地方。

#### `line(name, *, price=0, labor_count=0, max_per_year=0) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 生产线名，同比赛内唯一 |
| **price** | 数值/字符串 | `0` | 单价 |
| **labor_count** | int | `0` | 用工人数（非负整数） |
| **max_per_year** | 数值/字符串 | `0` | 年产能 |

→ `productionLines`：`name` `price` `laborCount` `maxPerYear`

#### `infrastructure(name, *, footprint=0, price=0, activation_price=0, employment_rate_bonus=0, population_bonus=0, high_quality_population_bonus=0, happiness_index_bonus=0, per_capita_income_bonus=0, carbon_reduction_bonus=0) → Ref`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| **name** | 必填 | 基建名，同比赛内唯一 |
| **footprint** | `0` | 占地面积 |
| **price** | `0` | 单价 |
| **activation_price** | `0` | 启用费用 |
| **employment_rate_bonus** | `0` | 就业率加成（`0.05` = +5%） |
| **population_bonus** | `0` | 人口加成 |
| **high_quality_population_bonus** | `0` | 高素质人口加成 |
| **happiness_index_bonus** | `0` | 幸福度加成 |
| **per_capita_income_bonus** | `0` | 人均收益加成 |
| **carbon_reduction_bonus** | `0` | 减碳加成 |

→ `infrastructures`：`name` `footprint` `price` `activationPrice` `employmentRateBonus`
`populationBonus` `highQualityPopulationBonus` `happinessIndexBonus` `perCapitaIncomeBonus` `carbonReductionBonus`

> 这些加成是合同「基建各项加成」聚合端点的数据来源，填了就有用。

#### `warehouse(name, type, *, capacity=0, price=0) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 仓库名，同比赛内唯一 |
| **type** | str | 必填 | `MATERIAL` / `PART` / `PRODUCT` / `FUEL` |
| **capacity** | 数值/字符串 | `0` | 容量 |
| **price** | 数值/字符串 | `0` | 单价 |

→ `warehouses`：`name` `type` `capacity` `price`

> 四种种类建议都覆盖，否则对应物资无处存放。

#### `part(name, *, materials=None, tech=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 零件名，同比赛内唯一 |
| **materials** | dict | `None` | `{原料: 数量系数}`，键只能传 `Ref` 或原料名 |
| **tech** | 列表 | `None` | 所需科技节点（`Ref` 或名称）列表 |

→ `parts`：`name`
→ `partMaterials`：`partName` `materialName` `ratio`
→ `partTechRequirements`：`partName` `techNodeName`

```python
p_iron = b.part("铁锭", materials={iron: 2, coal: 1}, tech=[t1])
```

#### `add_material_ratio(part, material, ratio) → self`

| 参数 | 说明 |
| --- | --- |
| **part** | 零件（已登记） |
| **material** | 原料（已登记） |
| **ratio** | 数量系数 |

同一对「零件-原料」不重复登记（重复会报错）。

#### `product(name, *, parts=None, tech=None) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 产品名，同比赛内唯一 |
| **parts** | dict | `None` | `{零件: 数量系数}` |
| **tech** | 列表 | `None` | 所需科技节点列表 |

→ `products`：`name`
→ `productParts`：`productName` `partName` `ratio`
→ `productTechRequirements`：`productName` `techNodeName`

#### `add_part_ratio(product, part, ratio) → self`

参数与 `add_material_ratio` 对应，作用在「产品-零件」配比上。

#### `add_tech_requirement(item, tech_node) → self`

| 参数 | 说明 |
| --- | --- |
| **item** | 零件**或**产品（`Ref` 或名称）；库会自动判断类型 |
| **tech_node** | 科技节点（已登记） |

同一条需求重复登记会被幂等忽略。

#### `vehicle(name, *, fuel, path_types=None, fuel_consumption_per_km=0, max_cargo=0, price=0, carbon_emission=0) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 载具名，同比赛内唯一 |
| **fuel** | Ref/str | **必填** | 绑定燃料（模型是 `PROTECT` 外键，不能为空） |
| **path_types** | 列表 | `None` | 可通行的路径类型列表 |
| **fuel_consumption_per_km** | float | `0` | 每公里油耗 |
| **max_cargo** | float | `0` | 载货量 |
| **price** | 数值/字符串 | `0` | 单价 |
| **carbon_emission** | float | `0` | 碳排放系数 |

→ `vehicles`：`name` `fuelName` `fuelConsumptionPerKm` `maxCargo` `price` `carbonEmission`
→ `vehiclePathTypes`：`vehicleName` `pathTypeName`

> 一条可通行路径类型都没有时，该载具的运输路径校验会失败，`validate()` 会提醒。

#### `add_path_type(vehicle, path_type) → self`

给载具追加一种可通行路径类型；重复登记幂等忽略。

---

### 4.5 科技与需求

#### `demand(region, product, quantity, *, note=None) → self`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **region** | str | 必填 | 区域名（**文本**，建议与 `region()` 的名字一致） |
| **product** | Ref/str | 必填 | 产品（需已登记，否则会报错——产品不存在玩家无法交付） |
| **quantity** | int | 必填 | 需求量（非负整数） |
| **note** | str | `None` | 备注 |

→ `consumerDemands`：`region` `productType` `productName` `quantity` `note`

> 导入按 `(比赛, 区域, 产品, 数量)` 幂等去重——所以**「改需求量」等于新增一条**，
> 而不是修改原来那条。调需求时请想清楚是否要清掉旧记录。

```python
b.demand("东区", plate, 1200, note="基建用钢")
b.demand("西区", rebar, 900)
```

---

### 4.6 市场与规则

#### `card(region, company, field_key, *, display_name=None, zone=None, card_id=None) → self`

给区域登记一张总览卡片。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **region** | Ref/str | 必填 | 卡片所属区域（需已登记） |
| **company** | Ref/str | 必填 | 卡片展示哪家公司的字段（需已登记） |
| **field_key** | str | 必填 | 展示哪个产业字段（需已登记） |
| **display_name** | str | `None` | 卡片标题，缺省用 `field_key` |
| **zone** | str | `None` | 分区标记（可选） |
| **card_id** | str | `None` | 卡片 id，缺省生成 `"{区域}-{公司}-{fieldKey}"`（稳定、可重复） |

→ `overviewCards`：`regionName` `cards`（`[{id, displayName, companyId, industryFieldId, zone?}]`）

> **关键点**：卡片里的 `industryFieldId` 是**数据库主键**。产业字段是全局资源、
> 跨比赛复用，纯代码建包无法凭空知道这个 id，所以：
>
> - 未回填时写入占位值 `0`，`validate()` 会提醒（卡片会取不到值，但不会报错）；
> - 用 [`resolve_field_ids()`](#resolve_field_idsreference_archive--self) 从真实归档里回填。
>
> 重复调用 `card()` 会自动把卡片合并到同一区域的 `cards` 数组里。

#### `contract_type(key, name, *, description=None, party_roles=None, input_schema=None, effects=None, conditions=None, graph=None, enabled=True) → Ref`

登记一个**全局**合同类型（按 `key` 复用/更新）。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **key** | str | 必填 | 全局唯一 key |
| **name** | str | 必填 | 类型名称 |
| **description** | str | `None` | 说明 |
| **party_roles** | list | `None` | 参与方角色，见下 |
| **input_schema** | list | `None` | 需要填写的输入项，见下 |
| **effects** | list | `None` | 落账效果，见下 |
| **conditions** | list | `None` | 前置检查，见下 |
| **graph** | dict | `None` | 可视化图结构（前端「可视化新建」的产物，纯代码一般留空） |
| **enabled** | bool | `True` | 是否启用 |

→ `contractTypes`：`key` `name` `description` `partyRoles` `inputSchema` `effects` `conditions` `graph` `enabled`

四个 JSON 结构沿用合同引擎既有口径（`apps/contracts/engine.py`）：

```python
party_roles   = [{"role": "seller", "label": "卖方"},
                 {"role": "bank",   "label": "银行", "isHost": True}]
                 # role 必填且需与 effects/conditions 里的 party 对应
                 # isHost=True 表示主办方（虚拟参与方，不选公司）

input_schema  = [{"key": "amount", "label": "金额", "type": "NUMBER",
                  "required": True, "default": 0}]

effects       = [{"kind": "FIELD", "party": "buyer", "fieldKey": "cash",
                  "op": "SUB",                      # ADD 增加 / SUB 扣减 / SET 设定
                  "value": {"from": "input", "key": "amount"}}]

conditions    = [{"kind": "FIELD", "party": "buyer", "fieldKey": "cash",
                  "op": "GTE",                      # 大于等于
                  "value": {"from": "input", "key": "amount"}}]
```

> `party_roles` 的个数会决定合同需要几个参与方；`conditions` 是签约前的前置检查，
> `effects` 是执行时对产业字段的读写。**建议保存后用前端的「试算」验证一遍**。

#### `contract(name=None, *, contract_type, parties=None, inputs=None, status="DRAFT") → Ref`

登记一个比赛级合同实例（预设合同）。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 缺省取**合同类型名** | 合同名；同一合同类型下唯一 |
| **contract_type** | Ref/str | 必填 | 合同类型（`Ref` 或 `key`） |
| **parties** | list | `None` | 参与方，见下 |
| **inputs** | dict | `None` | 已填写的输入参数 |
| **status** | str | `"DRAFT"` | `DRAFT` / `PENDING_EXEC` / `EXECUTED` / `TERMINATED` |

→ `contractInstances`：`name` `contractTypeKey` `status` `parties` `inputs`

```python
parties = [{"role": "seller", "company": a, "contractNumber": "S-2026-001"},
           {"role": "buyer",  "company": c, "contractNumber": "B-2026-001"}]
```

`parties` 每项：

| 键 | 必填 | 说明 |
| --- | --- | --- |
| `role` | 是 | 必须与 `party_roles` 里的 `role` 对应 |
| `company` | 是 | 公司 `Ref` 或名称；公司不在本包时导入侧会把该方公司置空并提示 |
| `contractNumber` | 否 | 合同编号（参与方各自填写，用于识别具体单据） |
| `isHost` | 否 | 该方是否主办方 |

> **判重口径**：导入侧按 `(比赛, 合同类型, 名称)` 幂等，而名称缺省就是合同类型名，
> 所以**同一合同类型在一场比赛里通常只预置一份**；要区分不同单据请用
> `contractNumber`，而不是给 `contract(name=...)` 传不同名字（那样导入侧仍按类型名判重）。
>
> **状态警告**：`status="EXECUTED"` 会立刻改写公司字段并落账。开赛前请保持 `DRAFT`。

#### `stock(code, name, *, ...) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **code** | str | 必填 | 股票代码，同比赛内唯一（自然键） |
| **name** | str | 必填 | 股票名称 |
| **company** | Ref/str | `None` | 关联公司（使股票与公司经营数据联动） |
| **total_shares** | 数值/字符串 | `0` | 总股本 |
| **init_net_profit** | 数值/字符串 | `0` | 初始净利润 |
| **init_price** | 数值/字符串 | `0` | 初始价格 |
| **current_price** | 数值/字符串 | `None` | 当前价格；不填则取 `init_price` |
| **industry_pe** | float | `0` | 行业 PE |
| **current_carbon** | float | `0` | 当前碳排 |
| **industry_avg_carbon** | float | `0` | 行业平均碳排 |
| **happiness** | float | `0` | 幸福度 |
| **round** | int | `0` | 当前轮次 |
| **carbon_field_ref** | str | `None` | 碳排绑定的总览卡片引用字符串，如 `'{"region":"东区","cardId":"东区-甲钢铁-cash"}'` |
| **happiness_field_ref** | str | `None` | 幸福度绑定的卡片引用字符串 |
| **industry_avg_carbon_refs** | str | `None` | 行业碳排均值绑定的卡片引用数组字符串 |
| **pb_company** | Ref/str | `None` | 行业 PE 联动的公司 |
| **pb_random** | float | `None` | PE 随机模式参数 |

→ `stocks`：`code` `name` `companyName` `totalShares` `initNetProfit` `initPrice`
`currentPrice` `industryPe` `currentCarbon` `industryAvgCarbon` `happiness` `round`
`carbonFieldRef` `happinessFieldRef` `industryAvgCarbonRefs` `pbCompanyId` `pbRandom`

> 三个 `*_ref` 参数本库**原样透传**，不做解析。请先用 `card()` 建好卡片，
> 再把卡片的 `cardId` 拼进去。
>
> `pbFieldId`（PE 联动的字段绑定）与 `bindFieldId` 指向具体主键，跨比赛不搬运，
> 需在导入后重新选择。

```python
b.stock("600001", "甲钢铁", company=a, total_shares="12000",
        init_net_profit="8000", init_price="12.5", industry_pe=15.0)
```

#### `account(name, *, owner=None, username=None, cash_balance=1000000) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **name** | str | 必填 | 账户名，同比赛内唯一 |
| **owner** | Ref/str | `None` | 归属公司（公司账户）；与 `username` **二选一** |
| **username** | str | `None` | 归属用户名（用户账户）；该用户名必须已 `user()` 登记 |
| **cash_balance** | 数值/字符串 | `1000000` | 现金余额 |

→ `stockFundsAccounts`：`name` `ownerType` `companyName` / `username` `cashBalance`

```python
b.account("甲钢铁资金户", owner=a, cash_balance="1000000")
b.account("操盘手备用金", username="player_a", cash_balance="200000")
```

> 两者都不传或都传都会报错。

#### `message(title, content="", *, to_all=True, to_users=None, sender=None) → self`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **title** | str | 必填 | 标题 |
| **content** | str | `""` | 正文 |
| **to_all** | bool | `True` | 是否面向全体 |
| **to_users** | 列表 | `None` | 指定收件人用户名列表（需已 `user()` 登记） |
| **sender** | str | `None` | 发布者用户名；不填则用导入时的操作账号 |

→ `messages`：`title` `content` `targetsAll` `targetUserIds` `senderUsername`

> **限制**：账号在导入顺序里排在消息**之后**，所以**单次导入**时指定收件人无法落地
> （导入结果里会有提示）。要保留指定收件人，请分两次导入：先导账号，再单独导消息。
> `validate()` 检测到这种用法会提醒。

---

### 4.7 账号与权限

#### `user(username, *, role="PLAYER", display_name=None, company_scopes=None, view_company_scopes=None, contract_view_company_scopes=None, stock_company_scopes=None, permissions=None, is_active=True) → Ref`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **username** | str | 必填 | 用户名，**全局唯一**（跨比赛） |
| **role** | str | `"PLAYER"` | `SUPER_ADMIN` / `COMPETITION_ADMIN` / `PLAYER` |
| **display_name** | str | `None` | 显示名 |
| **company_scopes** | 列表 | `None` | **公司管理范围**（决定能改哪些公司、以及合同执行权） |
| **view_company_scopes** | 列表 | `None` | 查看范围 |
| **contract_view_company_scopes** | 列表 | `None` | 合同查看范围 |
| **stock_company_scopes** | 列表 | `None` | 股票范围 |
| **permissions** | 列表 | `None` | 细粒度权限键数组；不填表示按角色继承 |
| **is_active** | bool | `True` | 是否启用 |

→ `users`：`username` `role` `displayName` `permissions` `isActive`
+ `companyScopes` / `viewCompanyScopes` / `contractViewCompanyScopes` / `stockCompanyScopes`
+ 对应的 `*ScopeNames`（供跨分组按公司名兜底解析）

四个范围参数都接受「`Ref` 列表 / 名称列表 / 单个值」，库会去重并展开成名称数组。

```python
pa = b.user("player_a", role="PLAYER", display_name="甲钢铁操盘手",
            company_scopes=[a], view_company_scopes=[a],
            contract_view_company_scopes=[a], stock_company_scopes=[a])

b.user("referee", role="COMPETITION_ADMIN", display_name="本场裁判",
       company_scopes=[a, b_steel, c],
       permissions=["contract:manage", "contract:audit", "contract:execute"])
```

> **最容易被忽略的一点**：四套范围为空 → 该账号「登录后什么都看不到」。
> 玩家账号至少要给 `company_scopes`。
>
> **导入语义**：用户名全局唯一。目标库已有同名账号时**不覆盖密码、不抢比赛归属**，
> 只把公司范围**并入**；新建账号密码为随机值且强制首次登录改密，需超管重置后再交付选手。
>
> 权限键的完整清单见 `apps/common/permissions.py` 的 `PERMISSION_CATALOG`。

---

### 4.8 对外产出方法

#### `build(*, scope=None, resources=None) → dict`

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| **scope** | str | `None` | 只产出某个分组：`competition` / `industry` / `company` / `supply` / `geo` / `tech` / `market` / `access` / `all` |
| **resources** | 列表 | `None` | 更细粒度：只产出这些资源名（如 `["companies", "companyFieldValues"]`） |

返回的结构与 `archive.build_export` 完全一致：

```python
{
  "schemaVersion": 1,
  "generator": "gipfel-preparation-builder",
  "exportedAt": "2026-01-01 12:00:00",
  "scope": "all",
  "scopeLabel": "全部准备数据",
  "sourceCompetition": {"id": None, "name": "2026 春季赛"},
  "resources": {
    "companies": {"label": "公司", "count": 3, "rows": [{"_id": 1, "name": "甲钢铁", ...}]},
    ...
  }
}
```

内部顺序：先 `validate()`，再逐资源产出并做**列名自检**（出现未登记列名立即报错）。
空资源不会出现在结果里。

#### `to_json(*, indent=2, scope=None) → str` / `save(path, *, indent=2, scope=None) → Path`

```python
text = b.to_json()                       # JSON 文本
b.save("spring-2026.json")               # 写文件（父目录会自动创建）
b.save("companies.json", scope="company")  # 只导出「参赛主体」分组
```

#### `validate() → list[str]`

返回**提醒**列表（不是错误）。检查七类问题：

| # | 检查 | 提醒文案要点 |
| --- | --- | --- |
| 1 | 产业类型缺 `location` 字段 | 地图/运费/区域总览依赖它 |
| 2 | 地图节点孤立（无任何连线） | 不可达，运费计算会失败 |
| 3 | 科技前置成环 | 这些节点永远无法解锁 |
| 4 | 载具没有可通行路径类型 | 运输路径校验会失败 |
| 5 | 卡片的 `industryFieldId` 仍是占位 0 | 需 `resolve_field_ids()` 回填 |
| 6 | 消息用了指定收件人 | 受导入顺序限制，需分两次导入 |
| 7 | （硬错误）公司未绑定产业类型 | 直接抛 `BuilderError` |

#### `resolve_field_ids(reference_archive) → self`

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| **reference_archive** | dict | 一份**已导出**的归档（`resources.industryTypes` + `resources.industryFields`） |

按 `(产业类型 code, fieldKey)` 查出真实字段 id，回填到所有已登记卡片。找不到时抛
`BuilderError`（不会留下 0 让卡片静默失效）。可在 `card()` 之前或之后调用，也可以反复调用。

```python
import json
from pathlib import Path

def build():
    b = CompetitionBuilder("2026 春季赛")
    ...
    # 若目标库已有这些产业字段（即导入过「行业口径」分组），回填卡片的字段 id
    ref = Path("industry.json")
    if ref.exists():
        b.resolve_field_ids(json.loads(ref.read_text(encoding="utf-8")))
    return b
```

完整两遍流程见 [总览文档第 6 节](BUILD_COMPETITION_BY_CODE.md#6-需要知道的既有语义不是本库的缺陷)。

#### `rows(resource) → list[dict]` / `names(resource) → list[str]`

```python
b.rows("companies")        # [{"_id": 1, "name": "甲钢铁", "industryTypeCode": 1, ...}, ...]
b.names("regions")         # ["东区", "西区"]
```

`rows()` 返回的是副本，改它不会影响构建器。

---

## 5. 命令行 `build_competition`

```
python manage.py build_competition [source] [选项]
```

### 5.1 位置参数

| 参数 | 说明 |
| --- | --- |
| **source** | 建包脚本（`.py`）或归档文件（`.json`）。给 `.json` 时跳过建包，直接走导入。省略时必须配合 `--schema` |

### 5.2 选项

| 选项 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--competition <id>` | int | 无 | 目标比赛 id。**导入必需**；只做 `--inspect` / `--out` 时不需要 |
| `--dry-run` | 开关 | 关 | 预演：事务回滚，返回与真实导入一致的结果，一行都不落库 |
| `--mode <append\|overwrite>` | 枚举 | `append` | `append` 只补缺（已存在原样保留）；`overwrite` 按本包更新已存在记录 |
| `--resources a,b,c` | 字符串 | 全部 | 只导入指定资源名，如 `companies,companyFieldValues` |
| `--scope <分组>` | 枚举 | 全部 | 只产出/导入某个分组。会同时限制「脚本产出」与「导入范围」 |
| `--allow-non-empty` | 开关 | 关 | 允许导入到已有业务数据的比赛 |
| `--out <path>` | 路径 | 无 | 把产出的归档 JSON 写文件（不连数据库） |
| `--inspect` | 开关 | 关 | 只打印产出摘要，不做任何导入 |
| `--schema [资源名]` | 字符串 | 无 | 打印字段字典；不给资源名则打印全部 |

### 5.3 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 出现了 problem（有数据没落地），或脚本/构建错误 |
| 非 0（`CommandError`） | 被拒绝（如目标比赛非空且未加 `--allow-non-empty`）、文件不存在、参数非法 |

> 因为 problem 会返回非零码，这个命令可以直接放进部署脚本/CI 做「建包即校验」。

### 5.4 脚本格式（五种写法任选）

命令按下面的顺序查找，命中即用：

```python
# ① 推荐：build() 返回构建器
def build():
    return CompetitionBuilder("比赛名")

# ② 模块级构建器
BUILDER = CompetitionBuilder("比赛名")

# ③ 模块级归档 dict（已构造好的归档，直接导入）
ARCHIVE = {"schemaVersion": 1, "resources": {...}}

# ④ 最后一行是一个构建器表达式（命令会捕获最后创建的构建器）
CompetitionBuilder("比赛名").region("东区")

# ⑤ build() 直接返回归档 dict
def build():
    return {"schemaVersion": 1, "resources": {...}}
```

脚本里用绝对导入即可：`from apps.preparation.builder import CompetitionBuilder`
（命令已把项目根目录加入 `sys.path`，且 Django 已初始化）。

### 5.5 常用组合

```powershell
# 本地评审一份建包脚本：打印摘要 + 存成 JSON 交给人审
python manage.py build_competition my.py --inspect --out review.json

# CI 校验：预演导入，有问题就非零退出
python manage.py build_competition my.py --competition 7 --dry-run

# 只补账号，不动其他数据
python manage.py build_competition my.py --competition 7 --resources users

# 只重建「物资与产能」，覆盖已存在记录
python manage.py build_competition my.py --competition 7 --scope supply --mode overwrite

# 导入别人给的归档文件
python manage.py build_competition 归档.json --competition 7 --dry-run
```

---

## 6. 辅助函数与常量

### 6.1 计算图助手

```python
from apps.preparation.builder import calc_node, calc_graph
```

**`calc_node(node_type, *, node_id=None, **config) → dict`**

| 参数 | 说明 |
| --- | --- |
| **node_type** | 短名：`add` `sub` `mul` `div` `field` `const` `sum` `avg` `max` `min`；也可直接写原始类型名 |
| **node_id** | 节点唯一 id；不填时用类型小写（如 `"add"`）。**多个同类型节点必须手动给不同 id** |
| ****config** | 透传给节点的配置，如 `fieldKey=`、`value=`、`scope=` |

**`calc_graph(*nodes, edges=None, **extra) → dict`**

| 参数 | 说明 |
| --- | --- |
| **\*nodes** | 若干 `calc_node(...)`；至少一个 |
| **edges** | 连线 `[{"from": ..., "to": ..., "fromPort": ..., "toPort": ...}]`。**省略时按传入顺序自动串成一条链**（第一个为根） |
| ****extra** | 透传到图对象上的额外键 |

```python
# 单输入：货币资金 = 现金
calc_graph(calc_node("add"), calc_node("field", fieldKey="cash"))

# 两输入相加（节点 id 必须唯一，这里手动指定）
calc_graph(calc_node("add", node_id="sum"),
           calc_node("field", node_id="a", fieldKey="cash"),
           calc_node("field", node_id="b", fieldKey="bank_deposit"))

# 自己写连线：两个字段分别进 add 的 in1 / in2
calc_graph(calc_node("add", node_id="sum"),
           calc_node("field", node_id="a", fieldKey="cash"),
           calc_node("field", node_id="b", fieldKey="bank_deposit"),
           edges=[{"from": "a", "to": "sum", "fromPort": "out", "toPort": "in1"},
                  {"from": "b", "to": "sum", "fromPort": "out", "toPort": "in2"}])
```

> 复杂的多输入图建议直接在前端「产业计算图」里搭好，再把导出的 `graph` JSON 抄进脚本。

### 6.2 异常

```python
from apps.preparation.builder import BuilderError
```

`BuilderError` 表示**写脚本时**的错误（重名、引用缺失、必填缺失、枚举非法、配置矛盾、
列名拼错）。它发生在 `build()` 之前或之中，**不会污染数据库**。
与「导入阶段」的 `archive.ArchiveError`（归档结构非法）分工不同。

### 6.3 常量

| 常量 | 内容 | 来源 |
| --- | --- | --- |
| `FIELD_TYPES` | `("STRING", "NUMBER", "BOOLEAN", "DICTIONARY", "LIST")` | `builder.types` |
| `TIMER_TRIGGERS` / `TIMER_FY_START` / `TIMER_FY_END` | `("FY_START", "FY_END")` | `builder.types` |
| `CALC_TYPES` | 计算图短名 → 原始类型名 | `builder.types` |
| `RESOURCE_ORDER` | 35 类资源的产出顺序（与 `archive.IMPORT_ORDER` 一致） | `builder.core` |
| `RESOURCE_LABELS` | 资源名 → 中文名 | `builder.core` |
| `SCOPES` | 分组 → 资源名元组 | `builder.core` |
| `RESOURCE_SCHEMA` | 资源名 → `ResourceSchema`（列定义） | `builder.schema` |
| `SCHEMA_VERSION` / `GENERATOR` | 归档结构版本 / 生成器标识 | `builder.core` |

模块内的枚举取值（写错立即报错）：

| 常量 | 取值 |
| --- | --- |
| `COMPETITION_STATUSES` | `ACTIVE` `CLOSED` |
| `COMPANY_STATUSES` | `ACTIVE` `INACTIVE` |
| `MATERIAL_TYPES` | `NORMAL` `SPECIAL` |
| `WAREHOUSE_TYPES` | `MATERIAL` `PART` `PRODUCT` `FUEL` |
| `CONTRACT_STATUSES` | `DRAFT` `PENDING_EXEC` `EXECUTED` `TERMINATED` |
| `USER_ROLES` | `SUPER_ADMIN` `COMPETITION_ADMIN` `PLAYER` |

### 6.4 一致性自检

```python
from apps.preparation.builder import assert_archive_parity   # 实际从 core 导出
```

校验 `RESOURCE_ORDER` 与 `archive.IMPORT_ORDER` 是否一致。**模块导入时已自动执行一次**
（fail-fast），一般不需要手动调用；写自定义工具时可用它做前置断言。

---

## 7. 归档列名对照表（35 类资源）

**这一节是给「想直接改 JSON」或「排查导入为什么跳过某行」的人看的。**
正常使用不需要关心列名——建包方法会自动填对。

标记含义：

- **必填**：导入侧缺了会跳过该行或产生错误数据；
- **自然键**：导入侧按它判断「已存在」，用它去重复用记录；
- **引用**：该列指向另一类资源的旧 id（`_id`），库按名称自动填；
- **辅助**：给导入侧做跨分组按名兜底用，不是模型字段。

每类资源都有 `_id`（旧 id，导入时由引擎映射成新主键），下表不再重复列出。

### ① 比赛基础

| 资源 | 建包方法 |
| --- | --- |
| `competitionMeta` | `CompetitionBuilder(...)` |
| `fiscalYears` | `fiscal_year(...)` |
| `stockConfig` | `stock_config_set(...)` |

| competitionMeta | 必填 | 说明 |
| --- | :---: | --- |
| `name` | | 比赛名称（导入**不会**改写目标比赛名，仅提示差异） |
| `status` | | `ACTIVE` / `CLOSED`；导入会同步目标比赛状态 |
| `mapBackground` | | 地图背景图；只在目标为空时写入 |

| fiscalYears | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `year` | 是 | 是 | 财年年份 |
| `status` | | | `ACTIVE` / `CLOSED` |

| stockConfig | 说明 |
| --- | --- |
| `isDefault` | `true` 表示回到系统默认 |
| `custom` | 自定义参数对象 |

### ② 行业口径（全局）

| industryTypes | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `code` | 是 | 是 | 全局唯一整数 |
| `name` / `description` / `icon` | | | 显示信息 |

| industryFields | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `industryTypeCode` | 是 | | 所属产业类型 code |
| `fieldKey` | 是 | 是 | 字段键（与产业类型组成复合自然键） |
| `name` | | | 字段显示名 |
| `fieldType` | | | `STRING`/`NUMBER`/`BOOLEAN`/`DICTIONARY`/`LIST` |
| `config` | | | 类型配置 |
| `defaultValue` | | | 默认值 |
| `isCalculated` | | | 是否计算字段 |
| `calcGraph` | | | 计算图（`isCalculated=true` 时必填） |
| `sortOrder` / `visible` | | | 排序 / 是否展示 |
| `timerEnabled` / `timerTrigger` / `timerValue` | | | 财年定时器 |

| contractTypes | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `key` | 是 | 是 | 全局唯一 key |
| `name` / `description` | | | 显示信息 |
| `partyRoles` | | | `[{role, label, selectable?, isHost?}]` |
| `inputSchema` | | | `[{key, label, type, required?, default?}]` |
| `effects` | | | `[{kind:"FIELD", party, fieldKey, op, value}]` |
| `conditions` | | | `[{kind:"FIELD", party, fieldKey, op, value}]` |
| `graph` / `enabled` | | | 可视化图 / 是否启用 |

### ③ 参赛主体

| companies | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 公司名 |
| `industryTypeCode` | 是 | | 所属产业类型 code |
| `regionName` | | | 区域名（不存在会按名自动建） |
| `status` | | | `ACTIVE` / `INACTIVE` |

| companyFieldValues | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `companyId` | | companies | 公司旧 id |
| `companyName` | | | 公司名（辅助） |
| `industryTypeCode` | 是 | | 字段所属产业类型 code |
| `fieldKey` | 是 | | 产业字段 fieldKey |
| `value` | | | 字段值（文本） |
| `version` | | | 乐观锁版本号（引擎维护） |

### ⑤ 地理与物流

| mapNodeTypes / pathTypes | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 类型名 |
| `description` / `color` | | | 描述 / 颜色 |

| mapNodes | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 节点名 |
| `nodeTypeName` | 是 | | 节点类型名 |
| `region` | 是 | | 区域名（**文本列**） |
| `x` / `y` | | | 坐标 |

| mapEdges | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `fromNodeName` / `toNodeName` | 是 | mapNodes | 端点节点名（唯一约束是这对） |
| `distance` | 是 | | 距离 |
| `pathTypeName` | 是 | pathTypes | 路径类型名 |

### ④ 物资与产能

| fuels | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 燃料名 |
| `pricePerLiter` | | | 每升单价 |

| materials | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 原料名 |
| `origin` / `carbonEmissionCoefficient` / `type` | | | 产地 / 碳排系数 / `NORMAL`\|`SPECIAL` |
| `nodePricesByName` | | | 地点价 `{节点名: 价格}`（推荐口径） |
| `nodePrices` | | | 地点价 `{节点旧id: 价格}`（导出侧口径） |

| techNodes | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 节点名 |
| `tier` / `researchCost` / `description` | | | 层级 / 研发费用 / 说明 |

| techPrerequisites | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `nodeId` | 是 | techNodes | 节点旧 id（**此资源导入侧无按名兜底**） |
| `prerequisiteId` | 是 | techNodes | 前置节点旧 id |

| infrastructures | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 基建名 |
| `footprint` / `price` / `activationPrice` | | | 占地 / 单价 / 启用费 |
| `employmentRateBonus` / `populationBonus` / `highQualityPopulationBonus` | | | 就业率 / 人口 / 高素质人口加成 |
| `happinessIndexBonus` / `perCapitaIncomeBonus` / `carbonReductionBonus` | | | 幸福度 / 人均收益 / 减碳加成 |

| productionLines | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 生产线名 |
| `price` / `laborCount` / `maxPerYear` | | | 单价 / 用工人数 / 年产能 |

| warehouses | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 仓库名 |
| `type` | 是 | | `MATERIAL`/`PART`/`PRODUCT`/`FUEL` |
| `capacity` / `price` | | | 容量 / 单价 |

| parts / products | 必填 | 自然键 | 说明 |
| --- | :---: | :---: | --- |
| `name` | 是 | 是 | 名称（模型只有名字，关系在下面的子资源里） |

| partMaterials / productParts | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `partName` / `productName` | 是 | parts / products | 父对象名 |
| `materialName` / `partName` | 是 | materials / parts | 子对象名 |
| `ratio` | 是 | | 数量系数 |

| partTechRequirements / productTechRequirements | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `partName` / `productName` | 是 | parts / products | 父对象名 |
| `techNodeName` | 是 | techNodes | 科技节点名 |

| vehicles | 必填 | 自然键 | 引用 | 说明 |
| --- | :---: | :---: | --- | --- |
| `name` | 是 | 是 | | 载具名 |
| `fuelName` | 是 | | fuels | 绑定燃料（`PROTECT`） |
| `fuelConsumptionPerKm` / `maxCargo` / `price` / `carbonEmission` | | | | 油耗/载货/单价/碳排 |

| vehiclePathTypes | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `vehicleName` | 是 | vehicles | 载具名 |
| `pathTypeName` | 是 | pathTypes | 路径类型名 |

### ⑥ 科技与需求

| consumerDemands | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `region` | 是 | | 区域名（文本列） |
| `productType` / `productName` | 是 | products | 产品名（两列都写同一个值） |
| `quantity` | 是 | | 需求量（与区域/产品组成幂等键） |
| `note` | | | 备注 |

### ⑦ 市场与规则

| stocks | 必填 | 自然键 | 引用 | 说明 |
| --- | :---: | :---: | --- | --- |
| `code` | 是 | 是 | | 股票代码 |
| `name` | 是 | | | 股票名称 |
| `companyName` | | | companies | 关联公司 |
| `totalShares` / `initNetProfit` / `initPrice` / `currentPrice` | | | | 股本/净利润/初始价/当前价 |
| `industryPe` / `currentCarbon` / `industryAvgCarbon` / `happiness` / `round` | | | | 衍生指标 |
| `carbonFieldRef` / `happinessFieldRef` / `industryAvgCarbonRefs` | | | | 总览卡片引用字符串 |
| `pbCompanyId` | | | companies | PE 联动公司旧 id |
| `pbRandom` | | | | PE 随机参数 |

| stockFundsAccounts | 必填 | 自然键 | 引用 | 说明 |
| --- | :---: | :---: | --- | --- |
| `name` | 是 | 是 | | 账户名 |
| `ownerType` | 是 | | | `COMPANY` / `USER` |
| `companyName` / `username` | | | companies / users | 归属方（按 `ownerType` 二选一） |
| `cashBalance` | | | | 现金余额 |

| contractInstances | 必填 | 自然键 | 引用 | 说明 |
| --- | :---: | :---: | --- | --- |
| `name` | 是 | 是 | | 合同名（缺省=合同类型名） |
| `contractTypeKey` | 是 | | contractTypes | 合同类型 key |
| `status` | | | | `DRAFT`/`PENDING_EXEC`/`EXECUTED`/`TERMINATED` |
| `parties` | | | | `[{role, companyId\|companyName, isHost?, contractNumber?}]` |
| `inputs` | | | | 已填写的输入参数 |

| overviewCards | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `regionName` | 是 | regions | 区域名 |
| `cards` | | | `[{id, displayName, companyId, industryFieldId, zone?}]` |

| messages | 必填 | 引用 | 说明 |
| --- | :---: | --- | --- |
| `title` | 是 | | 标题 |
| `content` | | | 正文 |
| `senderUsername` | | | 发布者用户名 |
| `targetsAll` | | | 是否面向全体 |
| `targetUserIds` | | users | 指定收件人旧账号 id 数组 |

### ⑧ 账号与权限

| users | 必填 | 自然键 | 引用 | 说明 |
| --- | :---: | :---: | --- | --- |
| `username` | 是 | 是 | | 用户名（**全局**唯一） |
| `role` | | | | `SUPER_ADMIN`/`COMPETITION_ADMIN`/`PLAYER` |
| `displayName` / `isActive` / `permissions` | | | | 显示名 / 启用 / 权限键数组 |
| `companyScopes` | | | companies | 公司管理范围 |
| `viewCompanyScopes` | | | companies | 查看范围 |
| `contractViewCompanyScopes` | | | companies | 合同查看范围 |
| `stockCompanyScopes` | | | companies | 股票范围 |
| `companyScopeNames` 等四个 `*Names` | | | | 对应范围的**公司名**（辅助，跨分组按名兜底） |

### 现场核对

```powershell
python manage.py build_competition --schema            # 打印全部资源的列定义
python manage.py build_competition --schema materials  # 只看一个
```

---

## 8. 报错对照表

`BuilderError` 的常见文案与处理：

| 报错关键词 | 原因 | 处理 |
| --- | --- | --- |
| `「X」重复登记` | 同类资源里名字重复 | 改名；想补数据请用 `add_*` 系列方法 |
| `引用的 X「Y」尚未在本构建器中登记` | 用了没登记的对象名，或拼错了 | 先调用对应的登记方法；或直接用 `Ref` |
| `需要 X 的引用，但拿到的是 Y 的引用` | 引用类型传错（如把零件当原料） | 检查依赖方向：原料 → 零件 → 产品 |
| `X 不能同时是计算字段与财年定时器字段` | `is_calculated` 与 `timer_enabled` 同时为真 | 二选一 |
| `标记为计算字段，必须提供 graph` | 缺计算图 | 用 `calc_graph(calc_node(...))` 构造 |
| `启用定时器时必须指定 timer_trigger / timer_value` | 定时器信息不全 | 补 `timer_trigger="FY_START"`、`timer_value=...` |
| `X 取值必须是 [...] 之一` | 枚举值写错 | 按提示里的取值改（见 [6.3](#63-常量)） |
| `只能二选一：owner=<公司> 或 username=<用户名>` | 资金账户归属给了两个或零个 | 按需传其中一个 |
| `地图连线的起终点不能相同` / `重复登记` | 自环连线 / 同一对节点连了两次 | 改成不同节点；反向连线是允许的 |
| `不能以自身为前置` | 科技节点自依赖 | 改前置关系 |
| `出现了列定义里没有的字段：xxx` | 产出行里出现未知列名（通常是内部数据被手改） | 用 `--schema` 核对列名 |
| `未知资源名：xxx` | `build(resources=...)` 或 `--schema` 给了不存在的资源名 | 按提示里的可选值改 |
| `未知分组 scope=...` | `scope` 写错 | 可选 `competition`/`industry`/`company`/`supply`/`geo`/`tech`/`market`/`access`/`all` |
| `参照归档里找不到这些产业字段的 id` | `resolve_field_ids()` 拿到的归档里没有对应字段 | 确认该字段已在目标库存在（导入过「行业口径」分组） |

导入阶段的问题（不是异常，而是结果里的 `problems` / `notes`）常见原因：

| 现象 | 原因 |
| --- | --- |
| 某类资源 `skipped` 很多 | 引用的父对象被 `kept`（append 模式下已存在→子行一并跳过），或必填缺失 |
| `科技前置 ... 的节点未在本包中导入` | 前置节点行缺 `nodeId`（手写 JSON 时常见） |
| `合同实例：...因所属对象已存在而保留未改动` | append 模式下合同类型（全局）已存在，见[总览文档第 6 节](BUILD_COMPETITION_BY_CODE.md#6-需要知道的既有语义不是本库的缺陷) |
| 消息的指定收件人被移除 | 账号在导入顺序里排在消息之后 |
| 卡片建了但取不到值 | 卡片的 `industryFieldId` 还是 0，需 `resolve_field_ids()` 回填 |

---

## 9. 已知边界与注意事项

这些是**导入引擎/业务模型的既有语义**，建包库不改动它们，只把边界说清楚：

| # | 边界 | 建议 |
| --- | --- | --- |
| 1 | 比赛名不会被导入改写 | 建完比赛后手动改名，或先建好再导内容 |
| 2 | 产业类型/字段/合同类型是全局资源 | `code` / `key` 规划好，别在不同行业间复用 |
| 3 | 依赖方向固定为 原料 → 零件 → 产品 | 中间品要建模成「产品」，不能「零件用零件」 |
| 4 | 载具必须绑燃料，且建议给路径类型 | 否则运费/路径校验失败 |
| 5 | 合同实例按「合同类型名」判重 | 同一类型只预置一份；多单据用 `contractNumber` |
| 6 | append 模式下合同实例跨比赛搬运会被跳过 | 用 `--mode overwrite` |
| 7 | 账号密码不导出，新账号为随机密码 | 导入后超管重置再交付 |
| 8 | 消息的指定收件人受导入顺序限制 | 分两次导入：先账号，后消息 |
| 9 | 卡片的 `industryFieldId`、股票的 `pbFieldId`、账户的 `bindFieldId` 跨比赛不搬运 | 用 `resolve_field_ids()` 回填卡片；其余在前端重新选择 |
| 10 | 消费者需求按 `(区域, 产品, 数量)` 判重 | 调需求量 = 新增一条，注意清理旧记录 |
| 11 | 财年 `ACTIVE` 会触发 `FY_START` 定时器 | 先配好字段再开财年 |
| 12 | `status="EXECUTED"` 的合同会立即落账 | 开赛前保持 `DRAFT` |
| 13 | 目标比赛非空时默认拒绝导入 | 确需合并时加 `--allow-non-empty`，并优先 `--dry-run` 先看一遍 |
| 14 | 单份归档有明细条数上限（2000 行/资源） | 超大赛事请按分组分批导入 |

---

## 10. 速查卡

```python
from apps.preparation.builder import CompetitionBuilder, calc_node, calc_graph

def build():
    # ── 比赛 ──────────────────────────────────────────────
    b = CompetitionBuilder("比赛名", status="ACTIVE")
    b.fiscal_year(2026)
    b.stock_config_set({"limitPct": 0.1, "maxMovePct": 0.08})

    # ── 行业口径（全局） ───────────────────────────────────
    it = b.industry_type(1, "钢铁")
    b.add_field(it, "所在地", "location", field_type="STRING")
    b.add_field(it, "现金", "cash", field_type="NUMBER", default_value="0")

    # ── 公司 ─────────────────────────────────────────────
    east = b.region("东区")
    a = b.company("甲钢铁", industry_type=it, region=east,
                  field_values={"location": "东区港", "cash": "800000"})

    # ── 地理 ─────────────────────────────────────────────
    nt, pt = b.node_type("城市"), b.path_type("公路")
    n1 = b.node("东区港", nt, region="东区", x=320, y=180)
    n2 = b.node("西区站", nt, region="西区")
    b.edge(n1, n2, 420, pt)

    # ── 物资与产能 ────────────────────────────────────────
    diesel = b.fuel("柴油", price_per_liter="7.5")
    iron = b.material("铁矿石", origin="东区港", node_prices={n1: "120"})
    t1 = b.tech("高炉冶炼", tier=1, research_cost="5000")
    p1 = b.part("铁锭", materials={iron: 2}, tech=[t1])
    pr = b.product("钢材", parts={p1: 3})
    b.line("一号线", price="1200000", labor_count=40, max_per_year="5000")
    b.infrastructure("港口", footprint=100, price="2000000")
    b.warehouse("原料仓", "MATERIAL", capacity="20000", price="300000")
    b.vehicle("卡车", fuel=diesel, path_types=[pt], max_cargo=30, price="260000")

    # ── 需求 / 市场 ───────────────────────────────────────
    b.demand("东区", pr, 1200)
    b.card(east, a, "cash", display_name="现金")
    ct = b.contract_type("steel-sale", "钢材销售合同",
                         party_roles=[{"role": "buyer", "label": "买方"},
                                      {"role": "seller", "label": "卖方"}],
                         effects=[{"kind": "FIELD", "party": "buyer", "fieldKey": "cash",
                                   "op": "SUB", "value": {"from": "input", "key": "amount"}}])
    b.contract(contract_type=ct,
               parties=[{"role": "buyer", "company": a, "contractNumber": "B-001"},
                        {"role": "seller", "company": a}],
               inputs={"amount": 100000}, status="DRAFT")
    b.stock("600001", "甲钢铁", company=a, total_shares="12000", init_price="12.5")
    b.account("甲钢铁资金户", owner=a, cash_balance="1000000")
    b.user("player_a", company_scopes=[a], view_company_scopes=[a],
           contract_view_company_scopes=[a], stock_company_scopes=[a])
    b.message("开局公告", "欢迎参赛", to_all=True)
    return b
```

```powershell
python manage.py build_competition my.py --inspect                   # 看摘要
python manage.py build_competition my.py --competition 7 --dry-run   # 预演
python manage.py build_competition my.py --competition 7             # 导入
python manage.py build_competition --schema companies                # 查字段
python manage.py test apps.preparation                               # 跑自检测试
```

---

## 相关文件

| 文件 | 作用 |
| --- | --- |
| [`backend/apps/preparation/builder/core.py`](../backend/apps/preparation/builder/core.py) | 构建器主体（本文档第 4 节的实现） |
| [`backend/apps/preparation/builder/schema.py`](../backend/apps/preparation/builder/schema.py) | 列定义表（本文档第 7 节的来源） |
| [`backend/apps/preparation/builder/types.py`](../backend/apps/preparation/builder/types.py) | 异常、引用、枚举、计算图助手 |
| [`backend/apps/preparation/management/commands/build_competition.py`](../backend/apps/preparation/management/commands/build_competition.py) | 命令行（本文档第 5 节） |
| [`backend/examples/competitions/demo_competition.py`](../backend/examples/competitions/demo_competition.py) | 覆盖全部 35 类资源的可运行示例 |
| [`backend/apps/preparation/tests/test_builder.py`](../backend/apps/preparation/tests/test_builder.py) | 41 条自动化验证 |
| [`docs/BUILD_COMPETITION_BY_CODE.md`](BUILD_COMPETITION_BY_CODE.md) | 总览与工作流（适合先读） |
