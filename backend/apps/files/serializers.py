"""文件应用序列化器：地图背景变换参数校验。"""
from __future__ import annotations

from rest_framework import serializers


class MapBackgroundTransformSerializer(serializers.Serializer):
    x = serializers.FloatField()
    y = serializers.FloatField()
    scale = serializers.FloatField()
    competitionId = serializers.IntegerField(required=False, allow_null=True)
