"""产业类型模型：对应原 Prisma IndustryType / IndustryField。

产业类型为全局资源（无 competitionId），供各比赛的公司引用。
"""
from django.db import models


class IndustryType(models.Model):
    """产业类型（全局模板）。被公司引用；删除公司时仅置空其引用。"""

    name = models.CharField(max_length=255)
    code = models.IntegerField(unique=True)
    description = models.TextField(null=True, blank=True)
    icon = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "industry_types"

    def __str__(self):
        return self.name


class IndustryField(models.Model):
    """产业字段：定义某产业类型下公司需填报的字段。

    config / calcGraph 在 DB 以 JSON 字符串（TextField）存储，API 输出时
    config 解析为对象（calcGraph 保持字符串）。每产业类型自动带一个
    fieldKey="location" 的「所在地」字段。
    """

    TYPE_CHOICES = [
        ("STRING", "STRING"),
        ("NUMBER", "NUMBER"),
        ("BOOLEAN", "BOOLEAN"),
        ("DICTIONARY", "DICTIONARY"),
        ("LIST", "LIST"),
    ]
    TIMER_TRIGGER_CHOICES = [
        ("FY_START", "FY_START"),
        ("FY_END", "FY_END"),
    ]

    industry_type = models.ForeignKey(
        IndustryType,
        on_delete=models.CASCADE,
        related_name="fields",
    )
    name = models.CharField(max_length=255)
    field_key = models.CharField(max_length=255)
    # STRING / NUMBER / BOOLEAN / DICTIONARY / LIST
    field_type = models.CharField(max_length=16, default="NUMBER", choices=TYPE_CHOICES)
    # 类型相关配置（JSON 字符串）：DICTIONARY -> { entries, valueType }；LIST -> { itemType }
    config = models.TextField(default="{}")
    default_value = models.TextField(null=True, blank=True)
    is_calculated = models.BooleanField(default=False)
    # 产业计算图（GGraph JSON 字符串）：isCalculated=true 时由该图级联重算本字段
    calc_graph = models.TextField(null=True, blank=True)
    # 旧公式引擎，已废弃（保留列以兼容历史数据）
    formula = models.TextField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    # 仅展示层开关；合同引擎仍按 fieldKey 读写其 CompanyFieldValue
    visible = models.BooleanField(default=True)
    # 财年定时器：不可与 isCalculated 同时启用
    timer_enabled = models.BooleanField(default=False)
    timer_trigger = models.CharField(
        max_length=16, null=True, blank=True, choices=TIMER_TRIGGER_CHOICES
    )
    timer_value = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "industry_fields"
        unique_together = (("industry_type", "field_key"),)

    def __str__(self):
        return self.name
