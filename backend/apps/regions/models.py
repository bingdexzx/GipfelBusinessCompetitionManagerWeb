"""区域模型：对应原 Prisma Region。"""
from django.db import models


class Region(models.Model):
    """区域（比赛级）。存储概览卡片配置 JSON 字符串。删除比赛时级联删除。"""

    name = models.CharField(max_length=128)
    description = models.TextField(null=True, blank=True)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="regions",
    )
    # 概览卡片 JSON 字符串：[{id, displayName, companyId, industryFieldId, zone?}]
    overview_cards = models.TextField(default="[]")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "regions"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name
