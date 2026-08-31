"""公司模型：对应原 Prisma Company / CompanyFieldValue。"""
from django.db import models


class Company(models.Model):
    """公司（比赛级参赛主体）。删除比赛时级联删除。"""

    STATUS_CHOICES = [("ACTIVE", "ACTIVE"), ("INACTIVE", "INACTIVE")]

    name = models.CharField(max_length=255)
    industry_type = models.ForeignKey(
        "industry_types.IndustryType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="companies",
    )
    status = models.CharField(max_length=16, default="ACTIVE", choices=STATUS_CHOICES)
    region = models.ForeignKey(
        "regions.Region",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "companies"
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class CompanyFieldValue(models.Model):
    """公司产业字段值（乐观锁 version）。无 created_at，仅 updated_at，与 Prisma 一致。"""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="field_values",
    )
    industry_field = models.ForeignKey(
        "industry_types.IndustryField",
        on_delete=models.CASCADE,
        related_name="field_values",
    )
    value = models.TextField(default="")
    version = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "company_field_values"
        unique_together = (("company", "industry_field"),)
        indexes = [models.Index(fields=["version"])]

    def __str__(self):
        return f"company={self.company_id} field={self.industry_field_id}"
