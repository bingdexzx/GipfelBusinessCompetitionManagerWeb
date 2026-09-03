"""燃料序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

from rest_framework import serializers

from .models import Fuel
from apps.common.helpers import assert_competition_exists as _assert_competition_exists



class FuelSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    pricePerLiter = serializers.FloatField()
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Fuel) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "pricePerLiter": instance.price_per_liter,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def create(self, validated_data: dict) -> Fuel:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        return Fuel.objects.create(
            name=validated_data["name"],
            price_per_liter=validated_data["pricePerLiter"],
            competition_id=cid,
        )

    def update(self, instance: Fuel, validated_data: dict) -> Fuel:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "pricePerLiter" in validated_data:
            instance.price_per_liter = validated_data["pricePerLiter"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        instance.save()
        return instance
