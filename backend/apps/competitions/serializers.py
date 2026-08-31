"""比赛与财年序列化器：camelCase 对齐前端契约。

Competition.map_background 在 DB 以 JSON 字符串（TextField）存储，序列化输出
为对象、反序列化输入接收对象并落库为 JSON 字符串；stock_config 为原生
JSONField，直接以对象读写。
"""
from __future__ import annotations

import json

from rest_framework import serializers

from .models import Competition, FiscalYear

_STATUS_CHOICES = [c[0] for c in Competition.STATUS_CHOICES]


def _parse_json(value):
    """JSON 字符串 → 对象；已是对象/None 原样返回。"""
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _dump_json(value):
    """对象 → JSON 字符串；None 保留为 null。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class CompetitionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    status = serializers.ChoiceField(choices=_STATUS_CHOICES, default="ACTIVE")
    mapBackground = serializers.JSONField(allow_null=True, required=False)
    stockConfig = serializers.JSONField(allow_null=True, required=False)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Competition) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "status": instance.status,
            "mapBackground": _parse_json(instance.map_background),
            "stockConfig": instance.stock_config,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("比赛名称不能为空")
        return value

    def create(self, validated_data: dict) -> Competition:
        return Competition.objects.create(
            name=validated_data["name"],
            status=validated_data.get("status", "ACTIVE"),
            map_background=_dump_json(validated_data.get("mapBackground")),
            stock_config=validated_data.get("stockConfig"),
        )

    def update(self, instance: Competition, validated_data: dict) -> Competition:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "status" in validated_data:
            instance.status = validated_data["status"]
        if "mapBackground" in validated_data:
            instance.map_background = _dump_json(validated_data["mapBackground"])
        if "stockConfig" in validated_data:
            instance.stock_config = validated_data["stockConfig"]
        instance.save()
        return instance


class FiscalYearSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    competitionId = serializers.IntegerField(read_only=True)
    year = serializers.IntegerField()
    status = serializers.ChoiceField(
        choices=[c[0] for c in FiscalYear.STATUS_CHOICES], default="ACTIVE"
    )
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: FiscalYear) -> dict:
        return {
            "id": instance.id,
            "competitionId": instance.competition_id,
            "year": instance.year,
            "status": instance.status,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_year(self, value: int) -> int:
        if value is None:
            raise serializers.ValidationError("财年不能为空")
        return value
