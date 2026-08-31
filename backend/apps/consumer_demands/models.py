"""消费者需求模型：对应原 Prisma ConsumerDemand。"""
from django.db import models


class ConsumerDemand(models.Model):
    """消费者需求（比赛级，按区域）。删除比赛时级联删除。

    product_type 为冗余字段，冗余存储 product.name，便于列表展示与历史留痕。
    """

    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="consumer_demands",
    )
    region = models.CharField(max_length=128)
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consumer_demands",
    )
    product_type = models.CharField(max_length=128)
    quantity = models.IntegerField(default=0)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "consumer_demands"
        indexes = [
            models.Index(fields=["competition", "region"]),
            models.Index(fields=["competition", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.region}-{self.product_type}"
