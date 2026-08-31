"""科技树序列化器：camelCase 对齐前端契约。

list/detail 输出包含 prerequisites 嵌套（含 prerequisite 节点 name）。
create/update 接收 prerequisites:[{prerequisiteNodeId}]，在视图中事务替换。
"""
from __future__ import annotations

from rest_framework import serializers

from .models import TechNode, TechPrerequisite


class TechNodeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    description = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    tier = serializers.FloatField(default=0)
    researchCost = serializers.FloatField(default=0)
    competitionId = serializers.IntegerField()
    prerequisites = serializers.ListField(
        child=serializers.DictField(), required=False, allow_empty=True
    )
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def to_representation(self, instance: TechNode) -> dict:
        prereqs = []
        for tp in instance.prerequisites.select_related("prerequisite").all():
            pre = tp.prerequisite
            prereqs.append({
                "nodeId": instance.id,
                "prerequisiteNodeId": pre.id,
                "prerequisite": {"id": pre.id, "name": pre.name},
            })
        return {
            "id": instance.id,
            "name": instance.name,
            "description": instance.description,
            "tier": instance.tier,
            "researchCost": instance.research_cost,
            "competitionId": instance.competition_id,
            "prerequisites": prereqs,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def create(self, validated_data: dict) -> TechNode:
        prerequisites = validated_data.pop("prerequisites", None) or []
        node = TechNode.objects.create(
            name=validated_data["name"],
            description=validated_data.get("description"),
            tier=validated_data.get("tier", 0),
            research_cost=validated_data.get("researchCost", 0),
            competition_id=validated_data["competitionId"],
        )
        if prerequisites:
            for p in prerequisites:
                pid = p.get("prerequisiteNodeId")
                if pid:
                    TechPrerequisite.objects.create(node=node, prerequisite_id=pid)
        return node

    def update(self, instance: TechNode, validated_data: dict) -> TechNode:
        from django.db import transaction

        prerequisites = validated_data.pop("prerequisites", None)
        with transaction.atomic():
            if "name" in validated_data:
                instance.name = validated_data["name"]
            if "description" in validated_data:
                instance.description = validated_data["description"]
            if "tier" in validated_data:
                instance.tier = validated_data["tier"]
            if "researchCost" in validated_data:
                instance.research_cost = validated_data["researchCost"]
            instance.save()
            if prerequisites is not None:
                instance.prerequisites.all().delete()
                for p in prerequisites:
                    pid = p.get("prerequisiteNodeId")
                    if pid:
                        TechPrerequisite.objects.create(node=instance, prerequisite_id=pid)
        return instance
