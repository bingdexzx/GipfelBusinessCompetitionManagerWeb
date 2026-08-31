"""生产线模型：对应原 Prisma ProductionLine。"""
from django.db import models


class ProductionLine(models.Model):
    """生产线（比赛级基础数据）。删除比赛时级联删除。"""

    name = models.CharField(max_length=255)
    price = models.FloatField()
    labor_count = models.IntegerField()
    max_per_year = models.FloatField()
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="production_lines",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "production_lines"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name
