"""消费者需求视图。

权限：读 data:region:view，写 data:region:edit——消费者需求与区域总览卡片
同属「区域」数据，前端（区域总览页 / 仪表盘）统一按 data:region:* 闸门，
且 data:region:* 在各角色模板默认集中，避免非超管账号 403。

路由由 backend.urls 以 path("api/", include("apps.consumer_demands.urls")) 引入。

前端契约（与 consumerDemandsApi 对齐）：
- GET    /api/consumer-demands        列表（按区域过滤，不分页，orderBy -updated_at，含 product）
- POST   /api/consumer-demands        创建（解析 productId → product_type）
- PATCH  /api/consumer-demands/:id    更新（productId 变更时重新解析 product_type）
- DELETE /api/consumer-demands/:id    删除
"""
from __future__ import annotations

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import (
    PermissionsPermission,
    apply_competition_scope,
    require_permissions,
)
from apps.common.scope import assert_same_competition
from apps.realtime.emit import emit_resource_changed

from .models import ConsumerDemand
from .serializers import ConsumerDemandSerializer

logger = logging.getLogger(__name__)

_VIEW_PERM = "data:region:view"
_EDIT_PERM = "data:region:edit"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


def _serialize(demand: ConsumerDemand) -> dict:
    return ConsumerDemandSerializer(demand).data


def _get_demand(pk, request) -> ConsumerDemand:
    """取消费者需求并做比赛域隔离，越权视作不存在。"""
    try:
        demand = ConsumerDemand.objects.get(pk=pk)
    except ConsumerDemand.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(request.user, "role", None) != "SUPER_ADMIN":
        if demand.competition_id != getattr(request.user, "competition_id", None):
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return demand


def _recompute_dependent_fields(competition_id: int, regions: list[str]) -> None:
    """消费诉求变更后，触发受其影响公司的 calcGraph 重算。

    calcGraph 中 CONSUMER_DEMAND 节点按公司「所在地」字段值聚合消费诉求量
    （见 apps.company_fields.calc._consumer_demand_total）。因此，本函数需要
    找出 competition 内、所在地字段值对应的区域等于诉求 region 的所有公司，逐一调
    recompute_calc_fields 即可——未引用消费诉求的 calcGraph 在求值时自然短路。

    查找逻辑：
    1. 先通过 Region 表找到区域 ID，再找 region_id 匹配的公司
    2. 再找所在地产业字段值对应的区域在 regions 列表中的公司

    调用方负责：删除/修改 region 时同时把旧 region 传入，保证旧区域下的
    公司也能重算（避免陈旧值）。

    重算失败仅记日志，不阻断主流程——主请求已完成，消费诉求本身的数据
    写入是源头事实。
    """
    from apps.companies.models import Company, CompanyFieldValue
    from apps.company_fields.calc import recompute_calc_fields
    from apps.industry_types.models import IndustryField
    from apps.maps.models import MapNode
    from apps.regions.models import Region

    regions_clean = [r for r in (regions or []) if r]
    if not regions_clean:
        return

    company_ids = set()

    # 方式1：通过公司的 region_id 字段查找
    region_ids = list(
        Region.objects.filter(competition_id=competition_id, name__in=regions_clean)
        .values_list("id", flat=True)
    )
    if region_ids:
        company_ids.update(
            Company.objects.filter(
                competition_id=competition_id,
                region_id__in=region_ids,
                industry_type_id__isnull=False,
            ).values_list("id", flat=True)
        )

    # 方式2：通过公司的"所在地"产业字段值查找
    # 先找出所有地图节点名称对应的区域
    node_names_in_regions = list(
        MapNode.objects.filter(
            competition_id=competition_id,
            region__in=regions_clean
        ).values_list("name", flat=True)
    )

    if node_names_in_regions:
        # 找到所有产业类型中的"location"字段
        location_fields = IndustryField.objects.filter(
            field_key="location"
        ).values_list("id", "industry_type_id")

        for field_id, industry_type_id in location_fields:
            # 找到使用这些产业类型的公司
            company_ids_for_type = list(
                Company.objects.filter(
                    competition_id=competition_id,
                    industry_type_id=industry_type_id,
                ).values_list("id", flat=True)
            )
            # 检查这些公司的所在地字段值是否在目标区域的节点名称中
            cfvs = CompanyFieldValue.objects.filter(
                company_id__in=company_ids_for_type,
                industry_field_id=field_id,
                value__in=node_names_in_regions
            ).values_list("company_id", flat=True)
            company_ids.update(cfvs)

    for cid in company_ids:
        try:
            recompute_calc_fields(cid)
        except Exception:  # noqa: BLE001 - 重算失败不阻断主流程
            logger.warning(
                "[consumer-demands] recompute_calc_fields failed competition=%s company=%s",
                competition_id,
                cid,
                exc_info=True,
            )


class CollectionView(APIView):
    """GET/POST /api/consumer-demands —— 列表（按区域过滤）+ 创建。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        qs = apply_competition_scope(
            ConsumerDemand.objects.all(),
            request.user,
            request.query_params.get("competitionId"),
        )
        region = request.query_params.get("region")
        if region:
            qs = qs.filter(region=region)
        qs = qs.select_related("product")
        demands = [_serialize(d) for d in qs.order_by("-updated_at")]
        return Response(demands)

    @require_permissions(_EDIT_PERM)
    def post(self, request):
        from apps.common.guards import create_competition_id

        serializer = ConsumerDemandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # 非超管强制归属自身比赛，防止跨比赛写入
        data = dict(serializer.validated_data)
        data["competitionId"] = create_competition_id(request.user, data)
        demand = serializer.create(data)
        emit_resource_changed(
            "consumer-demand", demand.id, demand.competition_id, "created"
        )
        _recompute_dependent_fields(demand.competition_id, [demand.region])
        return Response(_serialize(demand))


class ItemView(APIView):
    """PATCH/DELETE /api/consumer-demands/:id —— 更新 + 删除。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def patch(self, request, pk):
        demand = _get_demand(pk, request)
        # 记录旧 region：patch 改了 region 时，旧区域下的公司也要重算
        old_region = demand.region
        serializer = ConsumerDemandSerializer(demand, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # 禁止跨比赛迁移：剔除 competitionId
        data = {
            k: v for k, v in serializer.validated_data.items()
            if k not in ("competitionId", "competition_id")
        }
        serializer.update(demand, data)
        emit_resource_changed(
            "consumer-demand", demand.id, demand.competition_id, "updated"
        )
        regions_to_recompute = sorted({old_region, demand.region})
        _recompute_dependent_fields(demand.competition_id, regions_to_recompute)
        return Response(_serialize(demand))

    @require_permissions(_EDIT_PERM)
    def delete(self, request, pk):
        demand = _get_demand(pk, request)
        raw = request.query_params.get("competitionId")
        try:
            competition_id = int(raw) if raw else None
        except (TypeError, ValueError):
            competition_id = None
        assert_same_competition(demand.competition_id, competition_id)
        demand_id = demand.id
        competition_id_final = demand.competition_id
        demand_region = demand.region
        demand.delete()
        emit_resource_changed(
            "consumer-demand", demand_id, competition_id_final, "deleted"
        )
        _recompute_dependent_fields(competition_id_final, [demand_region])
        return Response({"ok": True})
