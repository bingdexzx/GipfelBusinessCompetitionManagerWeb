"""通用 CRUD 基类：对应原 NestJS base-crud.service.ts。

为 materials/parts/products/infrastructures/fuels/vehicles/warehouses/
production-lines/tech-nodes 等 9 类基础数据提供统一 CRUD + 分页 + 比赛域隔离
+ 删除影响。

子类需声明：
- model：Django Model 类
- serializer_class：DRF Serializer
- view_permission：读权限 key（如 "data:material:view"）
- edit_permission：写权限 key（如 "data:material:edit"）
- unique_fields：唯一约束 camelCase 字段名列表（如 ["competitionId","name"]）
"""
from __future__ import annotations

from rest_framework import permissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import apply_competition_scope
from apps.common.pagination import paginated_response, parse_pagination
from apps.common.permissions import has_permission


class CrudPermission(permissions.BasePermission):
    """按 HTTP 方法读取 view_permission / edit_permission 并校验。"""

    def has_permission(self, request, view):
        view_perm = getattr(view, "view_permission", "") or ""
        edit_perm = getattr(view, "edit_permission", "") or ""
        if request.method == "GET":
            required = view_perm
        else:
            required = edit_perm
        if not required:
            return True
        user = request.user
        perms = user.permissions_list if hasattr(user, "permissions_list") else []
        if not has_permission(getattr(user, "role", None), perms, required):
            raise permissions.exceptions.PermissionDenied("没有权限执行此操作")
        return True


_PERM_CLASSES = (IsAuthenticated, CrudPermission)


# ==================== 公共混入 ====================
class CrudMixin:
    """通用 CRUD 逻辑混入。子类需声明类属性。"""

    model = None
    serializer_class = None
    view_permission: str = ""
    edit_permission: str = ""
    # 唯一 camelCase 字段组合，用于 create/update 冲突检测
    unique_fields: list[str] = []
    order_by: str = "-updated_at"

    # ---------- 查询 ----------
    def get_queryset(self, request):
        qs = self.model.objects.all()
        return apply_competition_scope(qs, request.user, request.query_params.get("competitionId"))

    def filter_queryset(self, qs, params):
        return qs

    def serialize(self, instance, many=False):
        return self.serializer_class(instance, many=many).data

    # ---------- 比赛域隔离取对象 ----------
    def _get_object(self, pk, request):
        try:
            instance = self.model.objects.get(pk=pk)
        except self.model.DoesNotExist:
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            cid = getattr(instance, "competition_id", None)
            user_cid = getattr(request.user, "competition_id", None)
            if cid is not None and cid != user_cid:
                raise BusinessError("请求的资源不存在", code=404, status_code=404)
        return instance

    # ---------- 冲突检测 ----------
    _CAMEL_TO_SNAKE = {
        "competitionId": "competition_id",
        "name": "name",
        "code": "code",
        "key": "key",
    }

    def _check_conflict(self, data: dict, exclude_id=None):
        if not self.unique_fields:
            return
        flt = {}
        for f in self.unique_fields:
            snake = self._CAMEL_TO_SNAKE.get(f, f.lower())
            if f in data and data[f] is not None:
                flt[snake] = data[f]
        if not flt:
            return
        qs = self.model.objects.filter(**flt)
        if exclude_id is not None:
            qs = qs.exclude(pk=exclude_id)
        if qs.exists():
            raise BusinessError("名称已存在", code=409, status_code=409)

    # ---------- 删除影响 ----------
    def get_delete_impact(self, instance) -> dict:
        return {"name": str(instance), "children": []}


# ==================== 视图基类 ====================
class CrudListView(CrudMixin, APIView):
    permission_classes = _PERM_CLASSES

    def get(self, request):
        qs = self.get_queryset(request)
        qs = self.filter_queryset(qs, request.query_params)
        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = self.serialize(qs.order_by(self.order_by)[skip : skip + page_size], many=True)
        return Response(paginated_response(items, total, page, page_size))


class CrudCreateView(CrudMixin, APIView):
    permission_classes = _PERM_CLASSES

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._check_conflict(serializer.validated_data)
        instance = serializer.create(serializer.validated_data)
        return Response(self.serialize(instance))


class CrudDetailView(CrudMixin, APIView):
    permission_classes = _PERM_CLASSES

    def get(self, request, pk):
        instance = self._get_object(pk, request)
        return Response(self.serialize(instance))


class CrudUpdateView(CrudMixin, APIView):
    permission_classes = _PERM_CLASSES

    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    def _update(self, request, pk, partial):
        instance = self._get_object(pk, request)
        serializer = self.serializer_class(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self._check_conflict(serializer.validated_data, exclude_id=pk)
        serializer.update(instance, serializer.validated_data)
        return Response(self.serialize(instance))


class CrudDeleteView(CrudMixin, APIView):
    permission_classes = _PERM_CLASSES

    def delete(self, request, pk):
        instance = self._get_object(pk, request)
        instance.delete()
        return Response({"ok": True})


class CrudImpactView(CrudMixin, APIView):
    permission_classes = _PERM_CLASSES

    def get(self, request, pk):
        instance = self._get_object(pk, request)
        return Response(self.get_delete_impact(instance))


# ==================== 组合视图 ====================
def make_collection_view(list_view=CrudListView, create_view=CrudCreateView):
    """组合 list + create 视图（GET/POST /resource）。"""
    return type("CollectionAPIView", (list_view, create_view), {})


def make_item_view(detail_view=CrudDetailView, update_view=CrudUpdateView, delete_view=CrudDeleteView):
    """组合 detail + update + delete 视图（GET/PUT/PATCH/DELETE /resource/:id）。"""
    return type("ItemAPIView", (detail_view, update_view, delete_view), {})


def make_impact_item_view(impact_view=CrudImpactView):
    """impact 视图（GET /resource/:id/impact）。"""
    return impact_view


# ==================== 路由生成 ====================
def crud_urlpatterns(
    resource: str,
    collection_view,
    item_view,
    impact_view=None,
):
    """生成标准 CRUD 路由。

    - GET/POST  /<resource>
    - GET/PUT/PATCH/DELETE /<resource>/<int:pk>
    - GET /<resource>/<int:pk>/impact  （可选）
    """
    from django.urls import path

    patterns = [
        path(resource, collection_view.as_view(), name=f"{resource}-collection"),
        path(f"{resource}/<int:pk>", item_view.as_view(), name=f"{resource}-item"),
    ]
    if impact_view is not None:
        patterns.append(
            path(f"{resource}/<int:pk>/impact", impact_view.as_view(), name=f"{resource}-impact")
        )
    return patterns
