"""公司视图。

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
from apps.common.helpers import (
    company_list_scopes as _company_list_scopes,
    get_company_scoped as _get_company,
    parse_previous_ids as _parse_previous_ids,
)

_VIEW_PERM = "company:view"
_MANAGE_PERM = "company:manage"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)
# PATCH 仅允许以下字段（与前端 companiesApi.update 契约一致）
_UPDATE_FIELDS = {"name", "status", "regionId", "industryTypeId"}




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
        from apps.common.guards import create_competition_id

        serializer = CompanySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # 非超管强制归属自身比赛，防止跨比赛写入
        data = dict(serializer.validated_data)
        data["competitionId"] = create_competition_id(request.user, data)
        company = serializer.create(data)
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
        # 引用保护：公司被合同参与方 / 股票资金账户 / 股票 PE 联动引用时禁止删除
        # （这些引用是纯整型列/JSON，无外键级联，强删会留下孤儿数据并使合同执行/复原失败）
        import json as _json

        from apps.contracts.models import Contract
        from apps.stock.models import Stock, StockFundsAccount

        cid = company.pk
        contract_refs = 0
        for c in Contract.objects.filter(competition_id=company.competition_id).only("parties"):
            try:
                parties = _json.loads(c.parties or "[]")
            except (ValueError, TypeError):
                continue
            if any(isinstance(p, dict) and p.get("companyId") == cid for p in parties):
                contract_refs += 1
        if contract_refs:
            raise BusinessError(f"该公司仍是 {contract_refs} 份合同的参与方，请先删除相关合同")
        account_refs = StockFundsAccount.objects.filter(company_id=cid).count()
        if account_refs:
            raise BusinessError(f"该公司名下仍有 {account_refs} 个资金账户，请先删除相关账户")
        stock_refs = Stock.objects.filter(pb_company_id=cid).count()
        if stock_refs:
            raise BusinessError(f"仍有 {stock_refs} 只股票的 PE 联动绑定该公司，请先解除绑定")
        company.delete()
        return Response({"ok": True})


class RecomputeAllAPIView(APIView):
    """POST /api/companies/recompute-all —— 全量重算某比赛所有公司的计算字段。

    仅超级管理员可用。逐公司走 calc.recompute_calc_fields（按依赖拓扑序），
    成功后逐公司 emit_resource_changed("company-field", ..., "updated")
    让前端实时刷新字段值。
    """

    permission_classes = _PERM_CLASSES

    def post(self, request):
        import logging

        from apps.common.guards import _normalize_competition_id

        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可执行全量重算", code=403, status_code=403)

        competition_id = _normalize_competition_id(
            (request.data or {}).get("competitionId")
            if isinstance(request.data, dict)
            else request.query_params.get("competitionId")
        )
        if competition_id is None:
            raise BusinessError("缺少比赛上下文，请先选择比赛")

        company_ids = list(
            Company.objects.filter(competition_id=competition_id).values_list("id", flat=True)
        )

        from apps.company_fields.calc import recompute_calc_fields
        from apps.realtime.emit import emit_resource_changed

        logger = logging.getLogger("gipfel")
        ok_count = 0
        failed: list[int] = []
        for cid in company_ids:
            try:
                recompute_calc_fields(cid)
            except Exception as e:  # noqa: BLE001 单公司失败不中断整体
                logger.warning(
                    "[companies] 全量重算：公司 #%s 失败：%s", cid, getattr(e, "message", e)
                )
                failed.append(cid)
                continue
            ok_count += 1
            emit_resource_changed("company-field", cid, competition_id, "updated")

        logger.info(
            "[companies] 全量重算完成：比赛 #%s 共 %s 家，成功 %s，失败 %s",
            competition_id, len(company_ids), ok_count, len(failed),
        )
        return Response(
            {"ok": True, "recomputed": ok_count, "total": len(company_ids), "failed": failed}
        )


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
