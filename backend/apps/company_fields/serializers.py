"""公司产业字段值写入序列化器：camelCase 对齐前端契约。

- SetValuesSerializer：PUT /company-fields/:companyId 批量写入入参
- SetFieldSerializer：PUT /company-fields/:companyId/:fieldId 单字段写入入参
"""
from __future__ import annotations

from rest_framework import serializers


class FieldValueItemSerializer(serializers.Serializer):
    """批量写入中的单项：{industryFieldId, value, version?}。"""

    industryFieldId = serializers.IntegerField()
    value = serializers.CharField(allow_blank=True, allow_null=True, default="")
    version = serializers.IntegerField(required=False, allow_null=True)


class SetValuesSerializer(serializers.Serializer):
    """PUT /company-fields/:companyId {industryTypeId?, fields:[...]}。"""

    industryTypeId = serializers.IntegerField(required=False, allow_null=True)
    fields = serializers.ListField(
        child=FieldValueItemSerializer(), allow_empty=True
    )


class SetFieldSerializer(serializers.Serializer):
    """PUT /company-fields/:companyId/:fieldId {value, version?}。"""

    value = serializers.CharField(allow_blank=True, allow_null=True, default="")
    version = serializers.IntegerField(required=False, allow_null=True)
