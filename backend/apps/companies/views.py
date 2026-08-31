"""公司视图：对应原 NestJS CompanyController / CompanyService。

权限：读 company:view，写 company:manage。
路由由 backend.urls 以 path("api/", include("apps.companies.urls")) 引入。
"""
from __future__ import annotations

from django.db.models import Count
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import (
    PermissionsPermission,
    apply_competition_scope,
    require_permissions,
)
from apps.common.pagination import paginated_response, parse_pagination
from apps.common.permissions import has_permission
from apps.common.scope import assert_same_competition
from apps.common.sync import apply_updated_after, build_incremental_result

from .models import Company
from .serializers import CompanySerializer

_VIEW_PERM = "company:view"
_MANAGE_PERM = "company:manage"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)
# PATCH 仅允许以下字段（与前端 companiesApi.update 契约一致）
_UPDATE_FIELDS = {"name", "status", "regionId"}


def _company_list_scopes(user) -> list | None:
    """返回 company:view 作用域内可见公司 id 列表；None 表示不过滤。

    对应原 companyListScopes 逻辑：
    - SUPER_ADMIN：不过滤
    - 无 company:view 权限：不过滤（由权限层拦截）
    - 有 company:view 且 viewCompanyScopes 非空：仅这些公司
    - 有 company:view 且 viewCompanyScopes 为空：不过滤（见自己比赛全部公司）
    """
    if getattr(user, "role", None) == "SUPER_ADMIN":
        return None
    if not has_permission(user.role, user.permissions_list, _VIEW_PERM):
        return None
    scopes = user.view_company_scopes_list
    return scopes if scopes else None


def _parse_previous_ids(raw) -> list | None:
    """解析逗号分隔的 previousIds，用于增量同步 deletedIds 计算。"""
    if not raw:
        return None
    ids: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            pass
    return ids or None


def _get_company(pk, user) -> Company:
    """取公司并做比赛域 + viewCompanyScopes 隔离，越权视作不存在。"""
    try:
        company = Company.objects.get(pk=pk)
    except Company.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(user, "role", None) != "SUPER_ADMIN":
        if company.competition_id != getattr(user, "competition_id", None):
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    scopes = _company_list_scopes(user)
    if scopes is not None and pk not in scopes:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return company


def _serialize(company: Company) -> dict:
    return CompanySerializer(company).data


class CollectionAPIView(APIView):
    """GET/POST /api/companies —— 列表（分页/增量）+ 创建。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        qs = Company.objects.all()
        qs = apply_competition_scope(
            qs, request.user, request.query_params.get("competitionId")
        )
        # 区域过滤
        region_id = request.query_params.get("regionId")
        if region_id:
            try:
                qs = qs.filter(region_id=int(region_id))
            except (TypeError, ValueError):
                pass
        # viewCompanyScopes 过滤
        scopes = _company_list_scopes(request.user)
        if scopes is not None:
            qs = qs.filter(pk__in=scopes)
        # 预取产业类型 + 字段值计数（避免 N+1）
        qs = qs.select_related("industry_type").annotate(
            _field_values_count=Count("field_values")
        )

        # 增量同步
        updated_after = request.query_params.get("updatedAfter")
        where, incremental, _ = apply_updated_after({}, updated_after)
        if incremental:
            updated_qs = qs.filter(**where).order_by("-updated_at")
            updated = [_serialize(c) for c in updated_qs]
            all_current_ids = list(qs.values_list("pk", flat=True))
            previous_ids = _parse_previous_ids(request.query_params.get("previousIds"))
            return Response(
                build_incremental_result(
                    updated, all_current_ids, previous_ids, total=len(updated)
                )
            )

        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = [_serialize(c) for c in qs.order_by("-updated_at")[skip : skip + page_size]]
        return Response(paginated_response(items, total, page, page_size))

    @require_permissions(_MANAGE_PERM)
    def post(self, request):
        serializer = CompanySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = serializer.create(serializer.validated_data)
        return Response(_serialize(company))


class ItemAPIView(APIView):
    """GET/PATCH/DELETE /api/companies/:id —— 详情 + 更新 + 删除。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        company = _get_company(pk, request.user)
        return Response(_serialize(company))

    @require_permissions(_MANAGE_PERM)
    def patch(self, request, pk):
        company = _get_company(pk, request.user)
        # 仅放行 name/status/regionId
        data = {k: v for k, v in request.data.items() if k in _UPDATE_FIELDS}
        serializer = CompanySerializer(company, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.update(company, serializer.validated_data)
        return Response(_serialize(company))

    @require_permissions(_MANAGE_PERM)
    def delete(self, request, pk):
        company = _get_company(pk, request.user)
        raw = request.query_params.get("competitionId")
        try:
            competition_id = int(raw) if raw else None
        except (TypeError, ValueError):
            competition_id = None
        assert_same_competition(company.competition_id, competition_id)
        company.delete()
        return Response({"ok": True})


class ImpactView(APIView):
    """GET /api/companies/:id/impact —— 删除影响（公司产业字段值数）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        company = _get_company(pk, request.user)
        count = company.field_values.count()
        return Response(
            {
                "name": company.name,
                "children": [{"label": "公司产业字段值", "count": count}],
            }
        )
