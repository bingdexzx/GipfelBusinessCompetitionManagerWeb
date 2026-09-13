import datetime as dt
import xlwings as xw
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
        except Exception:
            self._quit_quietly()
            raise

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
    def add_book_entries(self,add:Decimal,minus:Decimal,number:str,about:str):
        sht = self.wb.sheets[0]
        # 审计 CW-14：先做金额校验，非法输入在**写任何单元格之前**就抛出（避免留下半行脏数据）
        add_value = amount_to_float(add, "借方金额")
        minus_value = amount_to_float(minus, "贷方金额")
        cdt = dt.date.today()
        dtstr = cdt.strftime("%Y/%m/%d")
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
        i = 0
        while (i != sht.used_range.last_cell.row):
            if (sht[i,0].value != None):
                if(sht[i+4,0].value == name):
                    break
                if((sht[i+4,0].color == (0,255,0))and(sht[i+4,0].value == None)):
                    break
                i += 1
                continue
            i += 1
        if(i == sht.used_range.last_cell.row):
            i -= 1
            sht[i,0].value = '库存商品成本期末移动平均结转报告'
            sht.range(f'A{i+1}:L{i+1}').merge()
            sht[i+1,0].value = '编制单位：XXX公司'#可以处理
            cdt = dt.date.today()
            dtstr = cdt.strftime("%Y/%m/%d")
            sht[i+1,8].value = f'报告日期：{dtstr}'
            sht.range(f'I{i+2}:K{i+2}').merge()
            sht[i+2,0].value = '库存货品名称及批次'
            sht.range(f'A{i+3}:A{i+4}').merge()
            sht[i+2,1].value = '期初数'
            sht.range(f'B{i+3}:C{i+3}').merge()
            sht[i+3,1].value = '数量'
            sht[i+3,2].value = '总计金额'
            sht[i+2,3].value = '采购入库'
            sht.range(f'D{i+3}:F{i+3}').merge()
            sht[i+2,3].color = '#FFFF00'
            sht[i+3,3].value = '数量'
            sht[i+5,3].value = 0
            sht[i+6,3].value = 0
            sht[i+3,4].value = '单价'
            sht[i+3,5].value = '采购金额'
            sht[i+2,6].value = '耗用出库'
            sht.range(f'G{i+3}:I{i+3}').merge()
            sht[i+2,6].color = '#FF3399'
            sht[i+3,6].value = '数量'
            sht[i+5,6].value = 0
            sht[i+6,6].value = 0
            sht[i+3,7].value = '加权平均单价'
            sht[i+3,8].value = '出库金额'
            sht[i+2,9].value = '结存'
            sht.range(f'J{i+3}:L{i+3}').merge()
            sht[i+2,9].color = '#FF8000'
            sht[i+3,9].value = '剩余数量'
            sht[i+3,10].value = '加权平均单价'
            sht[i+3,11].value = '剩余总额'
            sht[i+4,0].color = '#00FF00'
            sht[i+4,0].value = name
            sht[i+4,2].formula = f'=20*B{i+5}'
            if (thing.value != 3):
                sht[i+5,5].formula = f'=D{i+6}*E{i+6}'
                sht[i+6,5].formula = f'=D{i+7}*E{i+7}'
            elif thing.value == 3:
                sht[i+5,4].formula = f'=IF(D{i+6}=0,0,F{i+6}/D{i+6})'
                sht[i+6,4].formula = f'=IF(D{i+7}=0,0,F{i+7}/D{i+7})'
            sht[i+6,7].formula = f'=K{i+6}'
            sht[i+5,8].formula = f'=IF(F{i+6},G{i+6}*G{i+6},0)'
            sht[i+6,8].formula = f'=IF(F{i+7},G{i+7}*G{i+7},0)'
            sht[i+5,9].formula = f'=D{i+6}-G{i+6}+J{i+5}'
            sht[i+6,9].formula = f'=D{i+7}-G{i+7}+J{i+6}'
            sht[i+5,10].formula = f'=IF(J{i+6}=0,0,L{i+6}/J{i+6})'
            sht[i+6,10].formula = f'=IF(J{i+7}=0,0,L{i+7}/J{i+7})'
            sht[i+5,11].formula = f'=IF(F{i+6},L{i+5}-I{i+6},L{i+5}+F{i+6})'
            sht[i+6,11].formula = f'=IF(F{i+7},L{i+6}-I{i+7},L{i+6}+F{i+7})'
            sht[i+7,5].value = '本期采购入库'
            sht[i+7,6].formula = f'=SUM(F{i+6}:F{i+7})'
            sht[i+7,7].value = '本期出库金额'
            sht[i+7,8].formula = f'=SUM(I{i+6}:I{i+7})'
            sht[i+7,10].value = '剩余总额'
            sht[i+7,11].formula = f'=L{i+7}'
            if (thing.value != 3):
                sht[i+9,9].value = '结存'
                sht[i+9,10].value = '总库存净额'
                allplus:str = ''
                for m in range(1,i+9+1):
                    if(sht[m,10].value == '剩余总额'):
                        allplus += sht[m,11].get_address(row_absolute=False,column_absolute=False) + '+'
                allplus = allplus[:-1]
                sht[i+9,11].formula = f'={allplus}'
                if thing.value == 1:
                    shtT = self.wb.sheets[4]
                    search_range = sht.api.UsedRange
                    found_cell = search_range.Find(What='原材料',LookIn=xw.constants.FindLookIn.xlValues)
                    shtTT = shtT.range(found_cell.Address)
                    sht[shtTT+2,shtTT-1].value = f'={sht[i+9,11].get_address(include_sheetname=True,row_absolute=False,column_absolute=False)}'
                if thing.value == 2:
                    shtT = self.wb.sheets[4]
                    search_range = sht.api.UsedRange
                    found_cell = search_range.Find(What='半成品（零件）',LookIn=xw.constants.FindLookIn.xlValues)
                    shtTT = shtT.range(found_cell.Address)
                    sht[shtTT+2,shtTT-1].value = f'={sht[i+9,11].get_address(include_sheetname=True,row_absolute=False,column_absolute=False)}'
            if(thing.value == 3):
                sht[i+9,9].value = '结转'
                sht[i+9,10].value = '总商品净额'
                sht[i+10,10].value = '主营业务成本'
                allplus:str = ''
                for m in range(1,i+9+1):
                    if(sht[m,10].value == '剩余总额'):
                        allplus += sht[m,11].get_address(row_absolute=False,column_absolute=False) + '+'
                allplus = allplus[:-1]
                sht[i+9,11].formula = f'={allplus}'
                allplus:str = ''
                for m in range(1,i+9+1):
                    if(sht[m,10].value == '本期出库金额：'):
                        allplus += sht[m,7].get_address(row_absolute=False,column_absolute=False) + '+'
                allplus = allplus[:-1]
                sht[i+9,11].formula = f'={allplus}'
                shtT = self.wb.sheets[4]
                search_range = sht.api.UsedRange
                found_cell = search_range.Find(What='库存商品',LookIn=xw.constants.FindLookIn.xlValues)
                shtTT = shtT.range(found_cell.Address)
                sht[shtTT+2,shtTT-1].value = f'={sht[i+9,11].get_address(include_sheetname=True,row_absolute=False,column_absolute=False)}'
                shtT = self.wb.sheets[6]
                search_range = sht.api.UsedRange
                found_cell = search_range.Find(What='主营业务成本-存货成本',LookIn=xw.constants.FindLookIn.xlValues)
                shtTT = shtT.range(found_cell.Address)
                sht[shtTT+2,shtTT-1].value = f'={sht[i+10,11].get_address(include_sheetname=True,row_absolute=False,column_absolute=False)}'
        #写入数据
        if sht[i+4,0].value == None:
            sht[i+4,0].value = name
        while True:
            if i == sht.used_range.last_cell.row:
                break
            if (sht[i+6,3].value == 0) and (sht[i+6,6].value == 0):
                if add == True:
                    if sht[i+7,5].value == '本期采购入库':
                        sht.range(f'{i+8}:{i+8}').insert(shift='down')
                        sht.range(f'A{i+7}:L{i+7}').autofill(sht.range(f'A{i+8}:L{i+8}'))
                    sht[i+6,3].value = number
                    if thing.value == 3:
                        sht[i+6,5].value = float(price)
                        break
                    sht[i+6,4].value = float(price)
                    break
                if minus ==True:
                    if sht[i+7,5].value == '本期采购入库':
                        sht.range(f'{i+8}:{i+8}').insert(shift='down')
                        sht.range(f'A{i+7}:L{i+7}').autofill(sht.range(f'A{i+8}:L{i+8}'))
                    sht[i+6,6].value = number
                    break
            i += 1
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
        colunmT = 0
        rowT = 0
        rowT = found_cell.Row-1
        colunmT = found_cell.Column-1
        rowT += 3
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