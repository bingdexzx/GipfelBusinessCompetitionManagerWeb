"""基建序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

from rest_framework import serializers

from .models import Infrastructure


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


class InfrastructureSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    footprint = serializers.FloatField()
    employmentRateBonus = serializers.FloatField(default=0)
    populationBonus = serializers.FloatField(default=0)
    highQualityPopulationBonus = serializers.FloatField(default=0)
    price = serializers.FloatField()
    happinessIndexBonus = serializers.FloatField(default=0)
    perCapitaIncomeBonus = serializers.FloatField(default=0)
    carbonReductionBonus = serializers.FloatField(default=0)
    activationPrice = serializers.FloatField()
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Infrastructure) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "footprint": instance.footprint,
            "employmentRateBonus": instance.employment_rate_bonus,
            "populationBonus": instance.population_bonus,
            "highQualityPopulationBonus": instance.high_quality_population_bonus,
            "price": instance.price,
            "happinessIndexBonus": instance.happiness_index_bonus,
            "perCapitaIncomeBonus": instance.per_capita_income_bonus,
            "carbonReductionBonus": instance.carbon_reduction_bonus,
            "activationPrice": instance.activation_price,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def create(self, validated_data: dict) -> Infrastructure:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        return Infrastructure.objects.create(
            name=validated_data["name"],
            footprint=validated_data["footprint"],
            employment_rate_bonus=validated_data.get("employmentRateBonus", 0),
            population_bonus=validated_data.get("populationBonus", 0),
            high_quality_population_bonus=validated_data.get("highQualityPopulationBonus", 0),
            price=validated_data["price"],
            happiness_index_bonus=validated_data.get("happinessIndexBonus", 0),
            per_capita_income_bonus=validated_data.get("perCapitaIncomeBonus", 0),
            carbon_reduction_bonus=validated_data.get("carbonReductionBonus", 0),
            activation_price=validated_data["activationPrice"],
            competition_id=cid,
        )

    def update(self, instance: Infrastructure, validated_data: dict) -> Infrastructure:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "footprint" in validated_data:
            instance.footprint = validated_data["footprint"]
        if "employmentRateBonus" in validated_data:
            instance.employment_rate_bonus = validated_data["employmentRateBonus"]
        if "populationBonus" in validated_data:
            instance.population_bonus = validated_data["populationBonus"]
        if "highQualityPopulationBonus" in validated_data:
            instance.high_quality_population_bonus = validated_data["highQualityPopulationBonus"]
        if "price" in validated_data:
            instance.price = validated_data["price"]
        if "happinessIndexBonus" in validated_data:
            instance.happiness_index_bonus = validated_data["happinessIndexBonus"]
        if "perCapitaIncomeBonus" in validated_data:
            instance.per_capita_income_bonus = validated_data["perCapitaIncomeBonus"]
        if "carbonReductionBonus" in validated_data:
            instance.carbon_reduction_bonus = validated_data["carbonReductionBonus"]
        if "activationPrice" in validated_data:
            instance.activation_price = validated_data["activationPrice"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        instance.save()
        return instance
