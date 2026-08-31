"""仓库序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

from rest_framework import serializers

from .models import Warehouse

_TYPE_CHOICES = [c[0] for c in Warehouse.TYPE_CHOICES]


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


class WarehouseSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    capacity = serializers.FloatField()
    price = serializers.FloatField()
    type = serializers.ChoiceField(choices=_TYPE_CHOICES)
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Warehouse) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "capacity": instance.capacity,
            "price": instance.price,
            "type": instance.type,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def create(self, validated_data: dict) -> Warehouse:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        return Warehouse.objects.create(
            name=validated_data["name"],
            capacity=validated_data["capacity"],
            price=validated_data["price"],
            type=validated_data["type"],
            competition_id=cid,
        )

    def update(self, instance: Warehouse, validated_data: dict) -> Warehouse:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "capacity" in validated_data:
            instance.capacity = validated_data["capacity"]
        if "price" in validated_data:
            instance.price = validated_data["price"]
        if "type" in validated_data:
            instance.type = validated_data["type"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        instance.save()
        return instance
