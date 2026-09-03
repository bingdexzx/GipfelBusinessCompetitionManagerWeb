"""燃料模型。"""
from django.db import models


class Fuel(models.Model):
    """燃料（比赛级基础数据）。删除比赛时级联删除。"""

    name = models.CharField(max_length=255)
    # 燃料单价：玩家购买时累加到现金支出，浮点累计会漂。改 Decimal。
    price_per_liter = models.DecimalField(max_digits=18, decimal_places=4)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="fuels",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fuels"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name
