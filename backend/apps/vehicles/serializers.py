"""载具序列化器：camelCase 对齐前端契约，含嵌套 include。

输出嵌套结构：
    { id, name, fuelId, fuelConsumptionPerKm, maxCargo, price, carbonEmission,
      competitionId, createdAt, updatedAt,
      fuel: { id, name, pricePerLiter, ... },
      vehiclePathTypes: [{ vehicleId, pathTypeId, pathType: { ... } }] }

创建/更新接收 vehiclePathTypes 数组，由视图在事务内全量替换。fuelId 创建时必填。
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models
from rest_framework import serializers

from .models import Vehicle
from apps.common.helpers import to_camel as _to_camel
from apps.common.helpers import instance_to_camel as _instance_to_camel


# ==================== 通用 camelCase 序列化 ====================



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
    # 油耗/载货是系数/容量，Float 足够；价格必须 Decimal。
    fuelConsumptionPerKm = serializers.FloatField(min_value=0)
    maxCargo = serializers.FloatField(min_value=0)
    price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0"))
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
