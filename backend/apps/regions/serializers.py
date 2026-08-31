"""区域序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

import json

from rest_framework import serializers

from apps.common.json_util import parse_json_array

from .models import Region


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


class OverviewCardItemSerializer(serializers.Serializer):
    """单张概览卡片：{id, displayName, companyId, industryFieldId, zone?}。"""

    id = serializers.CharField()
    displayName = serializers.CharField()
    companyId = serializers.IntegerField()
    industryFieldId = serializers.IntegerField()
    zone = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class RegionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    competitionId = serializers.IntegerField()
    overviewCards = serializers.ListField(
        child=OverviewCardItemSerializer(),
        required=False,
        allow_null=True,
        allow_empty=True,
    )
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Region) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "description": instance.description,
            "competitionId": instance.competition_id,
            "overviewCards": parse_json_array(instance.overview_cards),
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def create(self, validated_data: dict) -> Region:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        cards = validated_data.get("overviewCards") or []
        return Region.objects.create(
            name=validated_data["name"],
            description=validated_data.get("description"),
            competition_id=cid,
            overview_cards=json.dumps(cards, ensure_ascii=False),
        )

    def update(self, instance: Region, validated_data: dict) -> Region:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "description" in validated_data:
            instance.description = validated_data["description"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        if "overviewCards" in validated_data:
            cards = validated_data["overviewCards"] or []
            instance.overview_cards = json.dumps(cards, ensure_ascii=False)
        instance.save()
        return instance
