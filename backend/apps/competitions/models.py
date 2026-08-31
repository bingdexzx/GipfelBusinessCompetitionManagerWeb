"""比赛与财年模型：对应原 Prisma Competition / FiscalYear。"""
from django.db import models


class Competition(models.Model):
    """比赛（租户根）。删除时级联删除所有子资源。"""

    STATUS_CHOICES = [("ACTIVE", "ACTIVE"), ("CLOSED", "CLOSED")]

    name = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, default="ACTIVE", choices=STATUS_CHOICES)
    # 地图背景图 JSON 字符串 {url, filename, width, height}
    map_background = models.TextField(null=True, blank=True)
    # 股票系统全局配置 JSON（null = DEFAULT_STOCK_CONFIG）
    stock_config = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "competitions"

    def __str__(self):
        return self.name


class FiscalYear(models.Model):
    STATUS_CHOICES = [("ACTIVE", "ACTIVE"), ("CLOSED", "CLOSED")]

    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="fiscal_years",
    )
    year = models.IntegerField()
    status = models.CharField(max_length=16, default="ACTIVE", choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fiscal_years"
        unique_together = (("competition", "year"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]
