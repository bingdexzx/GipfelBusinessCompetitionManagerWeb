# 合同通过监听程序（独立 · 静默 · 自动）

不改动网页端与后端任何代码：本程序是**独立运行的本地监听器**，对服务器只表现为
一个只读账号（登录 + 查询接口），文件全部落在启用者自己的电脑上。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `contract_watcher.py` | 主程序：轮询监听、类型目录同步、按类型分发 |
| `handlers.py` | **处理函数文件**（自动维护：新类型自动追加默认函数、类型改名自动改名） |
| `readable.py` | **翻译模块**：合同 payload → 可理解的中文记录；支持按类型注册自定义翻译器 |
| `DATA_GUIDE.md` | **合同数据指南**：处理函数里可获得哪些数据、如何取值 |
| `TEST_FLOW.md` | **端到端测试流程**：文字版分步操作与验收标准 |
| `bookkeeping_example/shang.py` | **Excel 记账联动示例**：用户记账处理函数（xledit 类，三个 add 模板；默认静默运行、含平衡校验 `check()`） |
| `bookkeeping_example/target.xlsx` | 上述脚本配套的 12 表记账账套模板 |
| `records/` | 默认存档目录：每个通过合同产出 **2 个文件** —— `contract_<id>_<时间>.json`（原始全量）+ `contract_<id>_<时间>_readable.json`（翻译可读版） |
| `watcher.log` | 运行日志（平时静默，全部记录在此） |
| `data/state.json` | 进度与类型目录状态（重启不重复处理） |

## 快速开始

```powershell
# 前提：账号具备 contract:view（自动生成/改名另需 contractType:view）
python contract_watcher.py --server http://127.0.0.1:8000 `
    --username admin --password "你的密码" [--competition 1]

# 前台观察一次运行效果（明细打到控制台）：
python contract_watcher.py --server ... --username ... --password ... --verbose

# 存量合同也要补处理（仅首次）：
python contract_watcher.py --server ... --username ... --password ... --backfill
```

- 默认每 3 秒检查一次（`--interval 1` 可更实时）；
- 首次运行建立进度基线：之后**新通过**的合同才会被处理；
- 单实例：重复启动会被端口锁拒绝（`--port` 可换）。

## 自动化行为（无需人工干预）

1. **合同通过 → 按类型执行**：轮询发现 `EXECUTED` 且 `executedAt` 更新的合同 →
   拉详情 → 按 `contractType.key` 找 `handle_<key>_passed(contract, ctx)` 执行；
   找不到则执行默认存档（全量 JSON + 可读翻译版 → `records/<key>/`）。
2. **新类型 → 实时生成默认函数**：轮询合同类型目录，出现新 key 即在
   `handlers.py` 末尾自动追加默认函数并热加载。
3. **类型改名 → 自动改名**：同一 typeId 的 key 变化时，自动更新该函数的
   「标注行 + 函数名」为新 key（函数体原样保留），并热加载生效。
4. **修改即生效**：你编辑 `handlers.py` 保存后，下一轮自动热加载，无需重启。
5. **健壮性**：登录态自动续期；断网/接口错误/处理异常只写日志并继续下一轮；
   进度落盘，重启不重复。

## 定制某个类型的处理

打开 `handlers.py`，找到对应自动生成块（标注 `ContractType.key = <你的key>`），
删除函数体内 `# [auto-default]` 一行并写自己的逻辑，例如按需拆分文件、发送到
本机其它目录等：

```python
def handle_material_procurement_passed(contract: dict, ctx: dict) -> None:
    # 例子：只保存参与方名单（去掉默认存档逻辑）
    import json, time
    from pathlib import Path
    sub = Path(ctx["out_dir"]) / "parties"
    sub.mkdir(parents=True, exist_ok=True)
    f = sub / f"parties_{contract['id']}.json"
    f.write_text(json.dumps(contract.get("parties", []), ensure_ascii=False, indent=2), encoding="utf-8")
```

## 翻译模块（readable.py · 默认自动产出可读版）

默认存档时，每个合同自动产出两个文件：
`contract_<id>_<时间>.json`（原始全量）与 `contract_<id>_<时间>_readable.json`
（翻译后的中文可读记录：参与方/填写内容/前置检查/落账明细，公司名、字段中文名、
操作中文（增加/扣减/设定）、金额千分位均已转换）。翻译失败不影响原始存档。

**用户接口**（处理函数里直接用）：

```python
from readable import translate_contract, build_readable, register_translator, pretty_value

# 1) 翻译任意合同
rec = translate_contract(contract)                 # dict，可直接 json.dumps 落盘

# 2) 为某合同类型注册专属翻译器（在默认结构上增删字段）
@register_translator("material-procurement")
def translate_procure(payload: dict) -> dict:
    rec = build_readable(payload)                  # 先取默认翻译
    rec["采购注意"] = "需要人工复核单价上限"            # 按类型补充内容
    return rec

# 3) 全局标签表可直接覆盖（影响所有类型）
import readable
readable.OP_LABELS["SET"] = "设定为"               # 修改操作词
```

在你的处理函数里：不调用 `ctx["default_archive"]` 的自定义处理，
可自行用 `translate_contract(contract)` 生成可读记录后按需落盘。

## Excel 记账联动（bookkeeping_example/ · 内容理解）

用户提供的记账处理函数 `shang.py` + 账套 `target.xlsx`，用于把合同通过后的业务
变动**记入 Excel 账本**。已复制到 `bookkeeping_example/` 供参考与测试
（当前为 **2026-09-10 新版**，13,392 字节；旧版 12,612 字节）。

### 依赖与性质

- `shang.py` 使用 **xlwings** 驱动本机 **Excel 应用**（非标准库、非网页端）：需
  Windows + 已安装 Excel，首次使用 `pip install xlwings`；会真实打开并保存
  `target.xlsx`，请勿同时被多人/多实例打开（测试建议用副本）。
- **默认静默运行**：`xledit(file, debug=False)` 不显示 Excel 窗口
  （`visible=False` + `ScreenUpdating=False`），适合监听程序后台调用；
  需要肉眼观察时传 `debug=True` 才显示 Excel 界面。
- 内置 **会计平衡校验**：`xledit.check()` 读取资产负债表 `sheets[7]` 的 `H80`
  单元格（资产 − 负债 − 所有者权益）：为 0 打印 `right`；>0 打印
  「资产>负债+所有者权益」；<0 打印「资产<负债+所有者权益」
  （已修正原先两种失衡使用同一文案的问题）。
- `target.xlsx` 是一个 **12 张表的记账账套**：银行流水账、原材料(加工用)、
  零件（加工用）、商品（各实体用）、明细账汇总-资产类科目、明细账汇总-负债类
  科目、明细账汇总-损益类科目、资产负债表、利润表、计算、现金流量表、
  常用财务分析表。

### `xledit` 类与三个 add 模板函数（语义对照）

| 函数 | 写哪张表 | 作用 | 典型对应合同事件 |
| --- | --- | --- | --- |
| `add_book_entries(add, minus, number, about)` | `sheets[0]` 银行流水账 | 追加一行银行日记账：日期自动、序号自增、`add` 写入「存款增加」、`minus` 写入「存款减少」、自动余额公式，摘要 = `number + " " + about`；余额单元格地址存 `entries_to_assets_money` 供资产表联动 | 合同款项收付（货款/定金/还款） |
| `add_book_item(thing: things, name, number, price, add, minus)` | `sheets[1-3]` 原材料/零件/商品 | 按存货名定位货品行（新版按 `things.RAWMETRIAL/COMPENT/PORDUCT` 枚举分支）：`add=True` → 采购入库（数量+单价），`minus=True` → 耗用出库（数量，加权单价由公式算）；新物料自动建移动平均结转报告表头，插入行用 `autofill` 复制格式与公式；净额自动同步到资产/损益汇总科目 | 原料/零件/商品类合同的收发存 |
| `add_book_assets(type: BOOOKTYPE, name, add, minus)` | `sheets[4]` 资产 / `sheets[5]` 负债 / `sheets[6]` 损益科目 | 按科目中文名定位行写入发生额、自动向下扩行并维护「银行存款」余额联动公式；**新版负债类与损益类分支均自动借贷互换**（按账套方向约定） | 合同对资产负债/损益类科目的影响 |

配套枚举：`things`（原材料/零件/产品）、`ASSET/LIABILITIES/EQUITY`（科目中文名
常量，如 `银行存款/应收账款/应付账款/主营业务成本-存货成本/…`）、`BOOOKTYPE`。

### 本版（2026-09-10）相对旧版的实际改动

| # | 改动 | 影响 |
| --- | --- | --- |
| 1 | `__init__` 增加 `debug=False`，默认**无界面**运行 | 可在监听程序后台静默记账 |
| 2 | 新增 `check()` 资产负债表平衡校验 | 记账后可自检是否平账 |
| 3 | `add_book_item` 参数 `unitprice` → `price`；分支判断改 `things` 枚举 | 调用方关键字传参需同步改名（位置传参不受影响） |
| 4 | 货品行定位 `i+3` → `i+4`、写数据行偏移 +1、插入行改 `autofill`、移除重复条件 | 修复旧版可能定位错行/条件不生效的问题 |
| 5 | `add_book_assets` 损益类分支新增借/贷互换 | 损益科目方向与资产相反，由脚本自动处理 |

### 与监听程序的结合方式（在你的 handlers.py 里）

把 `bookkeeping_example` 目录加入导入路径后，在对应合同类型的处理函数中调用：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "bookkeeping_example"))

from shang import xledit, things, ASSET, BOOOKTYPE, LIABILITIES, EQUITY

def handle_material_procurement_passed(contract: dict, ctx: dict) -> None:
    book = xledit(r"D:\账套\target.xlsx")          # 用副本测试，勿动原件
    try:
        amount = contract["inputs"].get("amount")
        number = contract["parties"][0].get("contractNumber") or str(contract["id"])
        about = contract["name"]                     # 摘要：可组合参与方/类型名
        book.add_book_entries(add=amount, minus=0, number=number, about=about)
        # book.add_book_item(things.RAWMETRIAL, "原料A", 100, Decimal("50"), True, False)
        # book.add_book_assets(BOOOKTYPE.ASSETS, ASSET.BANK_DEPOSITS, add=amount, minus=0)
        book.save()
    finally:
        try:
            book.xlapp.quit()
        except Exception:
            pass
```

> 参数取值按你的账套口径校验后再启用（金额单位、科目映射、借贷方向）。
> Excel 自动化建议只在单机、非并发场景使用；处理函数已受监听程序异常隔离保护，
> 记账失败只写日志，不影响合同执行与网页端。

## 开机自启（可选）

- Windows：任务计划程序 → 创建任务 → 触发器「登录时」→ 操作填上面的 python 命令；
- Linux：`crontab -e` 加 `@reboot ...`，或用 systemd user service；
- 无需界面常驻：程序没有窗口输出（去 `--verbose` 即全静默，仅写 `watcher.log`）。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 启动报「登录失败」 | 账号密码错，或 admin 首次登录需先改密 |
| 日志出现「获取合同类型目录失败」 | 账号缺 contractType:view：自动生成/改名不可用，合同通过处理不受影响 |
| 改了 handlers.py 没生效 | 等一个轮询周期即热加载；语法错误会在 watcher.log 记录并回退默认行为 |
| 换电脑/重装 | 整个文件夹复制过去即可（进度文件一并带走，不会重复处理） |
