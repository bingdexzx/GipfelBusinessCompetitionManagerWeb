"""产业类型序列化器：camelCase 对齐前端契约。

- config 在 DB 以 JSON 字符串存储，输出解析为对象；输入接收对象，落库时由视图
  序列化为 JSON 字符串（与 competitions 的 mapBackground 同一约定）。
- 产业类型输出附带 fields（按 sortOrder、id 升序）与 _count.companies。
"""
from __future__ import annotations

from rest_framework import serializers

from apps.common.json_util import parse_field_config

from .models import IndustryField, IndustryType

FIELD_TYPES = [c[0] for c in IndustryField.TYPE_CHOICES]
TIMER_TRIGGERS = [c[0] for c in IndustryField.TIMER_TRIGGER_CHOICES]


def _count_companies(industry_type_id: int) -> int:
    """统计引用某产业类型的公司数。延迟导入避免与 companies 应用循环依赖。"""
    from apps.companies.models import Company

    return Company.objects.filter(industry_type_id=industry_type_id).count()


class IndustryFieldSerializer(serializers.Serializer):
    """产业字段序列化器：输入校验 + camelCase 输出。"""

    id = serializers.IntegerField(read_only=True)
    industryTypeId = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=False, required=False)
    fieldKey = serializers.CharField(max_length=255, trim_whitespace=False, required=False)
    fieldType = serializers.ChoiceField(choices=FIELD_TYPES, default="NUMBER")
    # 输入接收对象；落库为 JSON 字符串由视图处理
    config = serializers.JSONField(required=False, allow_null=True)
    defaultValue = serializers.CharField(
        trim_whitespace=False, required=False, allow_null=True, allow_blank=True
    )
    isCalculated = serializers.BooleanField(required=False)
    # 产业计算图（GGraph JSON 字符串）
    calcGraph = serializers.CharField(
        trim_whitespace=False, required=False, allow_null=True, allow_blank=True
    )
    formula = serializers.CharField(
        trim_whitespace=False, required=False, allow_null=True, allow_blank=True
    )
    sortOrder = serializers.IntegerField(required=False)
    visible = serializers.BooleanField(required=False)
    timerEnabled = serializers.BooleanField(required=False)
    timerTrigger = serializers.ChoiceField(
        choices=TIMER_TRIGGERS, required=False, allow_null=True
    )
    timerValue = serializers.CharField(
        trim_whitespace=False, required=False, allow_null=True, allow_blank=True
    )
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: IndustryField) -> dict:
        return {
            "id": instance.id,
            "industryTypeId": instance.industry_type_id,
            "name": instance.name,
            "fieldKey": instance.field_key,
            "fieldType": instance.field_type,
            "config": parse_field_config(instance.config),
            "defaultValue": instance.default_value,
            "isCalculated": instance.is_calculated,
            "calcGraph": instance.calc_graph,
            "formula": instance.formula,
            "sortOrder": instance.sort_order,
            "visible": instance.visible,
            "timerEnabled": instance.timer_enabled,
            "timerTrigger": instance.timer_trigger,
            "timerValue": instance.timer_value,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }


class IndustryTypeSerializer(serializers.Serializer):
    """产业类型序列化器：输入校验 + camelCase 输出（含 fields 与 _count）。"""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=False, required=False)
    code = serializers.IntegerField(required=False)
    description = serializers.CharField(
        trim_whitespace=False, required=False, allow_null=True, allow_blank=True
    )
    icon = serializers.CharField(
        max_length=255, trim_whitespace=False, required=False, allow_null=True, allow_blank=True
    )
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: IndustryType) -> dict:
        fields_qs = instance.fields.all().order_by("sort_order", "id")
        return {
            "id": instance.id,
            "name": instance.name,
            "code": instance.code,
            "description": instance.description,
            "icon": instance.icon,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
            "fields": IndustryFieldSerializer(fields_qs, many=True).data,
            "_count": {"companies": _count_companies(instance.id)},
        }
