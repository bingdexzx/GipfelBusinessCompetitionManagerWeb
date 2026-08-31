"""载具视图：对应原 NestJS VehicleController（/api/vehicles）。

权限：data:vehicle:view / data:vehicle:edit。比赛域隔离由 base_crud + _get_object 保证。

列表/详情带嵌套 include（fuel、vehiclePathTypes.pathType）。
创建/更新在事务内全量替换 vehiclePathTypes（delete old + create new），与原 NestJS
vehicle.service.ts 的 $transaction 逻辑一致。fuelId 创建时必填（serializer 约束）。
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.response import Response

from apps.common.base_crud import (
    CrudCreateView,
    CrudDeleteView,
    CrudDetailView,
    CrudImpactView,
    CrudListView,
    CrudUpdateView,
    make_collection_view,
    make_impact_item_view,
    make_item_view,
)
from apps.common.exceptions import BusinessError

from .models import Vehicle, VehiclePathType
from .serializers import VehicleSerializer, _serialize_vehicle

_VIEW_PERMISSION = "data:vehicle:view"
_EDIT_PERMISSION = "data:vehicle:edit"
_UNIQUE_FIELDS = ["competitionId", "name"]
# fuel 为正向外键（select_related 单查询），vehicle_path_types 为反向多端
_PREFETCH_RELATED = ("vehicle_path_types__path_type",)
_SELECT_RELATED = ("fuel",)

# 主表字段映射：camelCase 输入 -> snake_case 模型字段
_FIELD_MAP = {
    "name": "name",
    "fuelId": "fuel_id",
    "fuelConsumptionPerKm": "fuel_consumption_per_km",
    "maxCargo": "max_cargo",
    "price": "price",
    "carbonEmission": "carbon_emission",
    "competitionId": "competition_id",
}


def _name_conflict(competition_id, name, exclude_id=None) -> None:
    """比赛域内名称唯一冲突检测（对应原 ConflictException）。"""
    if not name:
        return
    qs = Vehicle.objects.filter(competition_id=competition_id, name=name)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise BusinessError("载具名称已存在", code=409, status_code=409)


def _replace_relations(instance: Vehicle, data: dict) -> None:
    """按提交的 vehiclePathTypes 全量替换（须在事务内调用）。"""
    if "vehiclePathTypes" in data:
        instance.vehicle_path_types.all().delete()
        for vpt in data["vehiclePathTypes"]:
            VehiclePathType.objects.create(
                vehicle=instance,
                path_type_id=vpt["pathTypeId"],
            )


class _VehicleBase:
    """载具视图共享配置与通用方法。"""

    model = Vehicle
    serializer_class = VehicleSerializer
    view_permission = _VIEW_PERMISSION
    edit_permission = _EDIT_PERMISSION
    unique_fields = _UNIQUE_FIELDS

    def serialize(self, instance, many=False):
        return (
            [_serialize_vehicle(x) for x in instance] if many else _serialize_vehicle(instance)
        )

    @staticmethod
    def _prefetch(qs):
        return qs.select_related(*_SELECT_RELATED).prefetch_related(*_PREFETCH_RELATED)

    @classmethod
    def _fetch_one(cls, pk):
        return cls._prefetch(Vehicle.objects).get(pk=pk)

    def _get_object(self, pk, request, prefetch=False):
        qs = self._prefetch(Vehicle.objects) if prefetch else Vehicle.objects
        try:
            instance = qs.get(pk=pk)
        except Vehicle.DoesNotExist:
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            cid = instance.competition_id
            user_cid = getattr(request.user, "competition_id", None)
            if cid is not None and cid != user_cid:
                raise BusinessError("请求的资源不存在", code=404, status_code=404)
        return instance


class VehicleListView(_VehicleBase, CrudListView):
    def get_queryset(self, request):
        return self._prefetch(super().get_queryset(request))


class VehicleCreateView(_VehicleBase, CrudCreateView):
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _name_conflict(data["competitionId"], data["name"])
        with transaction.atomic():
            instance = Vehicle.objects.create(
                name=data["name"],
                fuel_id=data["fuelId"],
                fuel_consumption_per_km=data["fuelConsumptionPerKm"],
                max_cargo=data["maxCargo"],
                price=data["price"],
                carbon_emission=data["carbonEmission"],
                competition_id=data["competitionId"],
            )
            _replace_relations(instance, data)
        return Response(self.serialize(self._fetch_one(instance.pk)))


class VehicleDetailView(_VehicleBase, CrudDetailView):
    def get(self, request, pk):
        instance = self._get_object(pk, request, prefetch=True)
        return Response(self.serialize(instance))


class VehicleUpdateView(_VehicleBase, CrudUpdateView):
    def _update(self, request, pk, partial):
        instance = self._get_object(pk, request, prefetch=False)
        serializer = self.serializer_class(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "name" in data:
            _name_conflict(
                data.get("competitionId", instance.competition_id),
                data["name"],
                exclude_id=pk,
            )
        with transaction.atomic():
            for camel, snake in _FIELD_MAP.items():
                if camel in data:
                    setattr(instance, snake, data[camel])
            instance.save()
            _replace_relations(instance, data)
        return Response(self.serialize(self._fetch_one(pk)))


class VehicleDeleteView(_VehicleBase, CrudDeleteView):
    """删除载具：级联删除其通行路径类型关联（CASCADE）。fuel 受 PROTECT 保护，不在此处理。"""


class VehicleImpactView(_VehicleBase, CrudImpactView):
    def get_delete_impact(self, instance: Vehicle) -> dict:
        children = []
        c1 = VehiclePathType.objects.filter(vehicle_id=instance.id).count()
        if c1:
            children.append({"label": "支持的路径类型", "count": c1})
        return {"name": instance.name, "children": children}


# ==================== 路由组合视图 ====================
CollectionAPIView = make_collection_view(VehicleListView, VehicleCreateView)
ItemAPIView = make_item_view(
    VehicleDetailView, VehicleUpdateView, VehicleDeleteView
)
ImpactAPIView = make_impact_item_view(VehicleImpactView)
