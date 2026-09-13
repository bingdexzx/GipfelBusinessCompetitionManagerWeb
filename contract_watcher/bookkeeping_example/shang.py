import datetime as dt
import xlwings as xw
from datetime import datetime, timezone as _timezone
from pathlib import Path
from decimal import Decimal,getcontext
from enum import Enum
import re as _re

class things(Enum):
    RAWMETRIAL = 1
    COMPENT = 2
    PORDUCT = 3
class ASSET(Enum):
    BANK_DEPOSITS = "银行存款"
    LAND_USE_RIGHTS = "土地使用权"
    RAW_MATERIALS = "原材料"
    SEMI_FINISHED_PARTS = "半成品（零件）"
    FIXED_ASSETS = "固定资产"
    ACCOUNTS_RECEIVABLE = "应收账款"
    ACCOUNTS_PAYABLE = "应付账款"
    INVENTORY_GOODS = "库存商品"
    INDUSTRIAL_PROPERTY = "工业产权及专有技术"
    ACCUMULATED_DEPRECIATION = "累计折旧"
    TRADING_FINANCIAL_ASSETS = "交易性金融资产"
class LIABILITIES(Enum):
    ADVANCE_RECEIVABLES = "预收账款"
    SHORT_TERM_LOANS = "短期借款"
    ACCOUNTS_PAYABLE = "应付账款"
    EMPLOYEE_BENEFITS_PAYABLE = "应付职工薪酬"
class EQUITY(Enum):
    PRODUCT_SALES_REVENUE = "产品（商品）销售收入"
    INVESTMENT_INCOME = "投资收益"
    OTHER_OPERATING_INCOME = "其他业务收入"
    MAIN_OPERATING_COST_INVENTORY = "主营业务成本-存货成本"
    MAIN_OPERATING_COST_LABOR = "主营业务成本-人工"
    MAIN_OPERATING_TAXES = "主营业务税金及附加"
    SELLING_EXPENSES = "销售费用"
    ADMINISTRATIVE_EXPENSES = "管理费用"
    FINANCIAL_EXPENSES_INTEREST = "财务费用（利息费用）"
    PAID_IN_CAPITAL = "实收资本"
    CAPITAL_RESERVE = "资本公积"
    UNDISTRIBUTED_PROFIT = "未分配利润"
    NON_OPERATING_INCOME = "营业外收入"
class BOOOKTYPE(Enum):
    ASSETS = 1
    LIABILITIES = 2
    EQUITY = 3


# 审计 CW-14：金额输入的严格形态（拒绝全角数字、下划线、千分位、nan/inf 等意外写法）。
# Decimal(str) 会把这些"看起来像数字"的串悄悄接受（`'１２３'`→123、`'1_000'`→1000），
# 记账金额不能靠这种宽容解析。
_AMOUNT_RE = _re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


def amount_to_float(value, field: str = "金额") -> float:
    """把合同里的金额输入项转成写入 Excel 的 float；形态非法即抛中文 ValueError。

    审计 CW-14：改前是裸 `float(add)` / `float(minus)`：
      - `None`（`DATA_GUIDE.md`：「未填写的输入项不会出现」）⇒ `None != 0` 为真 ⇒ **TypeError**；
      - `""` / `"1,000"` ⇒ **ValueError**；
      两者都被 `contract_watcher.py` 的 `dispatch` 吞掉 ⇒ 合同被标记「已处理」但**一条分录都没写**
      （静默漏账且永不重试）。而 `float` 对超 15 位有效数字还会**静默丢低位**：
      `12345678901234567890` → `1.23456789012346E+19`。

    现在的规则（先 Decimal 保精度，再判可无损落入 Excel 的 double）：
      - `None` / 空串 / 纯空白 → 拒绝（并提示「未填写」）；
      - 形态不匹配 `_AMOUNT_RE`（千分位、全角数字、`1_000`、`nan`、`inf` 等）→ 拒绝；
      - 超出 IEEE-754 double 精确表示范围 → 拒绝（宁可报错让上层重试，也不静默改金额）；
      - 其余（含 0 与负数）→ 返回 float。负数金额是合法业务值（借贷方向由列决定），不拦。
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field}未填写或取值非法（{value!r}）：请检查合同输入项，确认后再处理")
    text = str(value).strip() if isinstance(value, str) else str(value)
    if not text:
        raise ValueError(f"{field}为空字符串：请检查合同输入项，确认后再处理")
    if not _AMOUNT_RE.fullmatch(text):
        raise ValueError(f"{field}不是合法数字（收到 {value!r}）：不接受千分位/全角数字等写法")
    dec = Decimal(text)
    as_float = float(dec)
    # 反向校验：float → Decimal(repr) 必须还原成同一个值，否则说明超过 double 精度、低位已被丢弃
    if Decimal(repr(as_float)) != dec:
        raise ValueError(
            f"{field} {value!r} 超出 Excel 数值可精确表示的范围（double 15~17 位有效数字）："
            "请拆分或按文本记录，避免静默丢失低位"
        )
    return as_float


# ==================== 货品表「槽位」判定（审计 CW-16） ====================
#
# 改前有两套互相矛盾的判定：
#   - 定位循环用「绿底 + value is None」找空槽；
#   - 写数据循环却用 `value == 0` 判空槽 —— 而模板（target.xlsx 的「原材料(加工用)」等表）
#     把整块可用槽位的数量列**预置成 0**（D/G = 0），数据行是由 `A{i+1}` 插行复制出来的，
#     一旦某行被插成空单元格（None），`None == 0` 为假 ⇒ 该槽位被跳过；走到表尾就直接
#     `break` ⇒ **数量既不写入也不报错**（静默漏记）。
#   - 定位循环走到底时 `i -= 1` 后把**最后一行**覆写成报表标题并 A:L 合并（原数据不可恢复）。
# 现在把判定收敛成一个明确的函数，并在「没有空槽」时抛出可重试的业务异常。

def is_blank_cell(value) -> bool:
    """「可写入的空槽位」判定：None / 空串 / 纯空白 / 数值 0 都算空。

    审计 CW-16：改前这里是 `value == 0`，与「空单元格是 None」的现实矛盾。
    `0` 必须算空 —— 模板把每个可用槽位的数量列预置成 0，那是「还没用」而不是「已记账」。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return value == 0


def find_free_row(sht, rows, quantity_cols=(3, 6)) -> int | None:
    """在 `rows`（0 基行号序列）里找第一个数量列全空的槽位行；找不到返回 None。

    审计 CW-16：改前是 `while (i != sht.used_range.last_cell.row)` 逐行走，越界或走到底
    都没有明确语义（最终落到「覆写最后一行」）。现在改为对显式行区间迭代，找不到就交给调用方报错。
    """
    last_row = sht.used_range.last_cell.row
    for i in rows:
        # 写数据还会用到 i+1（采购金额列）与 i+2（插入锚点），越出表尾的槽位一律不可用
        if i + 2 > last_row:
            continue
        if all(is_blank_cell(sht[i, c].value) for c in quantity_cols):
            return i
    return None


def parse_business_date(value, tz=None):
    """把合同的 `executedAt` 转成**当地业务日期**（`datetime.date`）。

    审计 CW-17：改前账期一律取 `dt.date.today()`（运行当天），于是 `--backfill` 补存量、
    故障恢复后补记、监听程序停机几天后重启 —— 这些「延迟处理」都会把昨天甚至上季度通过的
    合同记成**今天**发生的业务 ⇒ 跨天/跨月/跨财年错期，与合同 `executedAt` 无法对账
    （`add_book_entries` 的签名里根本没有日期参数，是设计缺口）。

    只接受「能被理解为合同执行时间」的输入：`datetime` / `date` / ISO 8601 字符串
    （后端返回 UTC，如 `2026-09-10T15:20:46.731818Z`，会换算到本地时区再取日期）。
    无法解析时返回 None，由调用方决定是否回退到运行当天。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, dt.date):
        return value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_timezone.utc)
    return moment.astimezone(tz).date()


def format_business_date(value, tz=None) -> str:
    """把合同 `executedAt` 格式化成账期字符串 `YYYY/MM/DD`（解析失败回退运行当天）。"""
    day = parse_business_date(value, tz)
    if day is None:
        return dt.date.today().strftime("%Y/%m/%d")
    return day.strftime("%Y/%m/%d")


# 审计 CW-08：这里原本有 `getcontext().prec = 2`，把**进程级** Decimal 精度改成 2 位有效数字。
# import 本模块（README 教程就是这么教的）即生效，随后任何 Decimal 金额运算都会变成量级错误：
#   Decimal('1234.56') + Decimal('0.44')  → 1.2E+3（1200）
#   Decimal('12345.67') * 3               → 3.7E+4（37000，正确 37037.01）
#   Decimal('999999.99') / 3              → 3.3E+5
# 记账属于金额场景，精度必须保持默认（28 位有效数字）；确需限制精度请用
# `with localcontext() as ctx: ctx.prec = ...` 只作用于局部，不要改全局上下文。

class xledit:
    xlapp:xw.App = None
    wb:xw.Book = None
    entries_to_assets_money = ''
    # 审计 CW-22：本进程启动过的 Excel PID（供 run_branch_tests 只回收「自己启动的」进程，
    # 而不是把用例期间新出现的所有 EXCEL.EXE 一律 taskkill —— 那会误杀用户自己的 Excel）。
    owned_pids: set = set()
    def __init__(self,file:str,debug:bool = False):
        p = Path(file)
        if(p.is_file() != True):
            raise
        # 审计 CW-09：改前 App() 启动后若 books.open() 抛错（文件被人工 Excel 打开/只读/损坏/
        # 网络盘瞬时不可用），异常直接冒泡且**没有 quit()** —— 每次失败泄漏一个隐藏 EXCEL.EXE，
        # 它继续占用该 xlsx 使后续尝试更容易失败，而 watcher 又把异常吞掉 ⇒ 持续性静默漏账。
        try:
            if debug == False:
                self.xlapp = xw.App(visible=False,add_book=False)
                self.wb = self.xlapp.books.open(file)
                self.xlapp.api.ScreenUpdating = False
                self.xlapp.api.DisplayAlerts = False
            if debug == True:
                self.xlapp = xw.App(visible=True,add_book=False)
                self.wb = self.xlapp.books.open(file)
                self.xlapp.api.ScreenUpdating = True
                self.xlapp.api.DisplayAlerts = False
            self._remember_pid()
        except Exception:
            self._quit_quietly()
            raise

    def _remember_pid(self):
        """登记本次启动的 Excel PID（审计 CW-22：供脚本只回收自己启动的进程）。"""
        pid = getattr(getattr(self.xlapp, "impl", None), "pid", None)
        if pid is None:
            pid = getattr(self.xlapp, "pid", None)
        if isinstance(pid, int):
            type(self).owned_pids.add(pid)

    def _quit_quietly(self):
        """异常路径下回收 Excel 进程（失败不影响原始异常）。"""
        app = getattr(self, "xlapp", None)
        if app is None:
            return
        try:
            app.quit()
        except Exception:  # noqa: BLE001 - 回收失败也要保留原始异常
            pass
        self.xlapp = None
        self.wb = None
    def check(self):
        sht = self.wb.sheets[7]
        if sht.range('H80').value == 0:
            print("right")
        if sht.range('H80').value > 0:
            print("资产>负债+所有者权益")
        if sht.range('H80').value < 0:
            print("资产<负债+所有者权益")
    def save(self):
        self.wb.save()
        self.wb.close()
        self.xlapp.quit()
    def add_book_entries(self,add:Decimal,minus:Decimal,number:str,about:str,business_date=None):
        """记一笔分录；`business_date` 传合同 `executedAt`，缺省用运行当天（旧行为）。"""
        sht = self.wb.sheets[0]
        # 审计 CW-14：先做金额校验，非法输入在**写任何单元格之前**就抛出（避免留下半行脏数据）
        add_value = amount_to_float(add, "借方金额")
        minus_value = amount_to_float(minus, "贷方金额")
        # 审计 CW-17：账期取业务日期（调用方传合同 executedAt），缺省才是运行当天
        dtstr = format_business_date(business_date)
        i = 2
        while (sht[i,6].value != None):
            i += 1
        sht[i,0].value = dtstr
        if(i == 2):
            sht[i,2].value = 1
        if (sht[i,2].options(numbers=int).value != 1):
            sht[i,2].value =  sht[i-1,2].value + 1
        # 审计 CW-14：改前是 `if (add != 0): float(add)` ——
        # ① 金额为 0 时两列都不写，只留摘要与余额公式，形成借贷不对齐的「空金额行」；
        # ② 非法输入要走到这里才炸，前面的日期/序号已经写进表里。
        # 现在两列都写（0 也写），非法输入在方法开头就被拒绝。
        sht[i,3].value = add_value
        sht[i,4].value = minus_value
        if (sht[i,2].options(numbers=int).value != 1):
            sht[i,5].formula = f'=F{i}+D{i+1}-E{i+1}'
        elif (sht[i,2].options(numbers=int).value == 1):
            sht[i,5].formula = f'=B{i+1}+D{i+1}-E{i+1}'
        self.entries_to_assets_money = sht[i,5].get_address(include_sheetname=True)
        sht[i,6].value = str(number) + " " + str(about)
        self.wb.save()
    def add_book_item(self,thing:things,name:str,number:int,price:Decimal,add:bool,minus:bool):
        #
        if thing == things.RAWMETRIAL:
            sht = self.wb.sheets[1]
        elif thing == things.COMPENT:
            sht = self.wb.sheets[2]
        elif thing == things.PORDUCT:
            sht = self.wb.sheets[3]
        #
        # 审计 CW-16：改前的定位循环 `while (i != sht.used_range.last_cell.row)` 走到底后
        # `i -= 1` 再把该行覆写成「库存商品成本期末移动平均结转报告」并 `A{i+1}:L{i+1}` 合并 ——
        # 0 基索引算出的正是 Excel **最后一行**（通常是上一块物料的合计行），合并只保留左上角值，
        # 原数据不可恢复。这里保留原来的「按物料名 / 绿色槽位行定位块」逻辑，但把走到底的破坏性
        # 分支换成业务异常（watcher 会把该合同留在待处理队列重试），绝不写最后一行。
        last_row = sht.used_range.last_cell.row
        base = None
        i = 0
        while i < last_row:
            if (sht[i+4,0].value == name) or (
                (sht[i+4,0].color == (0,255,0)) and (sht[i+4,0].value == None)
            ):
                base = i
                break
            i += 1
        if base is None:
            raise ValueError(
                f"货品表里没有该物料的空槽位（名称 {name!r} 未登记且模板已写满）："
                f"改前会覆写最后一行（A{last_row}:L{last_row}）造成不可恢复的数据损坏。"
                "请在 target.xlsx 里为该物料扩充预置槽位块后重试"
            )
        # 在同一块的槽位区间里找第一个还没用过的空槽
        # （实测几何：块首 = `i+4` 那行的上一行；槽位行 = 块首 + 6 ~ +19（0 基），共 14 个；
        #   改前用 `value == 0` 判空槽，插行复制出来的空单元格是 None ⇒ 被跳过并最终静默丢弃）
        item_row = find_free_row(sht, range(base + 6, min(base + 20, last_row)), quantity_cols=(3, 6))
        if item_row is None:
            raise ValueError(
                f"物料 {name!r} 的槽位已写满（块首 0 基行 {base}）："
                "改前会静默丢弃本次数量并直接返回。请检查是否重复登记，"
                "或为该物料扩充预置槽位块"
            )
        i = item_row - 6   # 写数据代码沿用「定位值 i」的偏移约定（写入行 = i+6）
        if sht[i+4,0].value == None:
            sht[i+4,0].value = name
        # 审计 CW-16：改前写数据循环用 `sht[i+6,3].value == 0 and sht[i+6,6].value == 0` 判「空槽」，
        # 而模板里未使用的槽位数量列是 **空**（None != 0）⇒ 空槽被跳过、走到表尾直接 break
        # ⇒ 数量既不写入也不报错。现在写入行已由上面的 find_free_row 确定为可用空槽。
        add_value = float(price)
        if add == True:
            if sht[i+7,5].value == '本期采购入库':
                sht.range(f'{i+8}:{i+8}').insert(shift='down')
                sht.range(f'A{i+7}:L{i+7}').autofill(sht.range(f'A{i+8}:L{i+8}'))
            sht[i+6,3].value = number
            if thing.value == 3:
                sht[i+6,5].value = add_value
            else:
                sht[i+6,4].value = add_value
        elif minus == True:
            if sht[i+7,5].value == '本期采购入库':
                sht.range(f'{i+8}:{i+8}').insert(shift='down')
                sht.range(f'A{i+7}:L{i+7}').autofill(sht.range(f'A{i+8}:L{i+8}'))
            sht[i+6,6].value = number
        else:
            raise ValueError(
                f"货品表写入未指定方向（物料 {name!r}：add/minus 都是假值），已拒绝写入"
            )
        self.wb.save()
    def add_book_assets(self,type:BOOOKTYPE,name:ASSET,add:Decimal,minus:Decimal):
        # 审计 CW-14：与 add_book_entries 同一类金额（改前同样是裸 float()），先校验再动工作表
        add_value = amount_to_float(add, "借方金额")
        minus_value = amount_to_float(minus, "贷方金额")
        #
        if type == BOOOKTYPE.ASSETS:
            sht = self.wb.sheets[4]
        elif type == BOOOKTYPE.LIABILITIES:
            sht = self.wb.sheets[5]
            n = minus_value
            minus_value = add_value
            add_value = n
        elif type == BOOOKTYPE.EQUITY:
            sht = self.wb.sheets[6]
            n = minus_value
            minus_value = add_value
            add_value = n
        search_range = sht.api.UsedRange
        found_cell = search_range.Find(What=name.value,LookIn=xw.constants.FindLookIn.xlValues)
        # 审计 CW-18：改前不检查 Find 结果 —— 账套换版/科目改名/名称多一个空格导致未命中时，
        # `found_cell` 是 None，紧接着的 `found_cell.Row` 抛 AttributeError，被 watcher 的
        # dispatch 吞掉 ⇒ 该合同**静默漏账**（且按 CW-02 永不重试）；而 `Find` 命中标题/说明/
        # 合计行里的同名文本时，代码继续按 `+3` 行向下找「两个空 formula 单元格」写入 ⇒
        # 金额落进无关区域，账表被污染且没有任何报错。现在显式判空并校验命中位置。
        if found_cell is None:
            raise ValueError(
                f"账套里找不到科目「{name.value}」：合同无法记账。"
                "请确认账套版本与科目名称逐字一致（含全角括号等），或改用带该科目的账套后重试"
            )
        found_row, found_col = int(found_cell.Row), int(found_cell.Column)
        colunmT = found_col - 1
        rowT = found_row - 1 + 3
        # 命中位置校验：必须落在该表的科目名称列（A 列），且起始写入行必须仍在表内。
        # 否则说明 Find 命中的是标题/说明/合计行里的同名文本，继续写下去会污染无关区域。
        if colunmT != 0 or rowT <= 0 or rowT >= int(sht.used_range.last_cell.row):
            raise ValueError(
                f"科目「{name.value}」的定位不可信（Find 命中 {found_cell.Address}，"
                f"推导出写入起点 0 基行 {rowT}、列 {colunmT}）："
                "疑似命中了标题/说明/合计行里的同名文本。请检查账套模板或科目名称后重试"
            )
        while True:
            if(sht[rowT,colunmT].formula == '') and (sht[rowT,colunmT+1].formula == '') and (sht[rowT,colunmT-1].value == None):
                sht[rowT,colunmT].value = add_value
                sht[rowT,colunmT+1].value = minus_value
                break
            if sht[rowT,colunmT-1].value != None:
                sht.range(f'{sht[rowT,colunmT-1].address}:{sht[rowT+1,colunmT+1].address}').api.Cut()
                sht.range(f'{sht[rowT+1,colunmT]}').paste()
                if name.value == '银行存款':
                    sht[rowT+2,colunmT+1].formula = f'{sht[rowT+2,colunmT].address}-{self.entries_to_assets_money}'
                sht[rowT,colunmT].value = add_value
                sht[rowT,colunmT+1].value = minus_value
                break
            rowT += 1
        self.wb.save()