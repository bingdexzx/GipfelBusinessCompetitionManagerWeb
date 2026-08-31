"""原料序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

from rest_framework import serializers

from .models import Material

_TYPE_CHOICES = [c[0] for c in Material.TYPE_CHOICES]


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


class MaterialSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    origin = serializers.CharField(max_length=255, trim_whitespace=True)
    carbonEmissionCoefficient = serializers.FloatField()
    type = serializers.ChoiceField(choices=_TYPE_CHOICES, default="NORMAL")
    nodePrices = serializers.CharField(allow_blank=True, default="{}", required=False)
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Material) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "origin": instance.origin,
            "carbonEmissionCoefficient": instance.carbon_emission_coefficient,
            "type": instance.type,
            "nodePrices": instance.node_prices,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def validate_origin(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("产地不能为空")
        return value

    def create(self, validated_data: dict) -> Material:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        return Material.objects.create(
            name=validated_data["name"],
            origin=validated_data["origin"],
            carbon_emission_coefficient=validated_data["carbonEmissionCoefficient"],
            type=validated_data.get("type", "NORMAL"),
            node_prices=validated_data.get("nodePrices", "{}"),
            competition_id=cid,
        )

    def update(self, instance: Material, validated_data: dict) -> Material:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "origin" in validated_data:
            instance.origin = validated_data["origin"]
        if "carbonEmissionCoefficient" in validated_data:
            instance.carbon_emission_coefficient = validated_data["carbonEmissionCoefficient"]
        if "type" in validated_data:
            instance.type = validated_data["type"]
        if "nodePrices" in validated_data:
            instance.node_prices = validated_data["nodePrices"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        instance.save()
        return instance
