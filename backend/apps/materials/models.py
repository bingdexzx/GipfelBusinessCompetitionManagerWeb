"""原料模型：对应原 Prisma Material。"""
from django.db import models


class Material(models.Model):
    """原料（比赛级基础数据）。删除比赛时级联删除。"""

    TYPE_CHOICES = [("NORMAL", "NORMAL"), ("SPECIAL", "SPECIAL")]

    name = models.CharField(max_length=255)
    origin = models.CharField(max_length=255)
    carbon_emission_coefficient = models.FloatField()
    # 按地点（地图节点）价格：JSON 字符串 { [mapNodeId]: 价格 }
    node_prices = models.TextField(default="{}")
    type = models.CharField(max_length=16, default="NORMAL", choices=TYPE_CHOICES)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="materials",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "materials"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name
