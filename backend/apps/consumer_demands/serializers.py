"""消费者需求序列化器：camelCase 对齐前端契约。"""
from __future__ import annotations

from rest_framework import serializers

from apps.common.exceptions import BusinessError

from .models import ConsumerDemand


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


def _resolve_product(product_id):
    """按 productId 解析 Product；缺失则 404（与原 NestJS 一致）。"""
    if product_id is None:
        return None
    from apps.products.models import Product

    try:
        return Product.objects.get(pk=product_id)
    except Product.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)


class ConsumerDemandSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    competitionId = serializers.IntegerField()
    region = serializers.CharField(max_length=128, trim_whitespace=True)
    productId = serializers.IntegerField(required=False, allow_null=True)
    productType = serializers.CharField(read_only=True)
    quantity = serializers.IntegerField(default=0)
    note = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: ConsumerDemand) -> dict:
        product = None
        if instance.product_id is not None:
            p = instance.product  # 视图层 select_related 预取，无额外查询
            if p is not None:
                product = {"id": p.id, "name": p.name}
        return {
            "id": instance.id,
            "competitionId": instance.competition_id,
            "region": instance.region,
            "productId": instance.product_id,
            "productType": instance.product_type,
            "quantity": instance.quantity,
            "note": instance.note,
            "product": product,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_region(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("区域不能为空")
        return value

    def create(self, validated_data: dict) -> ConsumerDemand:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)
        product_id = validated_data.get("productId")
        product = _resolve_product(product_id)
        return ConsumerDemand.objects.create(
            competition_id=cid,
            region=validated_data["region"],
            product_id=product.id if product is not None else None,
            product_type=product.name if product is not None else "",
            quantity=validated_data.get("quantity", 0),
            note=validated_data.get("note"),
        )

    def update(self, instance: ConsumerDemand, validated_data: dict) -> ConsumerDemand:
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            _assert_competition_exists(cid)
            instance.competition_id = cid
        if "region" in validated_data:
            instance.region = validated_data["region"]
        if "productId" in validated_data:
            product = _resolve_product(validated_data["productId"])
            instance.product_id = product.id if product is not None else None
            instance.product_type = product.name if product is not None else ""
        if "quantity" in validated_data:
            instance.quantity = validated_data["quantity"]
        if "note" in validated_data:
            instance.note = validated_data["note"]
        instance.save()
        return instance
