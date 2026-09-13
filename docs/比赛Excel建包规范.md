# 比赛 Excel 建包规范

> 目标：用表格文件（Excel / CSV）**快速建出一场比赛的框架**，并且**一张工作表 = 一类内容**，
> 表与表之间相互隔离 —— 想建什么就放哪张表，不放的表完全不参与产出。
>
> **表头用中文**（如「产业名称」「字段键」「地点价」）；程序也接受英文参数名（老文件兼容），
> 两者指向同一列，同一列不要写两遍。逐步上手的教程见 [**比赛 Excel 建包教程**](比赛Excel建包教程.md)。
>
> 本规范**没有新的落库路径**：表格先被翻译成比赛建包库（`CompetitionBuilder`）的调用，
> 产出与「代码建包 / 前端导入归档」完全同构的归档 JSON，再交给既有的
> `apps.preparation.archive.apply_import` 落库。因此比赛隔离、外键映射、追加/覆盖、
> 空比赛保护、dry-run 回滚这些既有语义全部原样适用。

```
表格文件(.xlsx) ──┐
                  ├─▶ sheet_spec 翻译 ─▶ CompetitionBuilder ─▶ 归档 JSON ─▶ apply_import ─▶ 比赛框架
CSV 目录/         ─┘
```

---

## 0. 边界：什么进表格，什么不进

**只把「比赛框架」交给表格** —— 也就是换一场比赛仍然成立的口径与规则：

| 进表格（本规范覆盖，21 张表） | 说明 |
| --- | --- |
| 比赛 / 财年 | 比赛名与状态、地图背景图、财年 |
| **股票参数** | 股票市场的**规则**：单轮限幅、单轮最大波动、做市商数量/点差、随机事件、估值回归…（键值两列，留空 = 沿用系统默认） |
| 产业类型 / 产业字段 | 行业口径：有哪些产业、每个产业有哪些字段（合同/图表都按它绑定） |
| 区域 | 比赛内的区域划分（消费者需求按它聚合） |
| 地图节点类型 / 路径类型 / 地图节点 / 地图连线 | 世界结构与物流网络 |
| 燃料 / 原料 / 科技 / 生产线 / 基建 / 仓库 / 零件 / 产品 / 载具 | 物资与产能（配方、地点价、科技前置） |
| 消费者需求 | 各区域对产品的需求量 |
| 合同类型 | 合同模板（全局资源）—— **表格里只写脚本路径**，四份 JSON 由「合同类型代码化」脚本产出（见第 4 节） |

> 合同类型**一律用代码创建**（`apps.contracts.builder` 的具名效果 + 比较表达式），
> 表格里不再手写参与方 / 输入项 / 效果 / 前置检查这四份 JSON：
> 手写 JSON 最容易写错，而引擎对写错的形状往往**静默按 0 计算**或让检查**恒不通过**。
> 写法见 [`docs/CONTRACT_TYPE_BY_CODE.md`](CONTRACT_TYPE_BY_CODE.md)，
> 现成脚本见 `backend/examples/contracts/`（`auto_chain_contracts.py`、`mini_contracts.py`）。

| **不进表格**（运行期数据） | 去哪里维护 |
| --- | --- |
| 公司、公司字段初始值 | 「公司管理」界面（推荐），或用代码建包脚本 |
| 账号与权限 | 「账号管理」界面（涉及口令安全） |
| 区域总览卡片 | 「区域总览」界面 |
| 比赛内的预置合同（合同实例） | 「合同管理」界面 |
| 比赛内消息 | 「消息中心」 |
| **个股**（代码/名称/股本/初始净利润/PE 联动/碳排·幸福度绑定） | 「股票管理」—— 它绑定具体公司、PE 联动公司与字段主键、总览卡片引用 |
| **资金账户**（公司户 / 个人户、绑定产业字段联动现金） | 「股票管理」—— 它绑定具体公司或用户 + 字段主键 |
| **持仓 / 委托 / K 线** | 由「股票行情」下单与「推进轮次」在运行时生成，无法预置 |

理由很简单：这些内容**绑定具体公司、具体人和具体主键**，换一场比赛就要重做一遍，
混进表格只会让「框架」和「这一场的参赛者」搅在一起。工作簿里若出现这些表名，
程序会在提示里明确告诉你「该去哪里维护」，而不是静默忽略：

```
· 工作表「公司」不属于表格规范的「比赛框架」，已跳过：参赛主体属于运行期数据：
  请在「公司管理」界面维护，或用代码建包脚本 examples/competitions/auto_chain_competition.py
```

> 想「框架 + 参赛主体」一次建齐，用代码建包脚本
> `python manage.py build_competition examples/competitions/auto_chain_competition.py --competition <id>`。
> 两层可以混用：先导表格框架，再用脚本/界面补主体（框架部分会被识别为已存在而保留）。

---

## 1. 快速开始

```powershell
cd backend
$env:PYTHONUTF8='1'

# ① 打印规范（本文档第 5 节就是它的产物，可随时重新生成）
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py --spec

# ② 生成空白模板（每张表的表头 + 一行示例 + 空行，另附「说明」表）
.\\.venv\\Scripts\\python.exe examples/excel/make_template.py --out examples/excel/比赛建包模板.xlsx

# ③ 只读表格、看看会建出什么（不连库、不写任何东西）
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛框架.xlsx --inspect

# ④ 写出归档 JSON（可以拿去前端「导入归档」上传）
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛框架.xlsx --out 框架.json

# ⑤ 建比赛 + 预演 + 真正导入（一条命令）
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛框架.xlsx --create-competition --dry-run
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛框架.xlsx --create-competition

# ⑥ 导入到已存在的比赛；或只导某个分组 / 只处理某几张表
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛框架.xlsx --competition 189 --scope supply
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的比赛框架.xlsx --competition 189 --sheets 产业类型,产业字段

# ⑦ 也可以用「一个目录 + 每张表一个 CSV」当输入（便于进 git / diff）
.\\.venv\\Scripts\\python.exe examples/excel/build_from_sheets.py 我的表目录 --inspect
.\\.venv\\Scripts\\python.exe examples/excel/make_template.py --from-sheets 我的表目录 --out 框架.xlsx
```

现成可用的例子：[`backend/examples/excel/汽车产业链示例.xlsx`](../backend/examples/excel/汽车产业链示例.xlsx)
（汽车产业链完整框架：3 产业 / 8 节点 / 5 原料 / 5 零件 / 3 产品 / 3 合同类型）、
空白模板 [`比赛建包模板.xlsx`](../backend/examples/excel/比赛建包模板.xlsx)、
教程用的 [`最小示例.xlsx`](../backend/examples/excel/最小示例.xlsx)（最小框架，17 张工作表 = 16 张业务表 + 1 张「说明」表）。

命令参数一览：

| 参数 | 作用 |
| --- | --- |
| `--inspect` | 只打印产出摘要与体检提醒，不导入 |
| `--out <path>` | 写出归档 JSON（可拿去前端「比赛准备 → 导入归档」上传） |
| `--create-competition` | 按「比赛」表的名称新建比赛（同名复用），再导入 |
| `--competition <id>` | 导入到该比赛 |
| `--dry-run` | 预演导入（事务回滚，一行都不落库） |
| `--mode append\|overwrite` | 追加（默认，已存在的保留）/ 覆盖（已存在的按本包更新） |
| `--scope <分组>` | 只**导入**该分组：`competition` / `industry` / `geo` / `supply` / `tech` / `market` |
| `--sheets a,b` | 只**处理**这几张表（引用缺失会立刻报错并给出提示） |
| `--name <比赛名>` | 覆盖「比赛」表里的名称（表里没有「比赛」表时作为兜底名） |
| `--allow-non-empty` | 允许导入到已有业务数据的比赛 |
| `--spec` / `--list-sheets` | 打印规范 / 表清单 |

退出码：`0` 成功；`1` 表格格式错误或导入出现 problem；`2` 用法错误。

---

## 2. 表与隔离：怎么理解「不同表建不同内容」

1. **只处理出现在表格里的表**。工作簿里没有的表完全不参与产出 —— 这就是内容隔离。
   `--inspect` 会列出「已处理的工作表」，一眼就能确认这次到底建了什么。
2. **引用表要一起放**。引用是被建包库当场校验的（拼错会立刻报错，而不是导入时才炸）：
   - `产业字段` → 需要 `产业类型`（可以写 code，也可以写名称）；
   - `零件` → 需要 `原料`、`科技`；`产品` → 需要 `零件`；
   - `载具` → 需要 `燃料`、`路径类型`；`地图连线` → 需要两个 `地图节点`；
   - `原料` 的地点价 → 需要对应 `地图节点`；`消费者需求` → 需要 `区域`（按名匹配）。
   少放了会得到可执行的提示，例如：
   `[产业字段] 第 2 行：… 引用的 产业类型（全局）「原料开采」尚未在本构建器中登记；本工作簿里没有「产业类型」表——请把它一并放进来（它是全局口径，很小）`
3. **`--sheets` 与 `--scope` 不是一回事**：
   - `--sheets` 决定**建包时处理哪些表**（真正的裁剪，用于「这个工作簿里有些表我现在不想建」）；
   - `--scope` 决定**落库时写哪个分组**（产出仍按整份表格建，只是导入被过滤）。
   只想补产业口径时就带上引用表并用 `--scope industry`：
   ```powershell
   python examples/excel/build_from_sheets.py 我的比赛框架.xlsx --sheets 产业类型,产业字段 --competition 189 --scope industry
   ```
4. **可以拆成多个文件**（按关注点分工，一人一张表）：每个文件只要包含自己那张表 + 它引用的表即可；
   `--name` 能让一个没有「比赛」表的文件也参与建档。

---

## 3. 单元格语法与表头

**表头默认用中文**（见第 5 节每张表的「表头」列）；程序同时接受英文参数名（老文件与代码口径都能用）：

| 表头写法 | 是否可用 | 说明 |
| --- | :---: | --- |
| `产业名称` / `字段名称` / `字段键` … | ✅ 推荐 | 中文表头，见第 5 节 |
| `name` / `field_key` / `field_type` … | ✅ | 英文参数名，与中文表头指向同一列 |
| 中文表头 + 英文参数名同时出现 | ❌ | 报「表头重复」，只留一个 |
| 自造列名 | ❌ | 报「规范之外的列」，并列出本表可用列 |

| 需求 | 写法 |
| --- | --- |
| 布尔 | `是/否`、`TRUE/FALSE`、`1/0`、`y/n` |
| 列表（路径类型、前置科技…） | `公路;铁路`（分号、顿号、逗号、换行都可以当分隔符） |
| 键值（配比、地点价…） | `锂矿石*4; 铝土矿*1` 或 `白云鄂博矿区:180; 上游集运站:195` |
| 复杂结构（计算图、字典配置…） | 以 `{` 或 `[` 开头的单元格按 **JSON** 解析 |
| 注释行 | 行首写 `#` 或 `//`，整行忽略 |
| 留空 | 该参数不传，用建包库默认值 |

金额 / 单价 / 配比这类列**建议直接写数字文本**（`600000`），程序按文本保精度；
含 JSON 的单元格里可以有逗号，切分时会自动跳过 JSON 与引号内部。

> 表名也要用规范里的名字（`产业字段`、`地图连线`…）。放一张规范里没有的表不会报错，
> 但会在提示里说明「不在规范内，已忽略」；公司 / 账号 / 卡片 / 合同实例 / 消息 / 股票相关表名
> 会额外说明**该去哪里维护**。

---

## 4. 数值口径与类型对照

| 表 | 表头 | 说明 |
| --- | --- | --- |
| 产业字段 | `所属产业` | 可以写 `2001` 也可以写 `原料开采`（内部会归一成名称） |
| 产业字段 | `字段键` | 唯一标识这个字段（英文，公式里当变量名用）；`字段名称` 才是中文显示名 |
| 产业字段 | `计算图` | 计算字段写 `cash + bank_deposit` 即可；多字段会串成嵌套 ADD；也可直接贴 GGraph JSON |
| 产业字段 | `类型配置` | 写 `NUMBER` 等价于 `{"valueType": "NUMBER"}`；也可直接贴 JSON |
| 地图节点 | `所属区域` | 是**文本**（不是外键），区域总览按它归属 |
| 原料 | `地点价` | `节点名:价格`；同一种原料可在不同节点不同价 |
| 零件 / 产品 | `原料配比` / `零件配比` | `名称*数量`；依赖方向固定为 原料 → 零件 → 产品 |
| 合同类型 | `脚本路径` | **必填**：指向「合同类型代码化」脚本（如 `examples/contracts/auto_chain_contracts.py`）；相对 backend 目录或表格所在目录都可以 |
| 合同类型 | `类型标识` | 留空 = 引入该脚本产出的**全部**合同类型；填了 = 只引入这一个（写错会列出该脚本实际产出哪些） |
| 合同类型 | `是否启用` | 对应合同类型的 `enabled` 开关 |
| 股票参数 | `参数` | 参数键，必须与 `apps.stock.engine.DEFAULT_STOCK_CONFIG` 一致（写错会报错并给出最相近的名字） |
| 股票参数 | `值` | 按该键默认值的类型解析：布尔写 `是/否`；`interventionMode` 写 `regression` / `expand-limit`；其余为数值（不接受负数） |

> **股票参数是唯一的「股票类」框架表**：它只描述市场规则，不涉及任何公司、人或主键。
> 键值两列、每行一个参数，**只填你要改的**（没写的键在运行期由
> `resolve_stock_config()` 补回系统默认）：

| 参数 | 值 |
| --- | --- |
| limitPct | 0.08 |
| maxMovePct | 0.05 |
| mmMinQty | 500 |
| mmMaxQty | 20000 |
| mmSelfTradeEnabled | 否 |
| interventionMode | expand-limit |

表格层会替你挡住三类问题：**未知参数名**（给最相近的名字）、
**`limitPct` < `maxMovePct`**、**`mmMinQty` > `mmMaxQty`**；
另外 `limitPct > 0.10` 会给一条「更容易被拉板」的提示（引擎的防连板机制仍会兜底）。

>
> **合同类型不在表格里手写 JSON**。四份 JSON（参与方 / 输入项 / 效果 / 前置检查）全部由
> `apps.contracts.builder.ContractType` 产出，脚本可以直接跑体检与试算：

```python
# examples/contracts/mini_contracts.py（节选）
from apps.contracts.builder import ContractType

def build():
    ct = ContractType("mini-sale", "简易购销合同")
    seller, buyer = ct.party("seller", "卖方"), ct.party("buyer", "买方")
    amount = ct.input("amount", "成交金额", "number", required=True, default="1000")
    ct.check(buyer.field("cash") >= amount, error="买方现金不足以支付货款")
    ct.sub_number(buyer.field("cash"), amount)
    ct.add_number(seller.field("cash"), amount)
    return ct
```

```powershell
python manage.py build_contract_types examples/contracts/mini_contracts.py --competition <比赛id> --check   # 静态体检
python manage.py build_contract_types examples/contracts/mini_contracts.py --competition <比赛id> --trial   # 真实引擎试算
python manage.py build_contract_types examples/contracts/mini_contracts.py --competition <比赛id> --import  # 直接导入
```

> 计算图的坑：建包库自带的 `calc_node/calc_graph` 产出的是**合同编辑器风格**的图，
> 产业计算字段求值器不认（字段会永远是空的）。本规范里的 `计算图` 列按求值器认识的
> GGraph 结构生成（`output` / `value` + `data.kind` + `sourceHandle/targetHandle`），
> 详见 [`汽车产业链测试赛准备.md` 第 6 节](汽车产业链测试赛准备.md#6-测试途中查出的问题与注意点未做任何修复)。

---

## 5. 表清单与列定义

以下是 `build_from_sheets.py --spec` 的产物（与 `sheet_spec.py` 同源，改动代码后重新生成即可）。
每张表的「分组」就是 `--scope` 的取值。

<!-- SPEC:BEGIN -->
### 比赛（分组：competition）

比赛本身：名称、状态、地图背景图（整表一行）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 比赛名称 | `name` | 比赛名称（全局唯一） | 文本 | 是 |
| 状态 | `status` | ACTIVE / CLOSED | 文本 |  |
| 地图背景图地址 | `map_background_url` | 地图背景图地址 | 文本 |  |
| 背景图宽 | `map_background_width` | 背景图宽 | 数字（可按文本填写以保精度） |  |
| 背景图高 | `map_background_height` | 背景图高 | 数字（可按文本填写以保精度） |  |

示例行：2026 汽车产业链测试赛 | ACTIVE |  |  | 

### 财年（分组：competition）

财年：新建 / 由非 ACTIVE 改为 ACTIVE 会触发 FY_START 定时器

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 年份 | `year` | 年份 | 数字（可按文本填写以保精度） | 是 |
| 状态 | `status` | ACTIVE / CLOSED | 文本 |  |

示例行：2026 | ACTIVE

### 股票参数（分组：competition）

股票市场的**规则**（单轮限幅 / 最大波动 / 做市商 / 随机事件…）：键值两列，每行一个参数；留空表示沿用系统默认。个股与资金账户绑定公司/人/主键，不在表格内（去「股票管理」维护）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 参数 | `param` | 参数（键名与系统默认配置一致） | 文本 | 是 |
| 值 | `value` | 值（数值 / 是·否 / regression·expand-limit） | 文本 | 是 |

示例行：limitPct | 0.10

### 产业类型（分组：industry）

全局资源：行业口径（按 code 跨比赛复用，不要给不同行业用同一个 code）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 编码 | `code` | 数字编码（全局唯一） | 数字（可按文本填写以保精度） | 是 |
| 产业名称 | `name` | 产业名称 | 文本 | 是 |
| 说明 | `description` | 说明 | 文本 |  |
| 图标 | `icon` | 图标 | 文本 |  |

示例行：2001 | 原料开采 | 汽车产业链上游 | 

### 产业字段（分组：industry）

全局资源：产业下的字段（合同、图表、股票都按 field_key 绑定）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 所属产业 | `industry_type` | 所属产业（code 或名称） | 文本 | 是 |
| 字段名称 | `name` | 字段显示名 | 文本 | 是 |
| 字段键 | `field_key` | 字段键（英文，公式里要用） | 文本 | 是 |
| 字段类型 | `field_type` | STRING/NUMBER/BOOLEAN/DICTIONARY/LIST | 文本 |  |
| 默认值 | `default_value` | 默认值 | 文本 |  |
| 是否计算字段 | `is_calculated` | 是否计算字段 | 是/否 |  |
| 计算图 | `graph` | 计算图：`cash + bank_deposit` 或 GGraph JSON | JSON 文本 |  |
| 启用财年定时器 | `timer_enabled` | 启用财年定时器 | 是/否 |  |
| 定时器时机 | `timer_trigger` | FY_START / FY_END | 文本 |  |
| 定时器写入值 | `timer_value` | 定时器写入值 | 文本 |  |
| 排序 | `sort_order` | 界面排序 | 数字（可按文本填写以保精度） |  |
| 是否展示 | `visible` | 是否展示 | 是/否 |  |
| 类型配置 | `config` | 类型配置 JSON 或 valueType | 文本 |  |

示例行：原料开采 | 现金 | cash | NUMBER | 0 |  |  |  |  |  | 2 | 是 | 

### 区域（分组：geo）

比赛内区域（区域总览、消费者需求按它聚合）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 区域名称 | `name` | 区域名（比赛内唯一） | 文本 | 是 |
| 说明 | `description` | 说明 | 文本 |  |

示例行：上游资源区 | 锂 / 铝 / 铁矿与橡胶硅砂资源带

### 地图节点类型（分组：geo）

地图节点分类（矿区 / 港口 / 城市 …）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 类型名称 | `name` | 类型名 | 文本 | 是 |
| 说明 | `description` | 说明 | 文本 |  |
| 颜色 | `color` | 颜色，如 #b45309 | 文本 |  |

示例行：矿区 | 原矿开采地 | #b45309
示例行：物流枢纽 | 集运站 / 港口 / 铁路货场 | #0ea5e9

### 路径类型（分组：geo）

道路类型（公路 / 铁路 / 航运）；载具按它判断可通行

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 类型名称 | `name` | 类型名 | 文本 | 是 |
| 说明 | `description` | 说明 | 文本 |  |
| 颜色 | `color` | 颜色 | 文本 |  |

示例行：公路 | 通用公路运输 | #94a3b8

### 地图节点（分组：geo）

地图节点（region 是文本列，不是外键）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 节点名称 | `name` | 节点名（比赛内唯一） | 文本 | 是 |
| 节点类型 | `node_type` | 节点类型（名称） | 文本 | 是 |
| 所属区域 | `region` | 所属区域名（文本） | 文本 |  |
| X坐标 | `x` | 画布 x 坐标 | 数字（可按文本填写以保精度） |  |
| Y坐标 | `y` | 画布 y 坐标 | 数字（可按文本填写以保精度） |  |

示例行：白云鄂博矿区 | 矿区 | 上游资源区 | 140 | 120
示例行：上游集运站 | 物流枢纽 | 上游资源区 | 360 | 300

### 地图连线（分组：geo）

节点之间的连线；同一对「起点+终点」只能有一条（反向算另一条）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 起点节点 | `from_node` | 起点节点 | 文本 | 是 |
| 终点节点 | `to_node` | 终点节点 | 文本 | 是 |
| 距离(公里) | `distance` | 距离（公里） | 数字（可按文本填写以保精度） | 是 |
| 路径类型 | `path_type` | 路径类型（名称） | 文本 | 是 |

示例行：白云鄂博矿区 | 上游集运站 | 120 | 公路

### 燃料（分组：supply）

燃料（载具必须绑定燃料，外键 PROTECT）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 燃料名称 | `name` | 燃料名 | 文本 | 是 |
| 每升单价 | `price_per_liter` | 每升单价 | 数字（可按文本填写以保精度） |  |

示例行：柴油 | 7.6

### 原料（分组：supply）

原料（地点价按地图节点名写；运输与运费计算都依赖它）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 原料名称 | `name` | 原料名 | 文本 | 是 |
| 产地 | `origin` | 产地（通常写地图节点名） | 文本 |  |
| 碳排系数 | `carbon_emission_coefficient` | 碳排系数 | 数字（可按文本填写以保精度） |  |
| 类型 | `type` | NORMAL / SPECIAL | 文本 |  |
| 地点价 | `node_prices` | 地点价：`白云鄂博矿区:180; 上游集运站:195` | 键值（名称:数值，分号分隔） |  |

示例行：锂矿石 | 白云鄂博矿区 | 0.52 | NORMAL | 白云鄂博矿区:180; 上游集运站:195

### 科技（分组：supply）

科技节点（零件 / 产品按它设前置）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 科技名称 | `name` | 科技名 | 文本 | 是 |
| 层级 | `tier` | 层级 | 数字（可按文本填写以保精度） |  |
| 研发费用 | `research_cost` | 研发费用 | 数字（可按文本填写以保精度） |  |
| 说明 | `description` | 说明 | 文本 |  |
| 前置科技 | `prerequisites` | 前置科技：`高炉冶炼;转炉炼钢` | 列表（分号分隔） |  |

示例行：电池成组技术 | 1 | 80000 | 解锁动力电池包 | 

### 生产线（分组：supply）

生产线（产能与用工人数）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 生产线名称 | `name` | 生产线名 | 文本 | 是 |
| 单价 | `price` | 单价 | 数字（可按文本填写以保精度） |  |
| 用工人数 | `labor_count` | 用工人数 | 数字（可按文本填写以保精度） |  |
| 年产能 | `max_per_year` | 年产能 | 数字（可按文本填写以保精度） |  |

示例行：电芯产线 | 2400000 | 120 | 6000

### 基建（分组：supply）

基建及其 6 项加成（合同可按清单聚合这些属性）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 基建名称 | `name` | 基建名 | 文本 | 是 |
| 占地面积 | `footprint` | 占地面积 | 数字（可按文本填写以保精度） |  |
| 单价 | `price` | 单价 | 数字（可按文本填写以保精度） |  |
| 启用费用 | `activation_price` | 启用费用 | 数字（可按文本填写以保精度） |  |
| 就业率加成 | `employment_rate_bonus` | 就业率加成 | 数字（可按文本填写以保精度） |  |
| 人口加成 | `population_bonus` | 人口加成 | 数字（可按文本填写以保精度） |  |
| 高素质人口加成 | `high_quality_population_bonus` | 高素质人口加成 | 数字（可按文本填写以保精度） |  |
| 幸福度加成 | `happiness_index_bonus` | 幸福度加成 | 数字（可按文本填写以保精度） |  |
| 人均收益加成 | `per_capita_income_bonus` | 人均收益加成 | 数字（可按文本填写以保精度） |  |
| 减碳加成 | `carbon_reduction_bonus` | 减碳加成 | 数字（可按文本填写以保精度） |  |

示例行：光伏电站 | 160 | 1200000 | 50000 | 0.02 |  |  |  |  | 0.12

### 仓库（分组：supply）

仓库（MATERIAL / PART / PRODUCT / FUEL 四种建议都覆盖）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 仓库名称 | `name` | 仓库名 | 文本 | 是 |
| 仓库种类 | `type` | MATERIAL/PART/PRODUCT/FUEL | 文本 | 是 |
| 容量 | `capacity` | 容量 | 数字（可按文本填写以保精度） |  |
| 单价 | `price` | 单价 | 数字（可按文本填写以保精度） |  |

示例行：原料仓 | MATERIAL | 30000 | 400000

### 零件（分组：supply）

零件：原料配比 + 科技前置（配比只能引用原料）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 零件名称 | `name` | 零件名 | 文本 | 是 |
| 原料配比 | `materials` | 原料配比：`锂矿石*4; 铝土矿*1` | 键值（名称:数值，分号分隔） |  |
| 所需科技 | `tech` | 所需科技：`电池成组技术` | 列表（分号分隔） |  |

示例行：动力电池包 | 锂矿石*4 | 电池成组技术

### 产品（分组：supply）

产品：零件配比 + 科技前置（配比只能引用零件）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 产品名称 | `name` | 产品名 | 文本 | 是 |
| 零件配比 | `parts` | 零件配比：`动力电池包*1; 驱动电机*1` | 键值（名称:数值，分号分隔） |  |
| 所需科技 | `tech` | 所需科技 | 列表（分号分隔） |  |

示例行：纯电轿车 | 动力电池包*1 | 电池成组技术

### 载具（分组：supply）

载具：绑定燃料 + 可通行路径类型（缺路径类型会导致运输校验失败）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 载具名称 | `name` | 载具名 | 文本 | 是 |
| 燃料 | `fuel` | 燃料（必填） | 文本 | 是 |
| 可通行路径类型 | `path_types` | 可通行路径类型：`公路;铁路` | 列表（分号分隔） |  |
| 每公里油耗 | `fuel_consumption_per_km` | 每公里油耗 | 数字（可按文本填写以保精度） |  |
| 载货量 | `max_cargo` | 载货量 | 数字（可按文本填写以保精度） |  |
| 单价 | `price` | 单价 | 数字（可按文本填写以保精度） |  |
| 碳排系数 | `carbon_emission` | 碳排系数 | 数字（可按文本填写以保精度） |  |

示例行：重型卡车 | 柴油 | 公路 | 0.35 | 30 | 260000 | 0.9

### 消费者需求（分组：tech）

区域消费者需求（导入按「区域+产品+数量」去重，改数量 = 新增一条）

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 区域名称 | `region` | 区域名（文本） | 文本 | 是 |
| 产品名称 | `product` | 产品名（需已登记） | 文本 | 是 |
| 需求量 | `quantity` | 需求量 | 数字（可按文本填写以保精度） | 是 |
| 备注 | `note` | 备注 | 文本 |  |

示例行：东部车都 | 纯电轿车 | 1200 | 城市通勤主力车型

### 合同类型（分组：market）

合同类型**只由代码脚本创建**（合同类型代码化建库）：本表只写脚本路径与要引入的类型标识

| 表头 | 参数名 | 说明 | 类型 | 必填 |
| --- | --- | --- | --- | :---: |
| 脚本路径 | `script` | 脚本路径（相对 backend 或表格所在目录） | 文本 | 是 |
| 类型标识 | `key` | 类型标识：留空 = 引入该脚本的全部合同类型；填了 = 只引入这一个 | 文本 |  |
| 是否启用 | `enabled` | 是否启用 | 是/否 |  |

示例行：examples/contracts/auto_chain_contracts.py | auto-mining | 是

<!-- SPEC:END -->

---

## 6. 与代码建包、界面维护的关系

| | 表格建包（本规范） | 代码建包 | 界面维护 |
| --- | --- | --- | --- |
| 覆盖 | **比赛框架** | 框架 + 参赛主体（全量） | 运行期数据 |
| 入口 | `examples/excel/build_from_sheets.py 表格.xlsx` | `manage.py build_competition 脚本.py` | 前端各管理页 |
| 适合 | 策划/运营改口径，不碰代码 | 需要编程（循环、公式、批量生成） | 建公司、发账号、签合同、发消息 |
| 落库 | `archive.apply_import` | 同一个 `archive.apply_import` | 既有接口 |

三者可以混用：**先用表格建框架，再用界面（或代码脚本）补参赛主体**，
它们产出的归档 JSON 结构完全一致，可以互相追加/覆盖。

### 实测：表格框架 vs 代码建包（同一套汽车产业链内容）

- 表格覆盖 **26 类资源**，其中 **24 类与代码建包逐行完全一致**
  （比赛信息、财年、产业类型、区域、地图、原料、科技、零件、产品、载具、需求…）；
- **合同类型 3 个 key 的四份 JSON 与代码建包逐字段一致**：表格导入后用
  `manage.py build_contract_types examples/contracts/auto_chain_contracts.py --competition <id> --import`
  复查，结果是 `[相同] 无需更新` ×3 —— 两条路径同源，不存在「手写 JSON 与代码不一致」的风险；
- 2 类为**无害差异**：`industryFields`（额外字段排序、计算图节点 id/坐标不同）、
  `pathTypes`（示例表格多写了 description）；
- 代码建包**多出来的 6 类正是运行期数据**：`companies`、`companyFieldValues`、
  `contractInstances`、`overviewCards`、`messages`、`users` —— 与第 0 节的边界完全吻合。

功能级验证：先用表格建出框架（**公司 / 账号 / 合同实例均为 0**），
再用代码脚本补上参赛主体，然后跑真实引擎：

```
合同类型试算：auto-mining 9/9、auto-purchase-sale 9/9、auto-transport 9/9 家公司通过
合同冒烟：开采 20 吨 → 1,360 元 + 配额 20 + 原矿 20；购销 20 吨锂矿石 @180 → 3,600 元；
         运输 540 km → 运费 6,858 + 碳税 48.6（全部事务回滚，不落库）
股票系统：stocks=0 / 资金账户=0
```

---

## 7. 注意点

1. **公司、账号、卡片、合同实例、消息不在表格里**（见第 0 节）：它们是运行期数据，在界面维护。
   在界面上维护时要注意既有语义：
   - 新建账号密码是随机值且强制首次登录改密，需超管在「账号管理」重置后再交付选手；
   - 账号是**全局**的：同一个用户名出现在第二场比赛时只会合并公司范围，不会改归属比赛；
   - 区域总览卡片绑定的是**产业字段主键**，字段是全局资源、跨比赛复用，一般无需重建；
   - 比赛内消息不做判重，重复发布会产生多条，注意清理。
2. **合同类型一律由代码脚本创建**（第 4 节）：表格里只写脚本路径 + 类型标识；
   脚本本身可以直接体检与试算
   （`build_contract_types <脚本> --competition <id> --check/--trial/--import`），
   改完脚本记得用 `--mode overwrite` 刷新已存在的合同类型。
   比赛内的**合同实例**（绑定具体公司）由界面创建，不随框架导入。
3. **老文档的两种写法仍会被自动归一**（并打印提示），作为安全网保留：
   若脚本用 `keep_effects()` 保留了旧 JSON，其中的
   `{"from": "input", "key": X}` 会被归一成 `{"type": "INPUT", "key": X}`
   （不归一的话引擎会**静默按 0 计算**），检查种类 `"kind": "FIELD"` 会被归一成
   `"FIELD_COMPARE"`（引擎没有 `FIELD` 这个检查种类，写成它会**恒不通过**）。
   这两处正是建包库文档与 `demo_competition.py` 里的写法 —— 新写脚本时不要照抄。
4. **文件格式**：`.xlsx` 由本仓库的极简读写器生成（纯标准库，未引入 openpyxl/pandas），
   Excel / WPS / LibreOffice 均可打开与另存；也可以用「目录 + CSV」完全绕开 Excel。
5. **计算字段**：只在「接口写公司字段」与「财年开始」时重算，合同落账不会触发；
   需要时跑 `auto_chain_setup.py --recompute-calc`。
6. **股票参数（`stockConfig`）的三条注意**：
   - 导入**不受 `append` / `overwrite` 影响，会直接覆盖**目标比赛的参数（`_imp_stock_config` 无条件写）
     → 建议先 `--dry-run` 再真导；想保留原配置就先导出备份；
   - 表格**只能设定参数，不能「恢复系统默认」**：归档虽有 `isDefault` 行，但建包库的
     `stock_config_set()` 不接受空字典 → 重置默认请在界面/接口把 `stockConfig` 置 `null`
     （`PATCH /api/competitions/:id {"stockConfig": null}`）；
   - 前端目前**没有比赛级股票参数页面**（只有「推进轮次」时的高级临时覆盖），
     所以这张表也是目前唯一「配置比赛级股票规则」的体面入口；
   - 个股与资金账户**不在表格内**：它们绑定公司/人/字段主键，去「股票管理」维护。

---

## 8. 文件

| 文件 | 作用 |
| --- | --- |
| [`docs/比赛Excel建包教程.md`](比赛Excel建包教程.md) | **逐步上手教程**（从空表到可打的比赛、常见错误速查） |
| [`backend/examples/excel/sheet_spec.py`](../backend/examples/excel/sheet_spec.py) | **规范本体**：表清单、列定义、中文表头、单元格语法、每张表的建包映射、边界（`OUT_OF_SCOPE_SHEETS`） |
| [`backend/examples/excel/build_from_sheets.py`](../backend/examples/excel/build_from_sheets.py) | 读表格 → 建包 → 导入（也支持 `--out` 只产出归档 JSON） |
| [`backend/examples/excel/make_template.py`](../backend/examples/excel/make_template.py) | 生成空白模板；xlsx ↔ CSV 目录互转 |
| [`backend/examples/excel/make_sample_auto_chain.py`](../backend/examples/excel/make_sample_auto_chain.py) | 生成汽车产业链框架示例 / 最小框架示例 |
| [`backend/examples/excel/xlsx_io.py`](../backend/examples/excel/xlsx_io.py) | 极简 xlsx / CSV 读写（纯标准库） |
| [`backend/examples/excel/比赛建包模板.xlsx`](../backend/examples/excel/比赛建包模板.xlsx) | 空白模板（22 张工作表 = 21 张业务表 + 1 张「说明」表；含边界说明与表头↔参数名对照） |
| [`backend/examples/excel/汽车产业链示例.xlsx`](../backend/examples/excel/汽车产业链示例.xlsx) | 汽车产业链完整框架（21 张工作表 = 20 张业务表 + 1 张「说明」表） |
| [`backend/examples/excel/最小示例.xlsx`](../backend/examples/excel/最小示例.xlsx) | 教程用的最小框架（17 张工作表 = 16 张业务表 + 1 张「说明」表） |
| [`backend/examples/contracts/auto_chain_contracts.py`](../backend/examples/contracts/auto_chain_contracts.py) | 开采 / 购销 / 运输三大合同类型（示例表格引用它） |
| [`backend/examples/contracts/mini_contracts.py`](../backend/examples/contracts/mini_contracts.py) | 最小合同类型脚本（最小示例引用它） |
| [`docs/CONTRACT_TYPE_BY_CODE.md`](CONTRACT_TYPE_BY_CODE.md) | **合同类型代码化**完整说明（具名效果、实体访问器、体检与试算） |

相关文档：[比赛 Excel 建包教程](比赛Excel建包教程.md)、[汽车产业链测试赛准备](汽车产业链测试赛准备.md)、
[合同类型代码化](CONTRACT_TYPE_BY_CODE.md)、[用代码创建比赛内容](BUILD_COMPETITION_BY_CODE.md)、
[比赛建包库完整 API 手册](BUILD_COMPETITION_API_REFERENCE.md)。
