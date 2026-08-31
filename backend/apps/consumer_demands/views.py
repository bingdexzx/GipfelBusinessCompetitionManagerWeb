"""消费者需求视图：对应原 NestJS ConsumerDemandController / ConsumerDemandService。

权限：读 consumer-demand:view，写 consumer-demand:edit。
路由由 backend.urls 以 path("api/", include("apps.consumer_demands.urls")) 引入。

前端契约（与 consumerDemandsApi 对齐）：
- GET    /api/consumer-demands        列表（按区域过滤，不分页，orderBy -updated_at，含 product）
- POST   /api/consumer-demands        创建（解析 productId → product_type）
- PATCH  /api/consumer-demands/:id    更新（productId 变更时重新解析 product_type）
- DELETE /api/consumer-demands/:id    删除
"""
from __future__ import annotations

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

_VIEW_PERM = "consumer-demand:view"
_EDIT_PERM = "consumer-demand:edit"
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


def _recompute_dependent_fields(demand_id: int) -> None:
    """消费者需求变更后重算依赖的产业字段（计算引擎待接入）。"""
    try:
        from apps.company_fields.calc import (
            recompute_consumer_demand_dependent_fields,
        )
    except ImportError:
        # TODO: 待 apps.company_fields.calc 实现后接入
        return
    try:
        recompute_consumer_demand_dependent_fields(demand_id)
    except Exception:  # noqa: BLE001 - 重算失败不阻断主流程
        pass


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
        serializer = ConsumerDemandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        demand = serializer.create(serializer.validated_data)
        emit_resource_changed(
            "consumer-demand", demand.id, demand.competition_id, "created"
        )
        _recompute_dependent_fields(demand.id)
        return Response(_serialize(demand))


class ItemView(APIView):
    """PATCH/DELETE /api/consumer-demands/:id —— 更新 + 删除。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def patch(self, request, pk):
        demand = _get_demand(pk, request)
        serializer = ConsumerDemandSerializer(demand, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.update(demand, serializer.validated_data)
        emit_resource_changed(
            "consumer-demand", demand.id, demand.competition_id, "updated"
        )
        _recompute_dependent_fields(demand.id)
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
        demand.delete()
        emit_resource_changed(
            "consumer-demand", demand_id, competition_id_final, "deleted"
        )
        _recompute_dependent_fields(demand_id)
        return Response({"ok": True})
