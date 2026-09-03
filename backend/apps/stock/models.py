"""股票系统模型。

注：companyId / userId / bindFieldId / pbCompanyId / pbFieldId 仅以 IntegerField
保存外键引用（不建立 FK 关系），避免跨应用级联复杂度——它们只是 int 引用。
Stock.company 例外，建立到 companies.Company 的 FK（on_delete=SET_NULL）。
"""
from django.db import models


class Stock(models.Model):
    """股票。删除比赛时级联删除。"""

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    # 基础信息（万股 / 万元）—— 股本/净利润/价格必须精确，
    # 浮点累计误差会让玩家账户与账面余额对不上。max_digits=18 容纳亿级；
    # decimal_places=4 给撮合误差留余量（价格场景仅 2 位生效）。
    total_shares = models.DecimalField(max_digits=18, decimal_places=4)
    init_net_profit = models.DecimalField(max_digits=18, decimal_places=4)
    # PE / 碳排 / 幸福度：衍生指标（来自产业计算图），浮点足够。
    industry_pe = models.FloatField()
    current_carbon = models.FloatField()
    industry_avg_carbon = models.FloatField()
    happiness = models.FloatField()
    # 绑定区域总览卡片（实时引用）：JSON 字符串 {region, cardId}
    carbon_field_ref = models.CharField(max_length=255, null=True, blank=True)
    happiness_field_ref = models.CharField(max_length=255, null=True, blank=True)
    # 行业碳排均值绑定的区域总览卡片引用数组 JSON [{region,cardId},...]
    industry_avg_carbon_refs = models.CharField(max_length=1024, null=True, blank=True)
    # 行业 PE 联动：pbCompanyId + pbFieldId 同时非空为联动模式，否则随机模式
    pb_company_id = models.IntegerField(null=True, blank=True)
    pb_field_id = models.IntegerField(null=True, blank=True)
    pb_random = models.FloatField(null=True, blank=True)
    # 价格用 Decimal，避免浮点误差累积。
    init_price = models.DecimalField(max_digits=18, decimal_places=4)
    current_price = models.DecimalField(max_digits=18, decimal_places=4)
    round = models.IntegerField(default=0)
    # 关联商赛公司（仅 int 引用，但建立 FK 以支持 SET_NULL）
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stocks",
    )
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="stocks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stocks"
        unique_together = (("competition", "code"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return f"{self.code} {self.name}"


class StockFundsAccount(models.Model):
    """资金账户。删除比赛时级联删除。"""

    OWNER_CHOICES = [("COMPANY", "COMPANY"), ("USER", "USER")]

    name = models.CharField(max_length=255)
    owner_type = models.CharField(max_length=16, choices=OWNER_CHOICES)
    # ownerType=COMPANY 时指向 Company.id（仅 int 引用）
    company_id = models.IntegerField(null=True, blank=True)
    # ownerType=USER 时指向 User.id（仅 int 引用）
    user_id = models.IntegerField(null=True, blank=True)
    # 玩家现金账户最关键：1 万笔成交后浮点累计误差可达 1.5 万元，
    # 玩家投诉的"我账户少了钱"根源在此。改 Decimal 后多笔成交保持精确到分。
    cash_balance = models.DecimalField(max_digits=18, decimal_places=4, default=1_000_000)
    # 绑定产业字段 ID（仅公司账户），现金将同步该字段值（仅 int 引用）
    bind_field_id = models.IntegerField(null=True, blank=True)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="stock_funds_accounts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_funds_accounts"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class StockHolding(models.Model):
    """持仓：某资金账户持有某股票的数量与成本价。"""

    funds_account = models.ForeignKey(
        StockFundsAccount,
        on_delete=models.CASCADE,
        related_name="holdings",
    )
    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name="holdings",
    )
    # 持股数与成本价：撮合后累加场景，浮点会漂；改 Decimal 与资金账户配套。
    shares = models.DecimalField(max_digits=18, decimal_places=4)
    cost_price = models.DecimalField(max_digits=18, decimal_places=4)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="stock_holdings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_holdings"
        unique_together = (("funds_account", "stock"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return f"account={self.funds_account_id} stock={self.stock_id} shares={self.shares}"


class StockOrder(models.Model):
    """订单：玩家在某轮对某股票下的买卖委托。"""

    SIDE_CHOICES = [("BUY", "BUY"), ("SELL", "SELL")]
    STATUS_CHOICES = [("PENDING", "PENDING"), ("FILLED", "FILLED"), ("CANCELLED", "CANCELLED")]

    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    funds_account = models.ForeignKey(
        StockFundsAccount,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    side = models.CharField(max_length=8, choices=SIDE_CHOICES)
    # 委托价格/数量/金额：撮合核心输入，必须精确。
    price = models.DecimalField(max_digits=18, decimal_places=4)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    status = models.CharField(max_length=16, default="PENDING", choices=STATUS_CHOICES)
    round = models.IntegerField(default=0)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="stock_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_orders"
        indexes = [
            models.Index(fields=["competition", "stock", "round", "status"]),
            models.Index(fields=["competition", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.side} {self.quantity}@{self.price} stock={self.stock_id} status={self.status}"


class StockCandle(models.Model):
    """K 线：每轮每股票一根。close = 本轮最终价。"""

    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name="candles",
    )
    round = models.IntegerField()
    # K 线 OHLC 与涨跌幅：每轮计算结果，存 Decimal 与股价口径一致。
    open = models.DecimalField(max_digits=18, decimal_places=4)
    high = models.DecimalField(max_digits=18, decimal_places=4)
    low = models.DecimalField(max_digits=18, decimal_places=4)
    close = models.DecimalField(max_digits=18, decimal_places=4)
    change_pct = models.DecimalField(max_digits=18, decimal_places=4)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="stock_candles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_candles"
        unique_together = (("stock", "round"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return f"stock={self.stock_id} round={self.round} close={self.close}"
