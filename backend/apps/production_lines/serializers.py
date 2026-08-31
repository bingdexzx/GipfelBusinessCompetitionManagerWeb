"""生产线序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

from rest_framework import serializers

from .models import ProductionLine


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


class ProductionLineSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    price = serializers.FloatField()
    laborCount = serializers.IntegerField()
    maxPerYear = serializers.FloatField()
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: ProductionLine) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "price": instance.price,
            "laborCount": instance.labor_count,
            "maxPerYear": instance.max_per_year,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def create(self, validated_data: dict) -> ProductionLine:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        return ProductionLine.objects.create(
            name=validated_data["name"],
            price=validated_data["price"],
            labor_count=validated_data["laborCount"],
            max_per_year=validated_data["maxPerYear"],
            competition_id=cid,
        )

    def update(self, instance: ProductionLine, validated_data: dict) -> ProductionLine:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "price" in validated_data:
            instance.price = validated_data["price"]
        if "laborCount" in validated_data:
            instance.labor_count = validated_data["laborCount"]
        if "maxPerYear" in validated_data:
            instance.max_per_year = validated_data["maxPerYear"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        instance.save()
        return instance
