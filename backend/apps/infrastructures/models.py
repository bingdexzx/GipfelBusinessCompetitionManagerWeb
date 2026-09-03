"""基建模型。"""
from django.db import models


class Infrastructure(models.Model):
    """基建（比赛级基础数据）。删除比赛时级联删除。"""

    name = models.CharField(max_length=255)
    # footprint 是面积（可保留 Float：图形属性，非账目）
    footprint = models.FloatField()
    # bonus 系列：百分比系数（0.05=+5%），用 Float 保留（区间运算，精度足）
    employment_rate_bonus = models.FloatField(default=0)
    population_bonus = models.FloatField(default=0)
    high_quality_population_bonus = models.FloatField(default=0)
    # 价格类：必须 Decimal（玩家购买场景）
    price = models.DecimalField(max_digits=18, decimal_places=4)
    happiness_index_bonus = models.FloatField(default=0)
    per_capita_income_bonus = models.FloatField(default=0)
    carbon_reduction_bonus = models.FloatField(default=0)
    activation_price = models.DecimalField(max_digits=18, decimal_places=4)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="infrastructures",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "infrastructures"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name
