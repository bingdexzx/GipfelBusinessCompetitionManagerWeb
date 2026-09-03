"""公司序列化器：camelCase 对齐前端契约。

输出含嵌套 industryType（{id,name} 或 null）与 _count.companies（公司产业字段值数）。
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Company
from apps.common.helpers import assert_competition_exists as _assert_competition_exists

_STATUS_CHOICES = [c[0] for c in Company.STATUS_CHOICES]



def _industry_type_repr(company: Company) -> dict | None:
    it = company.industry_type
    if it is None:
        return None
    return {"id": it.id, "name": getattr(it, "name", None)}


class CompanySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    industryTypeId = serializers.IntegerField(allow_null=True, required=False)
    competitionId = serializers.IntegerField()
    regionId = serializers.IntegerField(allow_null=True, required=False)
    status = serializers.ChoiceField(choices=_STATUS_CHOICES, default="ACTIVE")
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Company) -> dict:
        count = getattr(instance, "_field_values_count", None)
        if count is None:
            count = instance.field_values.count()
        return {
            "id": instance.id,
            "name": instance.name,
            "industryTypeId": instance.industry_type_id,
            "competitionId": instance.competition_id,
            "status": instance.status,
            "regionId": instance.region_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
            "industryType": _industry_type_repr(instance),
            "_count": {"companies": count},
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def validate(self, attrs: dict) -> dict:
        name = attrs.get("name") or (self.instance.name if self.instance else None)
        cid = attrs.get("competitionId") or (self.instance.competition_id if self.instance else None)
        if name and cid:
            qs = Company.objects.filter(competition_id=cid, name=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"name": "同一比赛下已存在同名公司"})
        return attrs

    def create(self, validated_data: dict) -> Company:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        return Company.objects.create(
            name=validated_data["name"],
            industry_type_id=validated_data.get("industryTypeId"),
            competition_id=cid,
            region_id=validated_data.get("regionId"),
            status=validated_data.get("status", "ACTIVE"),
        )

    def update(self, instance: Company, validated_data: dict) -> Company:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "industryTypeId" in validated_data:
            instance.industry_type_id = validated_data["industryTypeId"]
        # 禁止跨比赛迁移公司：忽略 competitionId 字段
        if "regionId" in validated_data:
            instance.region_id = validated_data["regionId"]
        if "status" in validated_data:
            instance.status = validated_data["status"]
        instance.save(update_fields=[
            f for f in ["name", "industry_type_id", "region_id", "status", "updated_at"]
            if f in validated_data or f == "updated_at"
        ])
        return instance
