"""零件视图：对应原 NestJS PartController（/api/parts）。

权限：data:part:view / data:part:edit。比赛域隔离由 base_crud + _get_object 保证。

列表/详情带嵌套 include（partMaterials.material、techRequirements.techNode）。
创建/更新在事务内全量替换嵌套关联（delete old + create new），与原 NestJS
part.service.ts 的 $transaction 逻辑一致。
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

from .models import Part, PartMaterial, PartTechRequirement
from .serializers import PartSerializer, _serialize_part

_VIEW_PERMISSION = "data:part:view"
_EDIT_PERMISSION = "data:part:edit"
_UNIQUE_FIELDS = ["competitionId", "name"]
_PREFETCH = ("part_materials__material", "tech_requirements__tech_node")


def _name_conflict(competition_id, name, exclude_id=None) -> None:
    """比赛域内名称唯一冲突检测（对应原 ConflictException）。"""
    if not name:
        return
    qs = Part.objects.filter(competition_id=competition_id, name=name)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise BusinessError("零件名称已存在", code=409, status_code=409)


def _replace_relations(instance: Part, data: dict) -> None:
    """按提交的 partMaterials / techRequirements 全量替换（须在事务内调用）。"""
    if "partMaterials" in data:
        instance.part_materials.all().delete()
        for pm in data["partMaterials"]:
            PartMaterial.objects.create(
                part=instance,
                material_id=pm["materialId"],
                ratio=pm["ratio"],
            )
    if "techRequirements" in data:
        instance.tech_requirements.all().delete()
        for tr in data["techRequirements"]:
            PartTechRequirement.objects.create(
                part=instance,
                tech_node_id=tr["techNodeId"],
            )


class _PartBase:
    """零件视图共享配置与通用方法。"""

    model = Part
    serializer_class = PartSerializer
    view_permission = _VIEW_PERMISSION
    edit_permission = _EDIT_PERMISSION
    unique_fields = _UNIQUE_FIELDS

    def serialize(self, instance, many=False):
        return [_serialize_part(x) for x in instance] if many else _serialize_part(instance)

    @staticmethod
    def _prefetch(qs):
        return qs.prefetch_related(*_PREFETCH)

    @classmethod
    def _fetch_one(cls, pk):
        return cls._prefetch(Part.objects).get(pk=pk)

    def _get_object(self, pk, request, prefetch=False):
        qs = self._prefetch(Part.objects) if prefetch else Part.objects
        try:
            instance = qs.get(pk=pk)
        except Part.DoesNotExist:
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            cid = instance.competition_id
            user_cid = getattr(request.user, "competition_id", None)
            if cid is not None and cid != user_cid:
                raise BusinessError("请求的资源不存在", code=404, status_code=404)
        return instance


class PartListView(_PartBase, CrudListView):
    def get_queryset(self, request):
        return self._prefetch(super().get_queryset(request))


class PartCreateView(_PartBase, CrudCreateView):
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _name_conflict(data["competitionId"], data["name"])
        with transaction.atomic():
            instance = Part.objects.create(
                name=data["name"],
                competition_id=data["competitionId"],
            )
            _replace_relations(instance, data)
        return Response(self.serialize(self._fetch_one(instance.pk)))


class PartDetailView(_PartBase, CrudDetailView):
    def get(self, request, pk):
        instance = self._get_object(pk, request, prefetch=True)
        return Response(self.serialize(instance))


class PartUpdateView(_PartBase, CrudUpdateView):
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
            if "name" in data:
                instance.name = data["name"]
            if "competitionId" in data:
                instance.competition_id = data["competitionId"]
            instance.save()
            _replace_relations(instance, data)
        return Response(self.serialize(self._fetch_one(pk)))


class PartDeleteView(_PartBase, CrudDeleteView):
    """删除零件：级联删除其配比/科技需求关联（CASCADE）。"""


class PartImpactView(_PartBase, CrudImpactView):
    def get_delete_impact(self, instance: Part) -> dict:
        children = []
        c1 = PartMaterial.objects.filter(part_id=instance.id).count()
        if c1:
            children.append({"label": "原料配比关系", "count": c1})
        # ProductPart 属于 products 应用，运行时（请求期）必然已注册，延迟导入避免循环依赖。
        from apps.products.models import ProductPart

        c2 = ProductPart.objects.filter(part_id=instance.id).count()
        if c2:
            children.append({"label": "作为组件被产品引用", "count": c2})
        c3 = PartTechRequirement.objects.filter(part_id=instance.id).count()
        if c3:
            children.append({"label": "科技树需求关联", "count": c3})
        return {"name": instance.name, "children": children}


# ==================== 路由组合视图 ====================
CollectionAPIView = make_collection_view(PartListView, PartCreateView)
ItemAPIView = make_item_view(PartDetailView, PartUpdateView, PartDeleteView)
ImpactAPIView = make_impact_item_view(PartImpactView)
