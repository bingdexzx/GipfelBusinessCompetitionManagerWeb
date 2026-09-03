"""产品序列化器：camelCase 对齐前端契约，含嵌套 include。

输出嵌套结构：
    { id, name, competitionId, createdAt, updatedAt,
      productParts: [{ productId, partId, ratio, part: { ... } }],
      techRequirements: [{ productId, techNodeId, techNode: { ... } }] }

创建/更新接收 productParts / techRequirements 数组，由视图在事务内全量替换。
"""
from __future__ import annotations

from django.db import models
from rest_framework import serializers

from .models import Product
from apps.common.helpers import to_camel as _to_camel
from apps.common.helpers import instance_to_camel as _instance_to_camel


# ==================== 通用 camelCase 序列化 ====================



def _serialize_product(instance: Product) -> dict:
    """构造单个产品的嵌套 include 输出。"""
    data = _instance_to_camel(instance)
    data["productParts"] = [
        {
            **_instance_to_camel(pp, include_id=False),
            "part": _instance_to_camel(pp.part),
        }
        for pp in instance.product_parts.all()
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
class ProductPartItemSerializer(serializers.Serializer):
    partId = serializers.IntegerField()
    ratio = serializers.FloatField(min_value=0)


class TechRequirementItemSerializer(serializers.Serializer):
    techNodeId = serializers.IntegerField()


# ==================== 产品序列化器 ====================
class ProductSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    competitionId = serializers.IntegerField()
    productParts = ProductPartItemSerializer(many=True, required=False)
    techRequirements = TechRequirementItemSerializer(many=True, required=False)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Product) -> dict:
        return _serialize_product(instance)

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("产品名称不能为空")
        return value
