# 合同类型代码化：用代码写合同，替代可视化拖拽

> 目标：把**创建合同类型**从「在画布上拖节点、连端口、填属性面板」变成「写一段简单 Python 代码」，
> 并把重点放在**降低抽象**上——尤其是最容易出错的两处：**效果（effect）** 与 **实体（ENTITY）**。
>
> 本方案**不新增任何引擎语义**：产物就是引擎今天已经在跑的四份 JSON，因此
> 可逆性（`revert_contract` 事件溯源重放）、审计粒度（`ContractFieldEffect` 每字段一行）、
> 试算接口全部原样不受影响。

---

## 目录

1. [先看效果：同一条合同，两种写法](#1-先看效果同一条合同两种写法)
2. [降低抽象之一：效果（effect）](#2-降低抽象之一效果effect)
3. [降低抽象之二：实体（ENTITY）](#3-降低抽象之二实体entity)
4. [快速开始](#4-快速开始)
5. [API 手册](#5-api-手册)
6. [静态体检：把静默错误提前](#6-静态体检把静默错误提前)
7. [命令行](#7-命令行)
8. [与可视化编辑器共存 / 渐进迁移](#8-与可视化编辑器共存--渐进迁移)
9. [落地过程中查清并规避的 11 个引擎契约陷阱](#9-落地过程中查清并规避的-11-个引擎契约陷阱)
10. [边界与未覆盖项](#10-边界与未覆盖项)
11. [复杂合同案例](#11-复杂合同案例)
12. [文件与测试](#12-文件与测试)

---

## 1. 先看效果：同一条合同，两种写法

**可视化编辑器**里做一份「买方付钱给卖方」的合同，需要：拖 1 个合同节点 → 2 个参与方节点 →
1 个输入项节点 → 1 个检查节点（连 2 个值源）→ 2 个效果节点（各连参与方 + 值源）→
再逐条连线并配置属性面板。

**代码化**：

```python
from apps.contracts.builder import ContractType, total_price

def build():
    ct = ContractType("steel-sale", "钢材销售合同")
    seller = ct.party("seller", "卖方")
    buyer  = ct.party("buyer",  "买方")

    amount = ct.input("amount", "成交金额", "number", required=True, default="100000")
    plate  = ct.input("plate", "采购清单", "materialList", party=seller)

    ct.check(buyer.field("cash") >= amount, error="买方货币资金不足")
    ct.sub_number(buyer.field("cash"),  amount)
    ct.add_number(seller.field("cash"), amount)
    ct.add_number(seller.field("cost"), total_price(plate, at=seller))
    return ct
```

可读、可 diff、可 review、可复用、可进版本管理与 CI。而**落库产物完全一样**。

---

## 2. 降低抽象之一：效果（effect）

### 2.1 问题：一个 `op` 包住四种语义

引擎落库的效果只有一种形状：

```json
{"kind": "FIELD", "party": "buyer", "fieldKey": "cash", "op": "ADD", "value": {...}}
```

但 `op` 的**真实含义取决于目标字段的运行时类型**（`engine.apply_field_effect`）：

| 字段类型 | `ADD` 的实际含义 | `SUB` 的实际含义 |
| --- | --- | --- |
| `NUMBER` | 数值相加 | 数值相减 |
| `LIST` | 追加并**去重** | 按元素移除 |
| `DICTIONARY` | 逐键累加（独有键保留） | 逐键相减；**若值是数组则改为「删键」** |
| `STRING` / `BOOLEAN` | 覆盖（`ADD` 无意义） | 覆盖 |

后果：**看一条效果无法知道它做什么**——必须再去查「这个 `fieldKey` 在目标公司所属产业里的
字段类型是什么」。字典的 `SUB` 更是靠「值是数组还是字典」来区分「删键」与「减数」，
意图藏在值的形态里。

### 2.2 做法：11 个具名效果，名字自带类型契约

| 效果 | 只能作用于 | 引擎 op | 实际行为 |
| --- | --- | --- | --- |
| `add_number(target, amount)` | `NUMBER` | `ADD` | 数值相加 |
| `sub_number(target, amount)` | `NUMBER` | `SUB` | 数值相减 |
| `set_number(target, amount)` | `NUMBER` | `SET` | 数值覆盖 |
| `append_items(target, *items)` | `LIST` | `ADD` | 追加（自动去重） |
| `remove_items(target, *items)` | `LIST` | `SUB` | 按元素移除 |
| `set_items(target, [...])` | `LIST` | `SET` | 整体覆盖（`[]` = 清空） |
| `add_dict(target, {k: v})` | `DICTIONARY` | `ADD` | 逐键累加，独有键保留 |
| `sub_dict(target, {k: v})` | `DICTIONARY` | `SUB` | 逐键相减，**键保留** |
| `remove_keys(target, *keys)` | `DICTIONARY` | `SUB` | **删键**（键本身消失） |
| `set_dict(target, {k: v})` | `DICTIONARY` | `SET` | 整体覆盖 |
| `set_value(target, value)` | 任意 | `SET` | 覆盖（用于 STRING / BOOLEAN） |

`with ct.when(...)` 这类控制流不算「效果」，单独一组：

| 控制流 | 引擎 kind |
| --- | --- |
| `with ct.when(cond):` / `with ct.otherwise():` | `IF`（**一条**效果、then/else 两分支） |
| `with ct.for_each(清单, var="row"):` | `FOREACH` |
| `ct.assign("name", value)` | `ASSIGN` |

### 2.3 收益

```python
# 以前要这样想：这是字典字段吗？SUB 传数组还是字典？
ct.add_dict(buyer.field("stock"), {"钢坯": 2})    # 语义：加上 2
ct.sub_dict(buyer.field("stock"), {"钢坯": 2})    # 语义：减掉 2，键还在
ct.remove_keys(buyer.field("stock"), "钢坯")      # 语义：把这个键删掉
```

三个名字，三种意图，不用查字段类型。类型不符**在构建期直接报错**：

```
BuildError: 字段「标签」的类型声明是 STRING，但效果「append_items」只能作用于 LIST 字段
```

### 2.4 附带去掉的两处抽象

**`valueOp` / `value2`**：引擎支持「写入量 = value ⟨valueOp⟩ value2」。本库不暴露这两个参数，
直接在**值层**写运算：

```python
ct.add_number(target, a + b)      # → op ADD + value2=a + valueOp=ADD + value=a
```

两种写法在引擎里等价（`combine_values` 先算再交给 `apply_field_effect`），但前者意图写在代码里。

**`kind` / `type` 的混淆**：检查对象用 `kind`、值源用 `type`，这是引擎内部差异，
使用者不需要知道（见第 9 节，本库在落地时踩过这个坑）。

---

## 3. 降低抽象之二：实体（ENTITY）

### 3.1 问题：反射式属性路径 + 隐藏输入项

引擎引用一条比赛数据要写：

```json
{"type": "ENTITY", "entityType": "MATERIAL", "entityRef": "<某个输入项的key>",
 "attribute": "price", "multiplyByInput": "qty"}
```

三层抽象叠在一起：

| # | 抽象 | 后果 |
| --- | --- | --- |
| ① | 实体靠「某个输入项的值」间接定位 | 想在公式里引用一个固定原料，**必须先造一个隐藏输入项**承载它的 id |
| ② | 属性名走 `getattr(camel→snake, 0)` 反射 | 属性名写错**不报错**，静默取 0 |
| ③ | 再乘一个输入项来算量 | 又一个隐式依赖 |

②已经踩出真实不一致：前端 `ENTITY_FIELDS` 给 `MATERIAL` 声明了 `price` 属性，
但 `Material` 模型上**没有** `price` 字段（价格按地图节点存在 `node_prices` JSON 里）。
于是同一个「原料单价」有两条路径、两个答案：

| 路径 | 实际走法 | 结果 |
| --- | --- | --- |
| 清单输入项 + `PRICE` 聚合 | `compute_material_list_price` | 按节点价 / 回退市场均价 ✓ |
| `ENTITY` + `attribute:"price"` | `getattr(material, "price", 0)` | **恒为 0** ✗ |

### 3.2 做法：一层具名访问器 + 属性白名单

```python
snap = snapshot(competition_id)
iron = snap.material("铁矿石")     # 不存在 → 立刻报错，并给出最相近的名字
iron.carbon                        # → ENTITY，属性对模型真实字段校验
snap.vehicle("重型卡车").maxCargo
```

三条保证：

1. **存在性**：`snap.material / part / product / tech / warehouse / production_line /
   fuel / vehicle / infrastructure / map_node` 查不到就抛错，并附可用清单与拼写建议；
2. **属性合法性**：`ENTITY_ATTRIBUTES` 白名单**只列模型上真实存在的标量字段**，
   并有 `assert_engine_parity()` 在导入期核对白名单与模型一致（防止本库自身漂移）；
3. **口径唯一**：原料**不允许**读 `price`（会静默为 0），取价只能走
   `total_price(清单, at=参与方)` / `avg_price(清单)`——与引擎聚合同一条口径。
   读错时给出可执行的提示：

```
BuildError: 原料「铁矿石」没有可读属性「price」
  ↳ 原料价格按地图节点存储（node_prices），模型上没有 price 字段，直接读会恒为 0。
    请用 total_price(原料清单, at=参与方) 取地点价总额，或 avg_price(原料清单) 取市场均价
```

### 3.3 隐藏输入项自动生成

引擎的 `entityRef` 必须指向一个输入项 key。本库由快照**按需生成**槽位：

```python
payload["effects"][0]["value"]
# {"type": "ENTITY", "entityType": "MATERIAL",
#  "entityRef": "__ref_material_12", "attribute": "carbonEmissionCoefficient"}

payload["inputSchema"]
# [..., {"key": "__ref_material_12", "label": "原料：铁矿石", "type": "ENTITY",
#         "entityType": "MATERIAL", "required": False, "default": 12, "hidden": True}]
```

同一个实体被引用多次只生成一个槽位。使用者不再需要手搓隐藏输入项——
**但复用的仍是引擎既有的 `ENTITY` 值源**，没有新机制。

---

## 4. 快速开始

```python
# contracts_src/steel_sale.py
from apps.contracts.builder import ContractType, number, total_price, snapshot

COMPETITION_ID = 7

def build():
    snap = snapshot(COMPETITION_ID)
    ct = ContractType("steel-sale", "钢材销售合同")

    seller = ct.party("seller", "卖方")
    buyer  = ct.party("buyer",  "买方")

    amount = ct.input("amount", "成交金额", "number", required=True, default="100000")
    plate  = ct.input("plate", "采购清单", "materialList", party=seller)

    ct.check(buyer.field("cash") >= amount, error="买方货币资金不足")
    ct.sub_number(buyer.field("cash"),  amount)
    ct.add_number(seller.field("cash"), amount)
    ct.add_number(seller.field("cost"), total_price(plate, at=seller))
    return ct
```

```powershell
cd backend

# 1) 静态体检（纯只读：不写库、不跑引擎）
python manage.py build_contract_types contracts_src/ --competition 7 --check

# 2) 试算验证（复用合同引擎，事务整体回滚）
python manage.py build_contract_types contracts_src/ --competition 7 --trial

# 3) 预演导入（打印将写入什么）
python manage.py build_contract_types contracts_src/ --competition 7 --dry-run

# 4) 真正导入（新增或按 key 更新）
python manage.py build_contract_types contracts_src/ --competition 7 --import
```

完整可运行示例：[`backend/examples/contracts/demo_contracts.py`](../backend/examples/contracts/demo_contracts.py)
（3 个合同类型，覆盖具名效果、实体访问器、聚合、控制流、输入项条件显隐）。

---

## 5. API 手册

### 5.1 `ContractType(key, name, *, description=None, enabled=True)`

合同类型构建器。`key` 只允许字母/数字/连字符/下划线（会出现在 URL 与文件名里）。

### 5.2 参与方

```python
party(role, label=None, *, is_host=False, selectable=True, industry_type_id=None) -> PartyRef
```

| 参数 | 说明 |
| --- | --- |
| `role` | 角色标识，合同内唯一；效果与检查都按它定位目标公司 |
| `label` | 显示名 |
| `is_host` | 主办方（虚拟参与方，不绑公司，**不能作为效果目标**） |
| `selectable` | 创建合同时是否可手选 |
| `industry_type_id` | 限定该角色只能由指定产业类型的公司担任（体检据此精确校验字段） |

`PartyRef` 的方法：

| 方法 | 作用 |
| --- | --- |
| `p.field(field_key)` | 引用该方的产业字段；**既可当效果的写入目标，也可直接参与运算与比较** |
| `p.is_industry(id)` | 该方公司是否属于指定产业类型（布尔值源） |
| `p.company_name()` | 该方公司名称 |

### 5.3 输入项

```python
input(key, label, type="number", *, required=False, default=None, entity_type=None,
      party=None, allowed=None, hidden=False, when=None) -> Value
```

15 种 `type`（与前端表单一一对应）：

| 类型 | 含义 |
| --- | --- |
| `number` / `string` / `boolean` | 标量 |
| `ENTITY` | 从数据管理选一个实体（需 `entity_type=`） |
| `nodeRoute` | 有序地图节点列表（创建时校验相邻节点有连线） |
| `mapNode` | 单个地图节点 |
| `list` / `dict` | 自由列表 / 字典 |
| `materialList` / `partList` / `productList` / `infrastructureList` / `fuelList` / `vehicleList` / `warehouseList` | 清单（值是 `{名称: 数量}` 字典） |
| `techNode` | 科技节点选择 |

其它参数：`party`（清单绑定参与方，供按所在地取价）、`allowed`（限制基建/载具可选范围，
对应引擎的 `allowedInfrastructures` / `allowedVehicles`）、`when`（条件显隐）。

### 5.4 检查

```python
check(condition, *, label="", error="") -> Check
check_container(kind, op, value1, value2, *, label="", error="") -> Check
```

`check()` 直接写比较表达式，自动判定成引擎的检查类型：

| 写法 | 引擎检查类型 |
| --- | --- |
| `buyer.field("cash") >= amount` | `FIELD_COMPARE` |
| `a >= b`（两个值源） | `VALUE_COMPARE` |
| `buyer.is_industry(1)` | `INDUSTRY_IS` |

`check_container()` 用于字典/列表相互比较：`kind="DICT_COMPARE"`（op 取 `GTE`/`GT`/`EQ`）、
`kind="LIST_COMPARE"`（op 取 `ELEMENT_EQ`/`CONTAINS`/`GT`/`GTE`/`EQ`）。

> 引擎不支持「两个产业字段互相比较」与「不等于」，本库会明确报错而不是产出一个会被误读的 JSON。

### 5.5 效果（11 种）

见[第 2.2 节](#22-做法11-个具名效果名字自带类型契约)。都是 `ct.xxx(target, ...)` 形式。

> **注意**：必须用 `ct.add_number(...)`，不能直接调用模块级的 `add_number(...)`。
> 后者不会被挂到合同上——本库有漏挂载自检，会在 `build()` 时直接报错（见第 9 节）。

### 5.6 控制流

```python
with ct.when(buyer.is_industry(1)):
    ct.add_number(buyer.field("subsidy"), number("100"))
with ct.otherwise():
    ct.add_number(buyer.field("subsidy"), number("0"))
```

`when` + `otherwise` 产出**一条** IF 效果（then/else 两分支），不是两条并列效果。

```python
with ct.for_each(plate, var="row"):
    ct.assign("q", ct.item("plate"))
    ct.add_number(seller.field("total"), var("q"))
```

- 清单类输入（`materialList` 等）的值是字典 → 循环变量拿到**名称**，数量用 `ct.item()` 取；
  本库会自动包一层 `keys(...)`（引擎的 FOREACH 只遍历列表）。
- `list` / `nodeRoute` / `mapNode` 型输入的值本身就是列表 → 直接遍历，元素就是值，
  此时**不要**用 `ct.item()`。

### 5.7 比赛数据引用

```python
snap = snapshot(competition_id)         # 只读，一次加载
snap.material("铁矿石")                  # → EntityRef
snap.vehicle("重型卡车").maxCargo         # → Value（ENTITY 值源）
snap.company_location(company_id)        # 公司所在地（未填返回 None，与引擎同口径）
snap.industry_field_types()              # {产业类型 id: {fieldKey: fieldType}}
snap.all_industry_field_keys()           # 全库字段 key 并集（体检用）
snap.companies()                         # 本场比赛公司列表
```

`EntityRef` 的可用属性按类型白名单（`ENTITY_ATTRIBUTES`），与模型真实字段一致：

| 实体 | 可读属性 |
| --- | --- |
| 原料 | `name` `origin` `carbonEmissionCoefficient` `type`（**无 `price`**，见 3.2） |
| 零件 / 产品 | `name` |
| 科技节点 | `name` `description` `tier` |
| 仓库 | `name` `capacity` `price` `type` |
| 生产线 | `name` `price` `laborCount` `maxPerYear` |
| 燃料 | `name` `pricePerLiter` |
| 载具 | `name` `fuelConsumptionPerKm` `maxCargo` `price` `carbonEmission` |
| 基建 | `name` `footprint` `price` `activationPrice` 及 6 项加成 |
| 地图节点 | `name` `region` `x` `y` |

### 5.8 值构造

```python
number("100")            # 数值常量（字符串保精度）
text("钢材")              # 文本常量
flag(True)               # 布尔常量
const([1, 2])            # 任意常量
var("row")               # 循环变量 / assign 的变量
formula("a + b")         # 自由公式（引擎 safe_evaluate 沙箱）
company_name(buyer)      # 参与方公司名
```

值支持 Python 运算符：`+ - * /`、`>= <= > <`、`.equals()` `.not_equals()`、`.and_()` `.or_()` `.not_()`。

> **公式的沙箱真相**：引擎把 FORMULA 的沙箱拼成 `{**inputs, **EXPR_HELPERS, **scope}`
> （`engine.py:1788`）——输入项与循环变量是**顶层名字**，**没有** `inputs` / `scope` 两个字典对象。
> 所以公式要写 `mats[row]` 或 `get(mats, row)`，**不能**写 `inputs['mats']`（会静默取 0）。
> 本库的体检会直接拦下后一种写法。

### 5.9 清单聚合

37 个聚合端点收敛成 8 类函数（**属性名与「数据管理」界面里的字段名一致**）：

```python
total_qty(清单)                             # 清单总数量
sum_of(清单, "price")                       # 清单 × 属性 求和
total_price(原料清单, at=买方)               # 原料总价（地点价 → 回退市场均价）
avg_price(原料清单)                          # 原料总价（明确用市场均价口径）
carbon(原料清单)                             # 原料碳排合计
expand(零件清单或产品清单)                    # 展开成配比/科技清单
warehouse_storage(仓库清单)                  # 每种种类的总存储量
tech_prerequisites(科技节点)                 # 前置节点列表
route_distance(节点列表) / route_path_types / route_start_node / route_end_node
```

还提供最常用属性的同义短名，**编译产物与 `sum_of` 完全一致**（不引入第二套口径）：
`vehicle_price` `vehicle_cargo` `vehicle_fuel_per_km` `vehicle_carbon` `fuel_price`
`warehouse_price` `infra_price` `infra_activation_price` `infra_footprint` `infra_employment`
`infra_population` `infra_high_quality` `infra_happiness` `infra_income` `infra_carbon`
`tech_research_cost`。

### 5.10 产出

```python
ct.build()      # {"partyRoles": [...], "inputSchema": [...], "effects": [...], "conditions": [...]}
ct.payload()    # 加上 key/name/... 的完整请求体，graph=None（可直接 POST /api/contract-types）
ct.to_json()    # JSON 文本
ct.effects_json() / ct.conditions_json()
ct.describe()   # 一句话摘要
```

`partyRoles` / `inputSchema` / `effects` / `conditions` 的每一个值都是引擎今天在跑的格式，
`graph` 传 `None`（后端 `allow_null=True`，引擎从不读它）。

保留既有内容：

```python
ct.keep_effects(existing_effects)   # 原样保留一段已有 effects（渐进迁移用，排在代码产出的效果之前）
```

---

## 6. 静态体检：把静默错误提前

引擎在数据解析不到时**一律静默降级**（这是刻意的业务规则，不是 bug）：

| 缺什么 | 引擎行为 | 代码位置 |
| --- | --- | --- |
| 聚合清单里的名字不存在 | 该项按 **0** 计入 | `engine.py:1365` |
| 原料在该地点没有报价 | 回退**市场均价** | `engine.py:1248` |
| 指定了参与方但公司没填 `location` | 回退均价 | `engine.py:1654` |
| 公式引用的名字不存在 | 取到 `None` → 参与运算按 0 | `engine.py:1780` |
| 公司产业下没有该字段 | **抛错**（这条会报） | `engine.py:2264` |

所以「配置错了」的典型表现不是报错，而是**数字不对**。静态体检把这些提前，且完全不碰引擎：

```powershell
python manage.py build_contract_types contracts_src/ --competition 7 --check
```

```
钢材销售合同（steel-sale）  状态：1 处阻断、1 处提醒
  [阻断] 类型检查：参与方「buyer」所属产业类型「钢铁」下没有字段「cash」
        ↳ 该产业可用字段：cangku、location、shengchanxian、xianjin、yuanliaoliang；
          引擎执行时会直接报「所属产业下不存在字段」
  [提醒] 值源：效果[3].value 的原料总价使用市场均价口径（未指定参与方）
        ↳ 要按公司所在地取价请用 total_price(清单, at=参与方)
```

检查项（严重级别：`error` 阻断 / `warning` 提醒 / `info` 提示）：

| 代码 | 级别 | 检查什么 |
| --- | --- | --- |
| `field.not_anywhere` | 阻断 | 引用的字段在**库中任何产业**下都不存在（多半是拼写错误） |
| `field.missing` | 阻断 | 字段不在该参与方所属产业下（引擎执行时会报错） |
| `effect.type_mismatch` | 阻断 | 效果与字段类型明确矛盾（如 STRING 字段用了 `add_number`） |
| `effect.host_party` | 阻断 | 效果目标是主办方（不绑公司，引擎会拒绝执行） |
| `party.unknown` / `value.field_party_unknown` | 阻断 | 引用了未定义的参与方 |
| `value.input_unknown` | 阻断 | 引用了不存在的输入项 |
| `value.aggregate_mismatch` | 阻断 | 清单类型与聚合口径错配（引擎会静默算 0） |
| `value.formula_inputs_object` / `value.formula_scope_object` | 阻断 | 公式里写了 `inputs[...]` / `scope[...]`（沙箱里没有这两个对象） |
| `value.formula_name` | 阻断 | 公式引用了未知名字 |
| `value.var_scope` | 阻断 | 变量用在了 `for_each` 作用域之外 |
| `value.entity_attr` | 阻断 | 实体属性不在白名单内 |
| `value.entity_ref` | 阻断 | 实体引用缺少 `entityRef` |
| `effect.dict_spec_leak` | 阻断 | 字典效果的值里混入了值源对象 |
| `input.entity_type` | 阻断 | `ENTITY` 输入项缺 `entityType` |
| `value.price_avg` | 提示 | 原料总价使用市场均价口径 |
| `industry.party_unbound` | 提示 | 参与方未限定产业类型，无法预先校验字段 |
| `input.route` | 提示 | 节点列表输入（创建合同时会校验相邻节点连线） |

试算（`--trial`）进一步用**真实引擎**验证：逐家真实公司各跑一次，
断言前置检查全过、字段改动符合预期，事务整体回滚不落任何数据。

---

## 7. 命令行

```
python manage.py build_contract_types [source] [选项]
```

| 选项 | 说明 |
| --- | --- |
| `<source>` | 合同类型脚本（`.py`）或包含脚本的目录 |
| `--competition <id>` | 比赛 id（体检与试算需要） |
| `--check` | 只做静态体检（默认动作） |
| `--trial` | 对每家公司各跑一次真实引擎（事务回滚） |
| `--dry-run` | 预演导入：打印将写入什么，不写库 |
| `--import` | 真正导入（新增或按 key 更新） |
| `--export [KEY]` / `--all` | 把已有合同类型**反解**成具名效果打印出来（迁移用，不写任何东西） |
| `--json` | 以 JSON 输出（接 CI） |
| `--strict-types` | 体检对「效果 × 字段类型」采用严格判定 |
| `--verbose` | 打印生成的四份 JSON |

脚本约定（按顺序查找）：`def build()`（推荐，返回 `ContractType` / 列表 / 字典）、
模块级 `CONTRACTS`、兜底「脚本里创建过的全部合同类型」。目录会被递归扫描（忽略 `_` 开头的文件）。

**退出码**：`0` 成功；`1` 体检有阻断项或试算失败；非 0（`CommandError`）参数/脚本错误。
可以直接放进 CI。

导入是**幂等**的：已存在的 `key` 会逐字段比对，无变化就跳过写入（也就不会触发无谓广播），
且**不会覆盖已有的 `graph`**——可视化画布仍然可用。

---

## 8. 与可视化编辑器共存 / 渐进迁移

三条路径产出的四份 JSON **完全同格式**，可以混用：

| 方式 | 适用 |
| --- | --- |
| 前端「可视化新建」 | 一次性、需要看图构思的场景 |
| 前端「简单新建」 | 只有 FIELD 效果与字段比较的简单合同 |
| **代码（本库）** | 需要版本管理、批量生成、CI 校验、跨比赛复用的场景 |

### 反解既有合同类型

```powershell
# 看看已有合同类型的每条效果对应哪个具名效果
python manage.py build_contract_types --export steel-sale

=== 钢材销售合同（steel-sale）===
具名效果反解覆盖率：1/1
  · add_dict         字典逐键累加：seller.cangku ← {钢材: 常量 '1'}
```

反解按「引擎 op + 值形态」判定，与 `Effect.to_spec()` **互为逆运算**（有往返测试保证）。
无法归类的行会被跳过并提示，由你决定是照抄原名还是改写。

### 建议的迁移顺序

1. `--export --all` 把所有存量类型打印出来，评估工作量；
2. 逐个改写成 `.py` 脚本，`--dry-run` 确认产出与原来**字段级一致**；
3. `--import` 覆盖（`key` 相同即更新，`graph` 保留）；
4. 之后新增/修改合同类型一律走代码；画布只作查看。

> **不要双向同步**：两边都当唯一真源必然冲突。建议代码为源、`graph` 为可丢弃的视图。

---

## 9. 落地过程中查清并规避的 11 个引擎契约陷阱

这些都是**真实存在的坑**，本库在开发期逐条踩过并已在编译/体检层规避。
记录下来是因为它们对「手写 JSON」或后续改造同样重要。

| # | 陷阱 | 表现 | 本库的处理 |
| --- | --- | --- | --- |
| 1 | **IF 的 `cond` 是值源（`type`），不是检查（`kind`）** | 写成 `{"kind":"INDUSTRY_IS",...}` 时 `eval_value_spec` 落到默认分支返回 **0**，分支**永远走 else** | `when()` 产出 `{"type":"INDUSTRY_IS",...}`（与前端 `graph-model.ts:1275` 一致） |
| 2 | **字典效果的 `value` 必须包 `CONST`** | 直接写裸字典 `{"钢坯":"3"}` → `eval_value_spec` 落到默认分支 `to_number(dict)` → **0**，字典效果变成「加 0」 | `add_dict`/`sub_dict`/`set_dict` 编译成 `{"type":"CONST","value":{...}}` |
| 3 | **FOREACH 只遍历列表** | `lst = arr if isinstance(arr, list) else []`——清单输入的值是字典，直接传就**一次都不循环**（静默无操作） | 清单类输入自动包 `keys(清单)` |
| 4 | **FORMULA 沙箱没有 `inputs` / `scope` 对象** | 沙箱是 `{**inputs, **EXPR_HELPERS, **scope}`，写 `inputs['mats']` 取到 `None` → 按 0 算 | `item()` 产出 `mats[row]`；体检拦下 `inputs[...]` / `scope[...]` |
| 5 | **`remove_keys` 必须保持数组形状** | 字典的 `SUB` 靠「值是数组还是字典」区分删键与减数；单键若退化成裸字符串，形状不稳定 | 单键也包 `LIST_CONCAT`（`as_list` 保证结果仍是数组） |
| 6 | **字段缺失的错误时机晚** | 字段不在公司产业下时引擎**会报错**，但只在执行到那条效果时才报；字段在**任何**产业都没有则必然出错 | 体检在构建期就报（`field.missing` / `field.not_anywhere`） |
| 7 | **`execute` 不套用 `inputSchema` 的默认值** | 未显式提供的输入项取到 `None` → `to_number(None)` = **0**；表现是「乘费率的效果恒为 0」 | `ct.default_inputs()` 负责补齐（`--trial` 也用它） |
| 8 | **不能用 `+` 拼字符串** | `+` 编译成 `OP:ADD`，而 `apply_op` 的 ADD 走数值路径（`to_number`）→ 两段文本都变成 **0** | 用 `concat_text(...)`（编译成沙箱的 `concat`）或 `join_text(列表, sep)` |
| 9 | **公式沙箱的函数都是小写** | `EXP(...)` 是 `apply_op` 的名字、不是沙箱函数；沙箱里是 `exp/log/pow/sqrt/round/...` | 体检的可用名字集合从引擎**动态派生**，写错立即报错 |
| 10 | **公式沙箱没有 `range`** | `for_each` 需要列表才能遍历，没有 `range` 就写不出「按 1..N 循环」 | 用 `range_list(start, stop)`（编译成 `LIST_RANGE`，左闭右开） |
| 11 | **`is_industry` 的 id 与参与方声明的 id 容易写岔** | 参与方声明 `industry_type_id=1001`、条件却写 `is_industry(1)`，运行期静默走错分支、体检也发现不了 | 用同一个常量（文档与案例都这么写） |

> 第 7–11 条是在编写[复杂合同案例](#11-复杂合同案例)时逐条踩出来的，
> 测试里都有对应的回归用例。

另外两处**设计取舍**（刻意不做的事）：

- **不做「效果 × 字段类型」的严格判定**（除非加 `--strict-types`）：合同模板是全局的、
  会被多个产业类型复用，同一 `fieldKey` 在不同产业里类型可能不同。默认只拦**明确矛盾**
  （STRING 字段用 `add_number`），不拦「同名不同型」。
- **不暴露 `ENTITY` 的 `attribute` 反射**：改成白名单访问器，从根上消灭「属性名写错静默为 0」。
  原料单价这类「需要多跳解析」的量干脆不暴露属性，只留聚合函数一条口径。

---

## 10. 边界与未覆盖项

| 项 | 说明 |
| --- | --- |
| `graph` 字段 | 代码方式产出 `graph=None`。想同时保留画布，可自己把既有 `graph` 传给 `POST /api/contract-types`；`--import` 会**保留**已存在记录的 `graph` |
| 效果类型 | 引擎只有 `FIELD` 一种叶子效果（作用对象是产业字段），本库不新增 |
| 非字段副作用 | 发消息、写日志、通知外部系统**不在合同效果里做**——用既有的实时广播 + `contract_watcher` 事件出口 |
| 效果中途失败 | 引擎没有「效果内抛出」的原语；需要阻断时用 `check()`（前置检查） |
| 字段类型跨产业不一致 | 见第 9 节最后一条；需要精确校验时给 `party(..., industry_type_id=N)` |
| 公式复杂度 | 单行表达式，可用助手见 `EXPR_HELPERS`；复杂逻辑拆成 `assign()` 变量 |
| 反解覆盖率 | 引擎 op 的语义空间（op × 值形态）已全覆盖；非 `FIELD` 的 `IF`/`FOREACH`/`ASSIGN` 目前只打印不反解 |

---

## 11. 复杂合同案例

[`backend/examples/contracts/complex_contracts.py`](../backend/examples/contracts/complex_contracts.py)
里是 6 个真实业务案例，专门挑「可视化编辑器里最难画」的逻辑：

| 案例 | 业务难点 | 用到的关键能力 |
| --- | --- | --- |
| ① 原料采购 | 同一原料在不同地点报价不同；采购清单要变成库存 | 地点价聚合（绑定参与方）、按名称循环写字典、碳排聚合后再运算 |
| ② 钢材销售 | 阶梯定价；会员折扣；多步金额顺序 | 公式分档、`assign` 中间值、值层运算 |
| ③ 技术引进 | 前置未解锁则拒绝签约；解锁能力 | 科技前置聚合 + 列表包含比较、列表追加去重 |
| ④ 银团贷款 | 复利；按产业分档；贴息；逐期还款计划 | `exp()` 复利公式、分支改写金额、`range_list` + `FOREACH` 动态键 |
| ⑤ 基建投资 | 分期到账；达标追加、未达标扣款 | 嵌套 IF、一套清单九种属性分别汇总 |
| ⑥ 物流运输 | 最短路径路程计价；超重加价；碳税；路线留痕 | 图搜索路程、起讫点聚合、条件改写金额 |

挑三个看一下写法：

**① 地点价口径**（`at=` 显式声明按哪一方取价，不再靠连线）

```python
materials = ct.input("materials", "采购原料清单", "materialList",
                     party=buyer, required=True)
goods = total_price(materials, at=buyer)          # 采购方所在地价
carbon_total = carbon(materials)                   # 碳排聚合
ct.check(buyer.field(F["cash"]) >= goods + transport, error="采购方货币资金不足")
```

**③ 列表包含比较**（前置校验：所选科技的前置必须都已在已解锁清单里）

```python
tech = ct.input("tech", "引进的科技", "techNode", required=True)
owned = ct.input("owned", "已解锁科技清单", "list", default="[]")
ct.check_container(
    "LIST_COMPARE", "CONTAINS",
    tech_prerequisites(tech), owned,               # 前置节点集合 ⊆ 已解锁集合
    label="科技前置校验",
    error="所选科技的前置节点尚未全部解锁，不能越级引进",
)
ct.append_items(licensee.field(F["tech_list"]), input_value(tech))   # 解锁（去重）
```

**④ 复利 + 分档 + 动态键循环**

```python
ct.assign("gross", principal * formula("exp(rate * months / 12)") - principal)
ct.assign("interest", var("gross"))
with ct.when(borrower.is_industry(PREFERRED_INDUSTRY_ID)):
    ct.assign("interest", var("gross") * number("0.9"))     # 优惠产业 9 折
with ct.when(subsidized):
    ct.assign("interest", var("interest") * number("0.5"))  # 贴息折半

# 逐期还款计划：键在运行期才知道，可视化编辑器表达不了
with ct.for_each(range_list(number("1"), months + number("1")), var="period"):
    ct.add_dict(borrower.field(F["repay_terms"]), {"待还期数": 1})
```

### 这些案例是怎么验证的

[`test_complex_contracts.py`](../backend/apps/contracts/tests/test_complex_contracts.py)
搭了一套完整比赛数据（产业字段 / 5 家公司 / 原料地点价 / 三节点地图 /
载具 / 基建 / 科技前置），对每个案例断言**真实金额**：

| 验证点 | 断言 |
| --- | --- |
| 地点价 | 铁矿石 A城 100 / B城 150（均价 125）→ 买 10 单位 = **1000**（按买方所在地），漏连参与方会变成 1250 |
| 阶梯定价 | 1000 吨→3800、500 吨→4000、499 吨→4200；会员再 ×0.95 |
| 前置校验 | 已解锁「高炉冶炼」才能引进「热轧工艺」；清单为空时**被拦下** |
| 复利 | 利息 = 本金 × (e^(0.06×1) − 1) × 0.9（优惠产业）× 0.5（贴息） |
| 达标分支 | 进度 1.0/0.8 → +100 万；0.5 → −10 万违约金 +30 万首期 |
| 最短路径 | A→B→C = 100+200 = **300km**；运费 = 300×12 + 0.3×300 = 3690；碳税 12 |
| 超重加价 | 载重 30、货重 40 → 运费 ×1.1 = 4059，违约金 405.9 |
| 动态键循环 | 期数 6 → 还款计划字典登记 6 次；2 种基建 → 在建清单登记 2 次 |

`fields` 的断言**按参与方角色分组**——引擎返回的键是 `"{公司id}:{字段key}"`，
多公司参与时（运输合同的承运方 + 委托方）只按字段名汇总会拿错公司的值。

---

## 12. 文件与测试

| 文件 | 作用 |
| --- | --- |
| [`backend/apps/contracts/builder/__init__.py`](../backend/apps/contracts/builder/__init__.py) | 对外入口（`ContractType` / 效果 / 值 / 聚合 / 体检） |
| [`backend/apps/contracts/builder/builder.py`](../backend/apps/contracts/builder/builder.py) | 构建器主体、控制流、条件与分支的两种形状、`default_inputs()` |
| [`backend/apps/contracts/builder/effects.py`](../backend/apps/contracts/builder/effects.py) | 11 种具名效果、编译规则、反解 |
| [`backend/apps/contracts/builder/values.py`](../backend/apps/contracts/builder/values.py) | 值层、实体属性白名单、输入类型、`range_list` / `concat_text` / `input_value` |
| [`backend/apps/contracts/builder/refs.py`](../backend/apps/contracts/builder/refs.py) | 比赛数据快照、实体引用、隐藏槽位 |
| [`backend/apps/contracts/builder/aggregates.py`](../backend/apps/contracts/builder/aggregates.py) | 8 类聚合函数 + 具名短名 |
| [`backend/apps/contracts/builder/validate.py`](../backend/apps/contracts/builder/validate.py) | 静态体检（60 个检查项） |
| [`backend/apps/contracts/builder/errors.py`](../backend/apps/contracts/builder/errors.py) | 异常与「最相近名字」建议 |
| [`backend/apps/contracts/management/commands/build_contract_types.py`](../backend/apps/contracts/management/commands/build_contract_types.py) | 命令行 |
| [`backend/examples/contracts/demo_contracts.py`](../backend/examples/contracts/demo_contracts.py) | 入门示例（3 个合同类型） |
| [`backend/examples/contracts/complex_contracts.py`](../backend/examples/contracts/complex_contracts.py) | **复杂案例集（6 个，覆盖最难画的逻辑）** |
| [`backend/apps/contracts/tests/test_type_builder.py`](../backend/apps/contracts/tests/test_type_builder.py) | 编译契约、抽象降低、体检、引擎执行、反解、默认值补齐 |
| [`backend/apps/contracts/tests/test_named_effect_semantics.py`](../backend/apps/contracts/tests/test_named_effect_semantics.py) | **逐条**验证每种具名效果的真实引擎行为 |
| [`backend/apps/contracts/tests/test_complex_contracts.py`](../backend/apps/contracts/tests/test_complex_contracts.py) | **复杂案例的金额级验收**（34 条） |

```powershell
cd backend
.\.venv\Scripts\python.exe manage.py test apps.contracts apps.preparation
```

测试要点：

- **编译契约**：四份 JSON 的形状、15 种输入类型、5 种检查、11 种效果、控制流；
- **引擎执行（端到端）**：把编译产物喂给 `ContractEngine.execute`（事务回滚），
  断言 `checks` 与字段落库值——**「本库产出的 JSON 引擎能不能吃」是被证明的，不是被假设的**；
- **具名效果语义**：18 条测试逐条验证「名字 ↔ 真实行为」一致，
  包括「字典三种语义互不串味」的对照测试；
- **体检**：60 个检查项（错形状/引用/类型/静默降级四类），关键项各有正例与反例；
- **构建期硬错误**：重名、引用缺失、类型不符、空参数、控制流作用域、漏挂载；
- **反解往返**：反解再编译与原 JSON 逐字节一致；
- **一致性防漂移**：输入类型与前端、实体类型与引擎、属性白名单与模型字段三方对拍。

---

## 相关文档

- [比赛建包库完整 API 手册](BUILD_COMPETITION_API_REFERENCE.md) —— 用代码创建**比赛内容**（公司/地图/物资/…）
- [用代码创建比赛内容](BUILD_COMPETITION_BY_CODE.md) —— 比赛建包库总览
- [合同可视化新建操作指南](合同可视化新建操作指南.md) —— 可视化编辑器（本方案的对照物）
