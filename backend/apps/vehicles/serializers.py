"""载具序列化器：camelCase 对齐前端契约，含嵌套 include。

输出形如（对应 Prisma include { fuel: true,
vehiclePathTypes: { include: pathType } }）：
    { id, name, fuelId, fuelConsumptionPerKm, maxCargo, price, carbonEmission,
      competitionId, createdAt, updatedAt,
      fuel: { id, name, pricePerLiter, ... },
      vehiclePathTypes: [{ vehicleId, pathTypeId, pathType: { ... } }] }

创建/更新接收 vehiclePathTypes 数组，由视图在事务内全量替换。fuelId 创建时必填。
"""
from __future__ import annotations

from django.db import models
from rest_framework import serializers

from .models import Vehicle


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


def _serialize_vehicle(instance: Vehicle) -> dict:
    """构造单个载具的嵌套 include 输出。"""
    data = _instance_to_camel(instance)
    data["fuel"] = _instance_to_camel(instance.fuel)
    data["vehiclePathTypes"] = [
        {
            **_instance_to_camel(vpt, include_id=False),
            "pathType": _instance_to_camel(vpt.path_type),
        }
        for vpt in instance.vehicle_path_types.all()
    ]
    return data


# ==================== 嵌套数组项序列化器（仅用于输入校验） ====================
class VehiclePathTypeItemSerializer(serializers.Serializer):
    pathTypeId = serializers.IntegerField()


# ==================== 载具序列化器 ====================
class VehicleSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    fuelId = serializers.IntegerField()
    fuelConsumptionPerKm = serializers.FloatField(min_value=0)
    maxCargo = serializers.FloatField(min_value=0)
    price = serializers.FloatField(min_value=0)
    carbonEmission = serializers.FloatField(min_value=0)
    competitionId = serializers.IntegerField()
    vehiclePathTypes = VehiclePathTypeItemSerializer(many=True, required=False)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Vehicle) -> dict:
        return _serialize_vehicle(instance)

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("载具名称不能为空")
        return value
