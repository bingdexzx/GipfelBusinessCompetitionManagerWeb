"""基建模型：对应原 Prisma Infrastructure。"""
from django.db import models


class Infrastructure(models.Model):
    """基建（比赛级基础数据）。删除比赛时级联删除。"""

    name = models.CharField(max_length=255)
    footprint = models.FloatField()
    employment_rate_bonus = models.FloatField(default=0)
    population_bonus = models.FloatField(default=0)
    high_quality_population_bonus = models.FloatField(default=0)
    price = models.FloatField()
    happiness_index_bonus = models.FloatField(default=0)
    per_capita_income_bonus = models.FloatField(default=0)
    carbon_reduction_bonus = models.FloatField(default=0)
    activation_price = models.FloatField()
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
