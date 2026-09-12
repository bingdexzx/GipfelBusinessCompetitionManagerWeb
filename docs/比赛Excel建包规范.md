# 比赛 Excel 建包规范

> 目标：**用表格文件（Excel / CSV）快速建一场比赛**，并且**一张工作表 = 一类内容**，
> 表与表之间相互隔离 —— 想建什么就放哪张表，不放的表完全不参与产出。
>
> 本规范**没有新的落库路径**：表格先被翻译成比赛建包库（`CompetitionBuilder`）的调用，
> 产出与「代码建包 / 前端导入归档」完全同构的归档 JSON，再交给既有的
> `apps.preparation.archive.apply_import` 落库。因此比赛隔离、外键映射、追加/覆盖、
> 空比赛保护、dry-run 回滚这些既有语义全部原样适用。
>
> **股票系统不在本规范内**：没有股票 / 资金账户 / 股票参数三类表；不填即不产出，
> 目标比赛沿用系统默认配置。

```
表格文件(.xlsx) ──┐
                  ├─▶ sheet_spec 翻译 ─▶ CompetitionBuilder ─▶ 归档 JSON ─▶ apply_import ─▶ 比赛
CSV 目录/         ─┘
```

---

## 1. 快速开始

```powershell
cd backend
$env:PYTHONUTF8='1'

# ① 打印规范（本文档第 3 节就是它的产物，可随时重新生成）
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py --spec

# ② 生成空白模板（每张表的表头 + 一行示例 + 空行，另附「说明」表）
.\.venv\Scripts\python.exe examples/excel/make_template.py --out examples/excel/比赛建包模板.xlsx

# ③ 只读表格、看看会建出什么（不连库、不写任何东西）
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --inspect

# ④ 建比赛 + 预演导入 + 真正导入（一条命令搞定）
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --create-competition --dry-run
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --create-competition

# ⑤ 导入到已存在的比赛；或只导某个分组 / 只处理某几张表
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 189
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 189 --scope company
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的比赛.xlsx --competition 189 --sheets 公司,公司字段值

# ⑥ 也可以用「一个目录 + 每张表一个 CSV」当输入（便于进 git / diff）
.\.venv\Scripts\python.exe examples/excel/build_from_sheets.py 我的表目录 --inspect
.\.venv\Scripts\python.exe examples/excel/make_template.py --from-sheets 我的表目录 --out 我的比赛.xlsx
```

现成可用的例子：[`backend/examples/excel/汽车产业链示例.xlsx`](../backend/examples/excel/汽车产业链示例.xlsx)
（与代码建包脚本 `auto_chain_competition.py` 描述同一场汽车产业链比赛），
以及空白模板 [`比赛建包模板.xlsx`](../backend/examples/excel/比赛建包模板.xlsx)。

命令参数一览：

| 参数 | 作用 |
| --- | --- |
| `--inspect` | 只打印产出摘要与体检提醒，不导入 |
| `--out <path>` | 写出归档 JSON（可拿去前端「比赛准备 → 导入归档」上传） |
| `--create-competition` | 按「比赛」表的名称新建比赛（同名复用），再导入 |
| `--competition <id>` | 导入到该比赛 |
| `--dry-run` | 预演导入（事务回滚，一行都不落库） |
| `--mode append\|overwrite` | 追加（默认，已存在的保留）/ 覆盖（已存在的按本包更新） |
| `--scope <分组>` | 只**导入**该分组：`competition/industry/company/supply/geo/tech/market/access` |
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
   - `公司` / `产业字段` → 需要 `产业类型`（可以写 code，也可以写名称）；
   - `零件` → 需要 `原料`、`科技`；`产品` → 需要 `零件`；
   - `载具` → 需要 `燃料`、`路径类型`；`地图连线` → 需要两个 `地图节点`；
   - `合同实例` → 需要 `合同类型` 与 `公司`；`区域总览卡片` → 需要 `区域`、`公司`、`产业字段`。
   少放了会得到可执行的提示，例如：
   `[公司] 第 2 行：… 引用的 产业类型（全局）「原料开采」尚未在本构建器中登记；本工作簿里没有「产业类型」表——请把它一并放进来（它是全局口径，很小）`
3. **`--sheets` 与 `--scope` 不是一回事**：
   - `--sheets` 决定**建包时处理哪些表**（真正的裁剪，用于「这个工作簿里有些表我现在不想建」）；
   - `--scope` 决定**落库时写哪个分组**（产出仍按整份表格建，只是导入被过滤）。
   只想建「公司」时就带上 `产业类型` 表并用 `--scope company`：
   ```powershell
   python examples/excel/build_from_sheets.py 我的比赛.xlsx --sheets 产业类型,产业字段,区域,公司,公司字段值 --competition 189 --scope company
   ```
4. **可以拆成多个文件**（按关注点分工，一人一张表）：每个文件只要包含自己那张表 + 它引用的表即可；
   `--name` 能让一个没有「比赛」表的文件也参与建档。

---

## 3. 单元格语法

| 需求 | 写法 |
| --- | --- |
| 布尔 | `是/否`、`TRUE/FALSE`、`1/0`、`y/n` |
| 列表（路径类型、前置科技、账号范围…） | `公路;铁路`（分号、顿号、逗号、换行都可以当分隔符） |
| 键值（配比、地点价…） | `锂矿石*4; 铝土矿*1` 或 `白云鄂博矿区:180; 上游集运站:195` |
| 合同输入项 | `quantity=20; royalty_rate=60`，复杂值直接写 JSON：`goods={"锂矿石": 20, "铝土矿": 5}` |
| 复杂结构（计算图、字典配置…） | 以 `{` 或 `[` 开头的单元格按 **JSON** 解析 |
| 注释行 | 行首写 `#` 或 `//`，整行忽略 |
| 留空 | 该参数不传，用建包库默认值（**注意：合同实例留空不是默认值，见第 5 节**） |

金额 / 单价 / 配比这类列**建议直接写数字文本**（`600000`），程序按文本保精度；
含 JSON 的单元格里可以有逗号，切分时会自动跳过 JSON 与引号内部。

---

## 4. 数值口径与类型对照

| 表 | 列 | 说明 |
| --- | --- | --- |
| 产业字段 | `industry_type` | 可以写 `2001` 也可以写 `原料开采`（内部会归一成名称） |
| 产业字段 | `graph` | 计算字段写 `cash + bank_deposit` 即可；多字段会串成嵌套 ADD；也可直接贴 GGraph JSON |
| 产业字段 | `config` | 写 `NUMBER` 等价于 `{"valueType": "NUMBER"}`；也可直接贴 JSON |
| 公司 | 任意额外列 | **列名即 `field_key`**，作为该公司字段初始值（例：`location`、`cash`、`inventory`） |
| 公司 | `inventory` 等字典列 | 写 JSON：`{"原矿": 120, "锂矿石": 40}` |
| 合同类型 | `script` | 指向「合同类型代码化」脚本（如 `examples/contracts/auto_chain_contracts.py`），四份 JSON 由脚本产出；同一行也可改为直接贴 4 份 JSON |
| 合同类型 | `party_roles` | 紧凑写法 `seller=卖方; bank=银行|host`（`|host` 表示主办方），或直接贴 JSON |
| 合同实例 | `parties` | `miner=西岭锂业|MIN-2026-001; buyer=中原创能|BY-2026-001`（角色=公司\|合同编号） |
| 合同实例 | `inputs` | `key=value` 形式；**必须把每个输入项都填上** —— 引擎执行时不会套用默认值，缺的会按 0 参与运算 |
| 消息 | `content` | 单元格里写不出换行时用字面量 `\n`，程序会还原成换行 |

> 计算图的坑：建包库自带的 `calc_node/calc_graph` 产出的是**合同编辑器风格**的图，
> 产业计算字段求值器不认（字段会永远是空的）。本规范里的 `graph` 列按求值器认识的
> GGraph 结构生成（`output` / `value` + `data.kind` + `sourceHandle/targetHandle`），
> 详见 [`汽车产业链测试赛准备.md` 第 6 节](汽车产业链测试赛准备.md#6-测试途中查出的问题与注意点未做任何修复)。

---

## 5. 表清单与列定义

以下是 `build_from_sheets.py --spec` 的产物（与 `sheet_spec.py` 同源，改动代码后重新生成即可）。
每张表的「分组」就是 `--scope` 的取值。

<!-- SPEC:BEGIN -->
## 比赛（分组：competition）

比赛本身：名称、状态、地图背景图（整表一行）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 比赛名称（全局唯一） | 文本 | 是 |
| `status` | ACTIVE / CLOSED | 文本 |  |
| `map_background_url` | 地图背景图地址 | 文本 |  |
| `map_background_width` | 背景图宽 | 数字（可按文本填写以保精度） |  |
| `map_background_height` | 背景图高 | 数字（可按文本填写以保精度） |  |

示例行：2026 汽车产业链测试赛 | ACTIVE |  |  | 

## 财年（分组：competition）

财年：新建 / 由非 ACTIVE 改为 ACTIVE 会触发 FY_START 定时器

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `year` | 年份 | 数字（可按文本填写以保精度） | 是 |
| `status` | ACTIVE / CLOSED | 文本 |  |

示例行：2026 | ACTIVE

## 产业类型（分组：industry）

全局资源：行业口径（按 code 跨比赛复用，不要给不同行业用同一个 code）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `code` | 数字编码（全局唯一） | 数字（可按文本填写以保精度） | 是 |
| `name` | 产业名称 | 文本 | 是 |
| `description` | 说明 | 文本 |  |
| `icon` | 图标 | 文本 |  |

示例行：2001 | 原料开采 | 汽车产业链上游 | 

## 产业字段（分组：industry）

全局资源：产业下的字段（合同、图表、股票都按 field_key 绑定）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `industry_type` | 所属产业（code 或名称） | 文本 | 是 |
| `name` | 字段显示名 | 文本 | 是 |
| `field_key` | 字段键（英文，公式里要用） | 文本 | 是 |
| `field_type` | STRING/NUMBER/BOOLEAN/DICTIONARY/LIST | 文本 |  |
| `default_value` | 默认值 | 文本 |  |
| `is_calculated` | 是否计算字段 | 是/否 |  |
| `graph` | 计算图：`cash + bank_deposit` 或 GGraph JSON | JSON 文本 |  |
| `timer_enabled` | 启用财年定时器 | 是/否 |  |
| `timer_trigger` | FY_START / FY_END | 文本 |  |
| `timer_value` | 定时器写入值 | 文本 |  |
| `sort_order` | 界面排序 | 数字（可按文本填写以保精度） |  |
| `visible` | 是否展示 | 是/否 |  |
| `config` | 类型配置 JSON 或 valueType | 文本 |  |

示例行：原料开采 | 现金 | cash | NUMBER | 0 |  |  |  |  |  | 2 | 是 | 

## 区域（分组：company）

比赛内区域（区域总览、总览卡片按它聚合）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 区域名（比赛内唯一） | 文本 | 是 |
| `description` | 说明 | 文本 |  |

示例行：上游资源区 | 锂 / 铝 / 铁矿与橡胶硅砂资源带

## 公司（分组：company）

参赛公司；**额外列会被当作该公司的产业字段初始值**（列名 = field_key）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 公司名（比赛内唯一） | 文本 | 是 |
| `industry_type` | 所属产业（code 或名称） | 文本 | 是 |
| `region` | 所属区域（不存在会按名自动建） | 文本 |  |
| `status` | ACTIVE / INACTIVE | 文本 |  |
| （额外列） | 列名视作 `field_key`，作为该公司字段初始值 | 文本 | |

示例行：西岭锂业 | 原料开采 | 上游资源区 | ACTIVE | 白云鄂博矿区 | 1200000

## 公司字段值（分组：company）

单独维护公司字段值（与公司表二选一或并用，后写覆盖先写）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `company` | 公司名 | 文本 | 是 |
| `field_key` | 产业字段键 | 文本 | 是 |
| `value` | 值（NUMBER 建议写字符串以保精度） | 文本 |  |

示例行：西岭锂业 | bank_deposit | 300000

## 地图节点类型（分组：geo）

地图节点分类（矿区 / 港口 / 城市 …）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 类型名 | 文本 | 是 |
| `description` | 说明 | 文本 |  |
| `color` | 颜色，如 #b45309 | 文本 |  |

示例行：矿区 | 原矿开采地 | #b45309

## 路径类型（分组：geo）

道路类型（公路 / 铁路 / 航运）；载具按它判断可通行

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 类型名 | 文本 | 是 |
| `description` | 说明 | 文本 |  |
| `color` | 颜色 | 文本 |  |

示例行：公路 | 通用公路运输 | #94a3b8

## 地图节点（分组：geo）

地图节点（region 是文本列，不是外键）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 节点名（比赛内唯一） | 文本 | 是 |
| `node_type` | 节点类型（名称） | 文本 | 是 |
| `region` | 所属区域名（文本） | 文本 |  |
| `x` | 画布 x 坐标 | 数字（可按文本填写以保精度） |  |
| `y` | 画布 y 坐标 | 数字（可按文本填写以保精度） |  |

示例行：白云鄂博矿区 | 矿区 | 上游资源区 | 140 | 120

## 地图连线（分组：geo）

节点之间的连线；同一对「起点+终点」只能有一条（反向算另一条）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `from_node` | 起点节点 | 文本 | 是 |
| `to_node` | 终点节点 | 文本 | 是 |
| `distance` | 距离（公里） | 数字（可按文本填写以保精度） | 是 |
| `path_type` | 路径类型（名称） | 文本 | 是 |

示例行：白云鄂博矿区 | 上游集运站 | 120 | 公路

## 燃料（分组：supply）

燃料（载具必须绑定燃料，外键 PROTECT）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 燃料名 | 文本 | 是 |
| `price_per_liter` | 每升单价 | 数字（可按文本填写以保精度） |  |

示例行：柴油 | 7.6

## 原料（分组：supply）

原料（地点价按地图节点名写；运输与运费计算都依赖它）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 原料名 | 文本 | 是 |
| `origin` | 产地（通常写地图节点名） | 文本 |  |
| `carbon_emission_coefficient` | 碳排系数 | 数字（可按文本填写以保精度） |  |
| `type` | NORMAL / SPECIAL | 文本 |  |
| `node_prices` | 地点价：`白云鄂博矿区:180; 上游集运站:195` | 键值（名称:数值，分号分隔） |  |

示例行：锂矿石 | 白云鄂博矿区 | 0.52 | NORMAL | 白云鄂博矿区:180; 上游集运站:195

## 科技（分组：supply）

科技节点（零件 / 产品按它设前置）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 科技名 | 文本 | 是 |
| `tier` | 层级 | 数字（可按文本填写以保精度） |  |
| `research_cost` | 研发费用 | 数字（可按文本填写以保精度） |  |
| `description` | 说明 | 文本 |  |
| `prerequisites` | 前置科技：`高炉冶炼;转炉炼钢` | 列表（分号分隔） |  |

示例行：电池成组技术 | 1 | 80000 | 解锁动力电池包 | 

## 生产线（分组：supply）

生产线（产能与用工人数）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 生产线名 | 文本 | 是 |
| `price` | 单价 | 数字（可按文本填写以保精度） |  |
| `labor_count` | 用工人数 | 数字（可按文本填写以保精度） |  |
| `max_per_year` | 年产能 | 数字（可按文本填写以保精度） |  |

示例行：电芯产线 | 2400000 | 120 | 6000

## 基建（分组：supply）

基建及其 6 项加成（合同可按清单聚合这些属性）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 基建名 | 文本 | 是 |
| `footprint` | 占地面积 | 数字（可按文本填写以保精度） |  |
| `price` | 单价 | 数字（可按文本填写以保精度） |  |
| `activation_price` | 启用费用 | 数字（可按文本填写以保精度） |  |
| `employment_rate_bonus` | 就业率加成 | 数字（可按文本填写以保精度） |  |
| `population_bonus` | 人口加成 | 数字（可按文本填写以保精度） |  |
| `high_quality_population_bonus` | 高素质人口加成 | 数字（可按文本填写以保精度） |  |
| `happiness_index_bonus` | 幸福度加成 | 数字（可按文本填写以保精度） |  |
| `per_capita_income_bonus` | 人均收益加成 | 数字（可按文本填写以保精度） |  |
| `carbon_reduction_bonus` | 减碳加成 | 数字（可按文本填写以保精度） |  |

示例行：光伏电站 | 160 | 1200000 | 50000 | 0.02 |  |  |  |  | 0.12

## 仓库（分组：supply）

仓库（MATERIAL / PART / PRODUCT / FUEL 四种建议都覆盖）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 仓库名 | 文本 | 是 |
| `type` | MATERIAL/PART/PRODUCT/FUEL | 文本 | 是 |
| `capacity` | 容量 | 数字（可按文本填写以保精度） |  |
| `price` | 单价 | 数字（可按文本填写以保精度） |  |

示例行：原料仓 | MATERIAL | 30000 | 400000

## 零件（分组：supply）

零件：原料配比 + 科技前置（配比只能引用原料）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 零件名 | 文本 | 是 |
| `materials` | 原料配比：`锂矿石*4; 铝土矿*1` | 键值（名称:数值，分号分隔） |  |
| `tech` | 所需科技：`电池成组技术` | 列表（分号分隔） |  |

示例行：动力电池包 | 锂矿石*4; 铝土矿*1 | 电池成组技术

## 产品（分组：supply）

产品：零件配比 + 科技前置（配比只能引用零件）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 产品名 | 文本 | 是 |
| `parts` | 零件配比：`动力电池包*1; 驱动电机*1` | 键值（名称:数值，分号分隔） |  |
| `tech` | 所需科技 | 列表（分号分隔） |  |

示例行：纯电轿车 | 动力电池包*1; 驱动电机*1 | 整车平台化

## 载具（分组：supply）

载具：绑定燃料 + 可通行路径类型（缺路径类型会导致运输校验失败）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `name` | 载具名 | 文本 | 是 |
| `fuel` | 燃料（必填） | 文本 | 是 |
| `path_types` | 可通行路径类型：`公路;铁路` | 列表（分号分隔） |  |
| `fuel_consumption_per_km` | 每公里油耗 | 数字（可按文本填写以保精度） |  |
| `max_cargo` | 载货量 | 数字（可按文本填写以保精度） |  |
| `price` | 单价 | 数字（可按文本填写以保精度） |  |
| `carbon_emission` | 碳排系数 | 数字（可按文本填写以保精度） |  |

示例行：重型卡车 | 柴油 | 公路 | 0.35 | 30 | 260000 | 0.9

## 消费者需求（分组：tech）

区域消费者需求（导入按「区域+产品+数量」去重，改数量 = 新增一条）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `region` | 区域名（文本） | 文本 | 是 |
| `product` | 产品名（需已登记） | 文本 | 是 |
| `quantity` | 需求量 | 数字（可按文本填写以保精度） | 是 |
| `note` | 备注 | 文本 |  |

示例行：东部车都 | 纯电轿车 | 1200 | 城市通勤主力车型

## 区域总览卡片（分组：market）

区域总览卡片（industryFieldId 由建包库自动回填，见文档两遍导入）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `region` | 区域名 | 文本 | 是 |
| `company` | 公司名 | 文本 | 是 |
| `field_key` | 要展示的产业字段键 | 文本 | 是 |
| `display_name` | 卡片标题 | 文本 |  |
| `zone` | 分区标记 | 文本 |  |
| `card_id` | 卡片 id（缺省自动生成） | 文本 |  |

示例行：上游资源区 | 西岭锂业 | cash | 西岭锂业现金 |  | 

## 合同类型（分组：market）

全局资源：合同模板。四份 JSON 可写 JSON，也可用 `script` 列指向合同类型代码化脚本

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `key` | 合同类型 key（全局唯一） | 文本 | 是 |
| `name` | 合同类型名 | 文本 | 是 |
| `description` | 说明 | 文本 |  |
| `script` | 合同类型脚本路径（如 examples/contracts/auto_chain_contracts.py） | 文本 |  |
| `party_roles` | 参与方：`seller=卖方; bank=银行|host` 或 JSON | JSON 文本 |  |
| `input_schema` | 输入项 JSON | JSON 文本 |  |
| `effects` | 效果 JSON | JSON 文本 |  |
| `conditions` | 前置检查 JSON | JSON 文本 |  |
| `enabled` | 是否启用 | 是/否 |  |

示例行：auto-mining | 开采合同 | 开采企业缴纳权利金并入库原矿 | examples/contracts/auto_chain_contracts.py |  |  |  |  | 是

## 合同实例（分组：market）

比赛内的预置合同（保持 DRAFT 不落账）。名称缺省取合同类型名，故每种类型只预置一份

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `contract_type` | 合同类型 key | 文本 | 是 |
| `name` | 合同名（缺省 = 合同类型名） | 文本 |  |
| `parties` | 参与方：`miner=西岭锂业|MIN-001; buyer=中原创能|BY-001` | 键值（名称:数值，分号分隔） |  |
| `inputs` | 输入项：`quantity=20; goods={"锂矿石": 20}` | 键值（key=value，分号分隔） |  |
| `status` | DRAFT / PENDING_EXEC / EXECUTED / TERMINATED | 文本 |  |

示例行：auto-mining | 开采合同 | miner=西岭锂业|MIN-2026-001 | ore_type=锂矿石; quantity=20; royalty_rate=60 | DRAFT

## 消息（分组：market）

比赛内消息（导入不做判重：重复导入会多建，注意去重）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `title` | 标题 | 文本 | 是 |
| `content` | 正文（可用 \n 换行） | 文本 |  |
| `to_all` | 是否发给全体 | 是/否 |  |
| `to_users` | 指定收件人：`player_a;player_b` | 列表（分号分隔） |  |
| `sender` | 发布者用户名（缺省用导入操作者） | 文本 |  |

示例行：开局公告 | 欢迎参赛，请先核对本公司初始字段。 | 是 |  | 

## 账号（分组：access）

参赛账号与四套公司范围（范围为空 = 登录后什么都看不到）

| 列 | 说明 | 类型 | 必填 |
| --- | --- | --- | :---: |
| `username` | 用户名（全局唯一） | 文本 | 是 |
| `role` | SUPER_ADMIN / COMPETITION_ADMIN / PLAYER | 文本 |  |
| `display_name` | 显示名 | 文本 |  |
| `company_scopes` | 公司管理范围：`西岭锂业;中原创能` | 列表（分号分隔） |  |
| `view_company_scopes` | 查看范围 | 列表（分号分隔） |  |
| `contract_view_company_scopes` | 合同查看范围 | 列表（分号分隔） |  |
| `stock_company_scopes` | 股票范围（本规范不覆盖股票，可留空） | 列表（分号分隔） |  |
| `permissions` | 细粒度权限键：`contract:manage;contract:audit` | 列表（分号分隔） |  |
| `is_active` | 是否启用 | 是/否 |  |

示例行：player_a | PLAYER | 玩家A | 西岭锂业;中原创能 | 西岭锂业;中原创能 | 西岭锂业;中原创能 |  |  | 是

<!-- SPEC:END -->

---

## 6. 与代码建包的关系

| | 代码建包 | 表格建包 |
| --- | --- | --- |
| 入口 | `manage.py build_competition 脚本.py` | `examples/excel/build_from_sheets.py 表格.xlsx` |
| 适合 | 复杂逻辑、循环生成、纳入 CI、版本管理 | 策划/运营随时改数据，不碰代码 |
| 合同类型 | `examples/contracts/*.py`（4 份 JSON 由代码产出） | 表格里写 `script` 列引用同一个脚本（同源，不重复维护） |
| 落库 | `archive.apply_import` | 同一个 `archive.apply_import` |

两者可以混用：表格建包负责「数据」，代码建包负责「需要编程的部分」，
它们产出的归档 JSON 结构完全一致，可以互相追加/覆盖。

### 实测等价性（`汽车产业链示例.xlsx` vs `auto_chain_competition.py`）

同一天在本地库上对拍的结果（按内容对齐、忽略行顺序）：

- **26 / 32 类资源逐行完全一致**（公司、区域、地图、原料、零件、产品、载具、合同类型/实例、账号…）；
- 6 类存在**有意的、无害的**差异：
  - `companyFieldValues` 90 → 48 行：表格里没写的字段沿用产业字段默认值（`ledger`、`carbon`、`contract_amount`…），语义等价；
  - `industryFields`：额外字段的 `sortOrder` 与计算图节点 id/坐标不同（结构等价）；
  - `pathTypes`：示例表格多写了 `description`；
  - `users`：公司范围数组的顺序不同（集合相同）；
  - `infrastructures` / `materials`：早期把金额写成了 float，现已改为按文本保精度（与代码一致）。

功能级验证（对表格建出来的比赛跑真实引擎）：

```
合同类型试算：auto-mining 9/9、auto-purchase-sale 9/9、auto-transport 9/9 家公司通过
合同冒烟：开采 20 吨 → 1,360 元 + 配额 20 + 原矿 20；购销 20 吨锂矿石 @180 → 3,600 元；
         运输 540 km → 运费 6,858 + 碳税 48.6（全部事务回滚，不落库）
股票系统：stocks=0 / 资金账户=0
```

---

## 7. 注意点（都是既有引擎语义，不是本工具的缺陷）

1. **总览卡片要导两遍**：`industryFieldId` 是数据库主键，产业字段是全局资源，
   首次导入时卡片拿不到 id（只影响取值，不报错）。第二次带 `--competition` 跑时会自动回填
   （`.xlsx` → 归档 → 导入，建议配 `--mode overwrite --allow-non-empty`）。
2. **比赛内消息不去重**：重复导入会多建一整套消息，注意清理（`auto_chain_setup.py --finish` 可去重）。
3. **合同实例只新增、不更新**：已存在（同比赛 + 同合同类型 + 同名）的实例会被跳过；
   要改预置实例的参与方/输入项，得先在「合同管理」里删掉它再导入。
4. **账号是全局的**：同一个用户名导入到第二场比赛时，只会把公司范围**并进去**，
   不会改归属比赛 —— 因此跨比赛复用的账号会同时拥有两场比赛的公司范围（本工具会照实合并）。
5. **文件格式**：`.xlsx` 由本仓库的极简读写器生成（纯标准库，未引入 openpyxl/pandas），
   Excel / WPS / LibreOffice 均可打开与另存；也可以用「目录 + CSV」完全绕开 Excel。
6. **本规范不覆盖**：股票、资金账户、股票参数（按要求不动股票系统），
   以及 `pbFieldId` / `bindFieldId` 这类指向具体主键的绑定列。

---

## 8. 文件

| 文件 | 作用 |
| --- | --- |
| [`backend/examples/excel/sheet_spec.py`](../backend/examples/excel/sheet_spec.py) | **规范本体**：表清单、列定义、单元格语法、每张表的建包映射 |
| [`backend/examples/excel/build_from_sheets.py`](../backend/examples/excel/build_from_sheets.py) | 读表格 → 建包 → 导入（也支持 `--out` 只产出归档 JSON） |
| [`backend/examples/excel/make_template.py`](../backend/examples/excel/make_template.py) | 生成空白模板；xlsx ↔ CSV 目录互转 |
| [`backend/examples/excel/make_sample_auto_chain.py`](../backend/examples/excel/make_sample_auto_chain.py) | 生成汽车产业链示例表格（与代码建包脚本同内容） |
| [`backend/examples/excel/xlsx_io.py`](../backend/examples/excel/xlsx_io.py) | 极简 xlsx / CSV 读写（纯标准库） |
| [`backend/examples/excel/比赛建包模板.xlsx`](../backend/examples/excel/比赛建包模板.xlsx) | 空白模板（含「说明」表） |
| [`backend/examples/excel/汽车产业链示例.xlsx`](../backend/examples/excel/汽车产业链示例.xlsx) | 可直接导入的汽车产业链示例 |

相关文档：[汽车产业链测试赛准备](汽车产业链测试赛准备.md)、
[用代码创建比赛内容](BUILD_COMPETITION_BY_CODE.md)、
[比赛建包库完整 API 手册](BUILD_COMPETITION_API_REFERENCE.md)。
