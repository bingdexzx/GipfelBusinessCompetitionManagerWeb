"""仓库模型。"""
from django.db import models


class Warehouse(models.Model):
    """仓库（比赛级基础数据）。删除比赛时级联删除。"""

    TYPE_CHOICES = [
        ("MATERIAL", "MATERIAL"),
        ("PART", "PART"),
        ("PRODUCT", "PRODUCT"),
    ]

    name = models.CharField(max_length=255)
    # 容量 + 价格：玩家购买场景，必须 Decimal。
    capacity = models.DecimalField(max_digits=18, decimal_places=4)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="warehouses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "warehouses"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name
