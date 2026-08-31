"""零件序列化器：camelCase 对齐前端契约，含嵌套 include。

输出形如（对应 Prisma include { partMaterials: { include: material },
techRequirements: { include: techNode } }）：
    { id, name, competitionId, createdAt, updatedAt,
      partMaterials: [{ partId, materialId, ratio, material: { ... } }],
      techRequirements: [{ partId, techNodeId, techNode: { ... } }] }

创建/更新接收 partMaterials / techRequirements 数组，由视图在事务内全量替换。
"""
from __future__ import annotations

from django.db import models
from rest_framework import serializers

from .models import Part


# ==================== 通用 camelCase 序列化 ====================
def _to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _instance_to_camel(instance, include_id: bool = True) -> dict | None:
    """把模型实例的所有具体字段序列化为 camelCase dict。

    - 外键字段输出为 <stem>Id（取 _id 列值，与 Prisma include 一致）
    - 时间字段输出 ISO 字符串
    - include_id=False 时省略自增 id（用于复合关联表，Prisma 无此列）
    """
    if instance is None:
        return None
    data = {}
    for f in instance._meta.concrete_fields:
        if not include_id and f.name == "id":
            continue
        if isinstance(f, (models.ForeignKey, models.OneToOneField)):
            data[_to_camel(f.name) + "Id"] = getattr(instance, f.attname)
        elif isinstance(f, (models.DateTimeField, models.DateField)):
            v = getattr(instance, f.name)
            data[_to_camel(f.name)] = v.isoformat() if v else None
        else:
            data[_to_camel(f.name)] = getattr(instance, f.name)
    return data


def _serialize_part(instance: Part) -> dict:
    """构造单个零件的嵌套 include 输出。"""
    data = _instance_to_camel(instance)
    data["partMaterials"] = [
        {
            **_instance_to_camel(pm, include_id=False),
            "material": _instance_to_camel(pm.material),
        }
        for pm in instance.part_materials.all()
    ]
    data["techRequirements"] = [
        {
            **_instance_to_camel(tr, include_id=False),
            "techNode": _instance_to_camel(tr.tech_node),
        }
        for tr in instance.tech_requirements.all()
    ]
    return data


# ==================== 嵌套数组项序列化器（仅用于输入校验） ====================
class PartMaterialItemSerializer(serializers.Serializer):
    materialId = serializers.IntegerField()
    ratio = serializers.FloatField(min_value=0)


class TechRequirementItemSerializer(serializers.Serializer):
    techNodeId = serializers.IntegerField()


# ==================== 零件序列化器 ====================
class PartSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    competitionId = serializers.IntegerField()
    partMaterials = PartMaterialItemSerializer(many=True, required=False)
    techRequirements = TechRequirementItemSerializer(many=True, required=False)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Part) -> dict:
        return _serialize_part(instance)

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("零件名称不能为空")
        return value
