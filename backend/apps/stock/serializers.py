"""股票系统序列化器：camelCase 对齐前端契约。

Stock 创建时由 compute_init_price 自动算初始价；PE 联动/随机模式由
compute_pb_data 解析。账户/订单/持仓的创建逻辑含请求上下文，由视图层
注入；本模块负责字段校验与基础序列化。
"""
from __future__ import annotations

import math

from rest_framework import serializers

from .models import Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder

# 延迟导入 engine 以避免循环依赖（engine 内部延迟导入 models）


# ==================== PE 联动 / 随机解析 ====================
def _random_pb() -> float:
    import random

    return round(random.random() * 20 * 100) / 100


def _clamp_pb(v: float) -> float:
    if not math.isfinite(v):
        return _random_pb()
    c = min(20, max(0, v))
    return round(c * 100) / 100


def compute_pb_data(item: Stock | None, dto: dict) -> dict:
    """解析股票的有效 PE 与联动字段。

    - 联动模式（pbCompanyId + pbFieldId 同时非空）：PE 取该公司产业字段实时值
    - 随机模式（二者均空）：PE 取自 pbRandom（dto 优先，其次 dto.industryPE 作种子）

    返回 {industryPE, pbCompanyId, pbFieldId, pbRandom}
    """
    from apps.common.exceptions import BusinessError
    from apps.companies.models import Company
    from apps.industry_types.models import IndustryField

    from .engine import resolve_field_value_or_default

    pb_company_id = dto.get("pbCompanyId") if dto.get("pbCompanyId") is not None else (
        item.pb_company_id if item is not None else None
    )
    pb_field_id = dto.get("pbFieldId") if dto.get("pbFieldId") is not None else (
        item.pb_field_id if item is not None else None
    )

    if (pb_company_id and not pb_field_id) or (not pb_company_id and pb_field_id):
        raise BusinessError(
            "PE 联动需同时选择公司与绑定字段，或二者均不填（随机模式）",
            code=400, status_code=400,
        )

    pb_random = item.pb_random if (item is not None and item.pb_random is not None) else None
    industry_pe: float

    if pb_company_id and pb_field_id:
        company = Company.objects.filter(pk=pb_company_id).first()
        field = IndustryField.objects.filter(pk=pb_field_id).first()
        if not company or not field or company.industry_type_id != field.industry_type_id:
            raise BusinessError(
                "绑定的产业字段不属于该公司所属产业类型",
                code=400, status_code=400,
            )
        v = resolve_field_value_or_default(pb_company_id, pb_field_id)
        fallback = item.industry_pe if item is not None else _random_pb()
        industry_pe = v if (v is not None and v > 0) else fallback
        pb_random = None
    else:
        seed: float | None = None
        if dto.get("pbRandom") is not None:
            seed = dto["pbRandom"]
        elif dto.get("industryPE") is not None:
            seed = dto["industryPE"]
        elif pb_random is None:
            seed = _random_pb()
        pb_random = _clamp_pb(seed) if seed is not None else _random_pb()
        industry_pe = pb_random

    return {
        "industryPE": industry_pe,
        "pbCompanyId": pb_company_id,
        "pbFieldId": pb_field_id,
        "pbRandom": pb_random,
    }


# ==================== 股票 ====================
class StockSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(max_length=64, trim_whitespace=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    totalShares = serializers.FloatField(min_value=0)
    initNetProfit = serializers.FloatField(min_value=0)
    industryPE = serializers.FloatField(min_value=0, required=False)
    currentCarbon = serializers.FloatField()
    industryAvgCarbon = serializers.FloatField()
    happiness = serializers.FloatField(min_value=0)
    carbonFieldRef = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    happinessFieldRef = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    industryAvgCarbonRefs = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    pbCompanyId = serializers.IntegerField(required=False, allow_null=True)
    pbFieldId = serializers.IntegerField(required=False, allow_null=True)
    pbRandom = serializers.FloatField(min_value=0, max_value=20, required=False, allow_null=True)
    companyId = serializers.IntegerField(required=False, allow_null=True)
    competitionId = serializers.IntegerField()
    initPrice = serializers.FloatField(read_only=True)
    currentPrice = serializers.FloatField(read_only=True)
    round = serializers.IntegerField(read_only=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def validate_code(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("股票代码不能为空")
        return value

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("股票名称不能为空")
        return value

    def create(self, validated_data: dict) -> Stock:
        from .engine import compute_init_price

        cid = validated_data["competitionId"]
        # 唯一性校验
        if Stock.objects.filter(competition_id=cid, code=validated_data["code"]).exists():
            from apps.common.exceptions import BusinessError

            raise BusinessError("股票代码已存在", code=409, status_code=409)

        pb = compute_pb_data(None, validated_data)
        init_price = compute_init_price(
            validated_data["initNetProfit"], validated_data["totalShares"], pb["industryPE"]
        )
        # 边界校验
        from apps.common.exceptions import BusinessError

        if not (validated_data["totalShares"] > 0):
            raise BusinessError("总股本必须大于 0", code=400, status_code=400)
        if not (validated_data["initNetProfit"] > 0):
            raise BusinessError("初始净利润必须大于 0", code=400, status_code=400)
        if not (pb["industryPE"] > 0):
            raise BusinessError(
                "有效行业 PE 必须大于 0（联动模式字段值或随机源须为正）",
                code=400, status_code=400,
            )
        if not (init_price > 0 and init_price <= 10000):
            raise BusinessError(
                f"初始价 {init_price} 异常，请检查净利润/股本/PE 量纲（应 ∈ (0, 10000]）",
                code=400, status_code=400,
            )

        return Stock.objects.create(
            code=validated_data["code"],
            name=validated_data["name"],
            total_shares=validated_data["totalShares"],
            init_net_profit=validated_data["initNetProfit"],
            industry_pe=pb["industryPE"],
            current_carbon=validated_data["currentCarbon"],
            industry_avg_carbon=validated_data["industryAvgCarbon"],
            happiness=validated_data["happiness"],
            carbon_field_ref=validated_data.get("carbonFieldRef") or None,
            happiness_field_ref=validated_data.get("happinessFieldRef") or None,
            industry_avg_carbon_refs=validated_data.get("industryAvgCarbonRefs") or None,
            pb_company_id=pb["pbCompanyId"],
            pb_field_id=pb["pbFieldId"],
            pb_random=pb["pbRandom"],
            init_price=init_price,
            current_price=init_price,
            round=0,
            company_id=validated_data.get("companyId"),
            competition_id=cid,
        )

    def update(self, instance: Stock, validated_data: dict) -> Stock:
        from .engine import compute_init_price

        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "companyId" in validated_data:
            instance.company_id = validated_data["companyId"]
        if "currentCarbon" in validated_data:
            instance.current_carbon = validated_data["currentCarbon"]
        if "industryAvgCarbon" in validated_data:
            instance.industry_avg_carbon = validated_data["industryAvgCarbon"]
        if "happiness" in validated_data:
            instance.happiness = validated_data["happiness"]
        if "carbonFieldRef" in validated_data:
            instance.carbon_field_ref = validated_data.get("carbonFieldRef") or None
        if "happinessFieldRef" in validated_data:
            instance.happiness_field_ref = validated_data.get("happinessFieldRef") or None
        if "industryAvgCarbonRefs" in validated_data:
            instance.industry_avg_carbon_refs = validated_data.get("industryAvgCarbonRefs") or None

        # PE 联动 / 随机
        pb_changed = (
            "pbCompanyId" in validated_data
            or "pbFieldId" in validated_data
            or "pbRandom" in validated_data
        )
        effective_pe = instance.industry_pe
        if pb_changed:
            pb = compute_pb_data(instance, validated_data)
            instance.pb_company_id = pb["pbCompanyId"]
            instance.pb_field_id = pb["pbFieldId"]
            instance.pb_random = pb["pbRandom"]
            instance.industry_pe = pb["industryPE"]
            effective_pe = pb["industryPE"]

        # 修改股本 / 净利润会重算初始价
        if "totalShares" in validated_data or "initNetProfit" in validated_data:
            total_shares = validated_data.get("totalShares", instance.total_shares)
            init_net_profit = validated_data.get("initNetProfit", instance.init_net_profit)
            instance.init_price = compute_init_price(init_net_profit, total_shares, effective_pe)
        if "totalShares" in validated_data:
            instance.total_shares = validated_data["totalShares"]
        if "initNetProfit" in validated_data:
            instance.init_net_profit = validated_data["initNetProfit"]

        instance.save()
        return instance


# ==================== 资金账户 ====================
class StockFundsAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    ownerType = serializers.ChoiceField(choices=["COMPANY", "USER"])
    companyId = serializers.IntegerField(required=False, allow_null=True)
    userId = serializers.IntegerField(required=False, allow_null=True)
    cashBalance = serializers.FloatField(min_value=0, required=False)
    bindFieldId = serializers.IntegerField(required=False, allow_null=True)
    competitionId = serializers.IntegerField()
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("账户名不能为空")
        return value

    def to_representation(self, instance: StockFundsAccount) -> dict:
        return {
            "id": instance.id,
            "name": instance.name,
            "ownerType": instance.owner_type,
            "companyId": instance.company_id,
            "userId": instance.user_id,
            "cashBalance": instance.cash_balance,
            "bindFieldId": instance.bind_field_id,
            "competitionId": instance.competition_id,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }


# ==================== 订单 ====================
class CreateOrderSerializer(serializers.Serializer):
    stockId = serializers.IntegerField()
    fundsAccountId = serializers.IntegerField()
    side = serializers.ChoiceField(choices=["BUY", "SELL"])
    price = serializers.FloatField(min_value=0.0001)
    quantity = serializers.FloatField(min_value=0.0001)
    competitionId = serializers.IntegerField()


# ==================== 推进轮次 ====================
class MarketMakerConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    spreadPct = serializers.FloatField(min_value=0.1, max_value=20, required=False)
    levels = serializers.IntegerField(min_value=1, max_value=10, required=False)
    baseQuantity = serializers.IntegerField(min_value=100, max_value=100000, required=False)


class StockConfigSerializer(serializers.Serializer):
    limitPct = serializers.FloatField(min_value=0.01, max_value=0.5, required=False)
    maxMovePct = serializers.FloatField(min_value=0.001, max_value=0.2, required=False)
    happinessImpact = serializers.FloatField(min_value=0, max_value=1, required=False)
    carbonImpact = serializers.FloatField(min_value=0, max_value=1, required=False)
    mmDepthPct = serializers.FloatField(min_value=0, max_value=0.1, required=False)
    mmMinQty = serializers.IntegerField(min_value=0, max_value=1_000_000, required=False)
    mmMaxQty = serializers.IntegerField(min_value=0, max_value=10_000_000, required=False)
    mmSpreadPct = serializers.FloatField(min_value=0, max_value=0.2, required=False)
    interventionMode = serializers.ChoiceField(
        choices=["regression", "expand-limit"], required=False
    )
    regressionPct = serializers.FloatField(min_value=0, max_value=0.2, required=False)
    tradePriceWeight = serializers.FloatField(min_value=0, max_value=1, required=False)


class AdvanceRoundSerializer(serializers.Serializer):
    stockIds = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )
    marketMaker = MarketMakerConfigSerializer(required=False)
    stockConfig = StockConfigSerializer(required=False)
