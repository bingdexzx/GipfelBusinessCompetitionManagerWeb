"""股票系统模型：对应原 Prisma Stock / StockFundsAccount / StockHolding / StockOrder / StockCandle。

注：companyId / userId / bindFieldId / pbCompanyId / pbFieldId 仅以 IntegerField
保存外键引用（不建立 FK 关系），避免跨应用级联复杂度——它们只是 int 引用。
Stock.company 例外，建立到 companies.Company 的 FK（on_delete=SET_NULL）。
"""
from django.db import models


class Stock(models.Model):
    """股票。删除比赛时级联删除。"""

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    # 基础信息（万股 / 万元）
    total_shares = models.FloatField()
    init_net_profit = models.FloatField()
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
    # 派生 / 运行时字段
    init_price = models.FloatField()
    current_price = models.FloatField()
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
    cash_balance = models.FloatField(default=1_000_000)
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
    shares = models.FloatField()
    cost_price = models.FloatField()
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
    price = models.FloatField()
    quantity = models.FloatField()
    amount = models.FloatField()
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
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    change_pct = models.FloatField()
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
