"""地图序列化器：camelCase 对齐前端契约。

MapNode 输出包含 nodeType 嵌套；MapEdge 输出包含 fromNode/toNode/pathType 嵌套。
"""
from __future__ import annotations

from rest_framework import serializers

from .models import MapEdge, MapNode, MapNodeType, PathType


class MapNodeTypeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    description = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    color = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: MapNodeType) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "description": instance.description,
            "color": instance.color,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def create(self, validated_data: dict) -> MapNodeType:
        return MapNodeType.objects.create(
            name=validated_data["name"],
            description=validated_data.get("description"),
            color=validated_data.get("color"),
            competition_id=validated_data["competitionId"],
        )

    def update(self, instance: MapNodeType, validated_data: dict) -> MapNodeType:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "description" in validated_data:
            instance.description = validated_data["description"]
        if "color" in validated_data:
            instance.color = validated_data["color"]
        instance.save()
        return instance


class PathTypeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    description = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    color = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: PathType) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "description": instance.description,
            "color": instance.color,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def create(self, validated_data: dict) -> PathType:
        return PathType.objects.create(
            name=validated_data["name"],
            description=validated_data.get("description"),
            color=validated_data.get("color"),
            competition_id=validated_data["competitionId"],
        )

    def update(self, instance: PathType, validated_data: dict) -> PathType:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "description" in validated_data:
            instance.description = validated_data["description"]
        if "color" in validated_data:
            instance.color = validated_data["color"]
        instance.save()
        return instance


class MapNodeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    region = serializers.CharField(max_length=128, default="")
    nodeTypeId = serializers.IntegerField()
    x = serializers.FloatField(default=0)
    y = serializers.FloatField(default=0)
    competitionId = serializers.IntegerField()
    nodeType = serializers.DictField(read_only=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: MapNode) -> dict:
        nt = instance.node_type
        return {
            "id": instance.id,
            "name": instance.name,
            "region": instance.region,
            "nodeTypeId": instance.node_type_id,
            "x": instance.x,
            "y": instance.y,
            "competitionId": instance.competition_id,
            "nodeType": {
                "id": nt.id,
                "name": nt.name,
                "description": nt.description,
                "color": nt.color,
            }
            if nt
            else None,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def create(self, validated_data: dict) -> MapNode:
        return MapNode.objects.create(
            name=validated_data["name"],
            region=validated_data.get("region", ""),
            node_type_id=validated_data["nodeTypeId"],
            x=validated_data.get("x", 0),
            y=validated_data.get("y", 0),
            competition_id=validated_data["competitionId"],
        )

    def update(self, instance: MapNode, validated_data: dict) -> MapNode:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "region" in validated_data:
            instance.region = validated_data["region"]
        if "nodeTypeId" in validated_data:
            instance.node_type_id = validated_data["nodeTypeId"]
        if "x" in validated_data:
            instance.x = validated_data["x"]
        if "y" in validated_data:
            instance.y = validated_data["y"]
        instance.save()
        return instance


class MapEdgeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    fromNodeId = serializers.IntegerField()
    toNodeId = serializers.IntegerField()
    distance = serializers.FloatField(default=0)
    pathTypeId = serializers.IntegerField()
    competitionId = serializers.IntegerField()
    fromNode = serializers.DictField(read_only=True)
    toNode = serializers.DictField(read_only=True)
    pathType = serializers.DictField(read_only=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: MapEdge) -> dict:
        fn = instance.from_node
        tn = instance.to_node
        pt = instance.path_type
        return {
            "id": instance.id,
            "fromNodeId": instance.from_node_id,
            "toNodeId": instance.to_node_id,
            "distance": instance.distance,
            "pathTypeId": instance.path_type_id,
            "competitionId": instance.competition_id,
            "fromNode": {"id": fn.id, "name": fn.name} if fn else None,
            "toNode": {"id": tn.id, "name": tn.name} if tn else None,
            "pathType": {"id": pt.id, "name": pt.name} if pt else None,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def create(self, validated_data: dict) -> MapEdge:
        from apps.common.exceptions import BusinessError

        from_id = validated_data["fromNodeId"]
        to_id = validated_data["toNodeId"]
        # 规范化：from < to，保证唯一约束
        fid, tid = (from_id, to_id) if from_id < to_id else (to_id, from_id)
        if MapEdge.objects.filter(from_node_id=fid, to_node_id=tid).exists():
            raise BusinessError("这两个节点之间已存在路径", code=409, status_code=409)
        return MapEdge.objects.create(
            from_node_id=fid,
            to_node_id=tid,
            distance=validated_data.get("distance", 0),
            path_type_id=validated_data["pathTypeId"],
            competition_id=validated_data["competitionId"],
        )

    def update(self, instance: MapEdge, validated_data: dict) -> MapEdge:
        if "distance" in validated_data:
            instance.distance = validated_data["distance"]
        if "pathTypeId" in validated_data:
            instance.path_type_id = validated_data["pathTypeId"]
        instance.save()
        return instance
