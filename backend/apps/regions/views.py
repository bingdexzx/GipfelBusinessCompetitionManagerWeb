"""区域视图：对应原 NestJS RegionController / RegionService。

权限：读 data:region:view，写 data:region:edit。
路由由 backend.urls 以 path("api/", include("apps.regions.urls")) 引入。

前端契约（与 regionsApi 对齐）：
- GET    /api/regions                              列表（分页/增量）
- POST   /api/regions                              创建
- GET    /api/regions/map-overview                 地图概览聚合
- PUT    /api/regions/by-name/<name>/overview-cards 按名保存概览卡片
- GET    /api/regions/:id                          详情（含 companies）
- PATCH  /api/regions/:id                          更新
- DELETE /api/regions/:id                          删除
- GET    /api/regions/:id/companies                区域内公司
- GET    /api/regions/:id/overview                 概览（解析后卡片）
- PUT    /api/regions/:id/overview-cards           保存概览卡片
"""
from __future__ import annotations

import json
from urllib.parse import unquote

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import (
    PermissionsPermission,
    apply_competition_scope,
    require_permissions,
)
from apps.common.json_util import parse_json_array
from apps.common.pagination import paginated_response, parse_pagination
from apps.common.scope import assert_same_competition
from apps.common.sync import apply_updated_after, build_incremental_result
from apps.realtime.emit import emit_resource_changed

from .models import Region
from .serializers import OverviewCardItemSerializer, RegionSerializer

_VIEW_PERM = "data:region:view"
_EDIT_PERM = "data:region:edit"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


# ==================== 工具函数 ====================
def _truthy(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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


def _effective_competition_id(request) -> int | None:
    """解析当前请求的比赛上下文。

    SUPER_ADMIN：取 query 中 competitionId（可空）；其余角色：取 query 或
    user.competition_id，强制隔离。
    """
    raw = request.query_params.get("competitionId")
    cid = None
    if raw:
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            cid = None
    if getattr(request.user, "role", None) == "SUPER_ADMIN":
        return cid
    return cid or getattr(request.user, "competition_id", None)


def _get_region(pk, request) -> Region:
    """取区域并做比赛域隔离，越权视作不存在。"""
    try:
        region = Region.objects.get(pk=pk)
    except Region.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(request.user, "role", None) != "SUPER_ADMIN":
        if region.competition_id != getattr(request.user, "competition_id", None):
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return region


def _serialize(region: Region) -> dict:
    return RegionSerializer(region).data


def _check_conflict(data: dict, exclude_id=None) -> None:
    """(competitionId, name) 唯一约束冲突检测。"""
    cid = data.get("competitionId")
    name = data.get("name")
    if cid is None or not name:
        return
    qs = Region.objects.filter(competition_id=cid, name=name)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise BusinessError("名称已存在", code=409, status_code=409)


def _validate_cards(raw_cards) -> list:
    """校验概览卡片数组，返回可 JSON 序列化的 cleaned 列表。"""
    cleaned = []
    for item in (raw_cards or []):
        ser = OverviewCardItemSerializer(data=item)
        ser.is_valid(raise_exception=True)
        cleaned.append(dict(ser.validated_data))
    return cleaned


def _company_brief(company) -> dict:
    return {
        "id": company.id,
        "name": company.name,
        "industryTypeId": company.industry_type_id,
    }


def _companies_in_region(region: Region) -> list:
    return [_company_brief(c) for c in region.companies.all()]


# ==================== 概览卡片解析 ====================
def _parse_location_value(raw) -> str:
    """解析 location 字段值：若为 JSON 字符串 '"北京"' 则解析为 北京；否则去空格返回。

    对应原 NestJS parseLocationValue。
    """
    if raw is None:
        return ""
    s = str(raw)
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        try:
            v = json.loads(s)
            if isinstance(v, str):
                return v
        except (ValueError, TypeError):
            pass
    return s.strip()


def _resolve_cards(cards: list, competition_id: int) -> list:
    """解析概览卡片：补全公司/产业字段信息并计算 value，缺项标记 valid=False。

    对应原 NestJS RegionService.resolveCards：
    - 查公司 → 取其 industry_type + 字段
    - 按字段 id 查 IndustryField
    - 查 CompanyFieldValue(companyId, industryFieldId) → card.value = fv.value 或 field.default_value
    - 公司/产业类型/字段缺失 → valid=False
    """
    # 延迟导入：相关 app 可能尚未就绪，避免本模块导入期失败
    from apps.companies.models import Company, CompanyFieldValue
    from apps.industry_types.models import IndustryField

    company_ids = [c.get("companyId") for c in cards if c.get("companyId") is not None]
    field_ids = [c.get("industryFieldId") for c in cards if c.get("industryFieldId") is not None]

    companies = {c.id: c for c in Company.objects.filter(pk__in=company_ids)}
    fields = {f.id: f for f in IndustryField.objects.filter(pk__in=field_ids)}

    # 预取字段值，按 (company_id, industry_field_id) 建立索引
    fv_map: dict[tuple[int, int], object] = {}
    if company_ids and field_ids:
        for fv in CompanyFieldValue.objects.filter(
            company_id__in=company_ids, industry_field_id__in=field_ids
        ):
            fv_map[(fv.company_id, fv.industry_field_id)] = fv

    resolved = []
    for card in cards:
        company_id = card.get("companyId")
        industry_field_id = card.get("industryFieldId")
        company = companies.get(company_id) if company_id is not None else None
        field = fields.get(industry_field_id) if industry_field_id is not None else None
        industry_type = company.industry_type if company is not None else None

        valid = True
        value = None
        if company is None or industry_type is None or field is None:
            valid = False
        else:
            fv = fv_map.get((company_id, industry_field_id))
            default_value = getattr(field, "default_value", "") or ""
            value = fv.value if fv is not None else default_value

        resolved.append(
            {
                "id": card.get("id"),
                "displayName": card.get("displayName"),
                "companyId": company_id,
                "industryFieldId": industry_field_id,
                "zone": card.get("zone"),
                "value": value,
                "valid": valid,
            }
        )
    return resolved


def _local_companies(region_name: str, competition_id: int) -> list:
    """返回落在该区域（按 location 字段值匹配地图节点名）的公司。

    对应原 NestJS getLocalCompanies：
    - 取该区域下所有 MapNode 名
    - 查 field_key=='location' 的 IndustryField
    - 查对应 CompanyFieldValue，解析 location 值，匹配节点名
    - 返回匹配公司 [{id, name, industryTypeId}]
    """
    from apps.companies.models import Company, CompanyFieldValue
    from apps.industry_types.models import IndustryField
    from apps.maps.models import MapNode

    node_names = list(
        MapNode.objects.filter(competition_id=competition_id, region=region_name)
        .exclude(name="")
        .values_list("name", flat=True)
    )
    if not node_names:
        return []
    node_set = set(node_names)

    location_field_ids = list(
        IndustryField.objects.filter(field_key="location").values_list("id", flat=True)
    )
    if not location_field_ids:
        return []

    matched_company_ids: list[int] = []
    for fv in CompanyFieldValue.objects.filter(
        industry_field_id__in=location_field_ids,
        company__competition_id=competition_id,
    ):
        loc = _parse_location_value(fv.value)
        if loc and loc in node_set:
            matched_company_ids.append(fv.company_id)
    if not matched_company_ids:
        return []
    return [_company_brief(c) for c in Company.objects.filter(pk__in=matched_company_ids)]


def _get_map_overview(competition_id: int) -> list:
    """聚合区域概览：MapNode.region（去重非空）+ Region 实体。对应 getMapOverview。"""
    from apps.maps.models import MapNode

    region_names: list[str] = []
    seen: set[str] = set()
    for name in (
        MapNode.objects.filter(competition_id=competition_id)
        .exclude(region="")
        .values_list("region", flat=True)
        .distinct()
    ):
        if name not in seen:
            seen.add(name)
            region_names.append(name)
    for name in Region.objects.filter(competition_id=competition_id).values_list(
        "name", flat=True
    ):
        if name not in seen:
            seen.add(name)
            region_names.append(name)

    result = []
    for name in region_names:
        region = Region.objects.filter(competition_id=competition_id, name=name).first()
        cards = []
        region_id = None
        if region is not None:
            region_id = region.id
            cards = _resolve_cards(parse_json_array(region.overview_cards), competition_id)
        result.append(
            {
                "id": region_id,
                "region": name,
                "companies": _local_companies(name, competition_id),
                "cards": cards,
            }
        )
    return result


# ==================== /regions ====================
class CollectionView(APIView):
    """GET/POST /api/regions —— 列表（分页/增量）+ 创建。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        qs = apply_competition_scope(
            Region.objects.all(), request.user, request.query_params.get("competitionId")
        )

        # 增量同步
        updated_after = request.query_params.get("updatedAfter")
        where, incremental, _ = apply_updated_after({}, updated_after)
        if incremental:
            updated_qs = qs.filter(**where).order_by("-updated_at")
            items = [_serialize(r) for r in updated_qs]
            all_current_ids = list(qs.values_list("pk", flat=True))
            previous_ids = _parse_previous_ids(request.query_params.get("previousIds"))
            # requireExistingIds=true：强制返回 existingIds（不计算 deletedIds）
            if _truthy(request.query_params.get("requireExistingIds")):
                previous_ids = None
            return Response(
                build_incremental_result(
                    items, all_current_ids, previous_ids, total=len(items)
                )
            )

        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = [_serialize(r) for r in qs.order_by("-updated_at")[skip : skip + page_size]]
        return Response(paginated_response(items, total, page, page_size))

    @require_permissions(_EDIT_PERM)
    def post(self, request):
        serializer = RegionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _check_conflict(serializer.validated_data)
        region = serializer.create(serializer.validated_data)
        emit_resource_changed("region", region.id, region.competition_id, "created")
        return Response(_serialize(region))


# ==================== /regions/map-overview ====================
class MapOverviewView(APIView):
    """GET /api/regions/map-overview —— 地图概览聚合。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        competition_id = _effective_competition_id(request)
        if competition_id is None:
            return Response([])
        return Response(_get_map_overview(competition_id))


# ==================== /regions/by-name/<name>/overview-cards ====================
class SaveByNameView(APIView):
    """PUT /api/regions/by-name/<name>/overview-cards —— 按名保存概览卡片。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def put(self, request, name):
        name = unquote(name)
        competition_id = _effective_competition_id(request)
        if competition_id is None:
            raise BusinessError("缺少比赛上下文", code=400, status_code=400)
        cleaned = _validate_cards(request.data.get("cards", []))
        region, _ = Region.objects.get_or_create(
            competition_id=competition_id,
            name=name,
            defaults={"overview_cards": "[]"},
        )
        region.overview_cards = json.dumps(cleaned, ensure_ascii=False)
        region.save()
        emit_resource_changed("region", region.id, region.competition_id, "updated")
        return Response({"success": True})


# ==================== /regions/:id ====================
class ItemView(APIView):
    """GET/PATCH/DELETE /api/regions/:id —— 详情（含 companies）+ 更新 + 删除。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        region = _get_region(pk, request)
        data = _serialize(region)
        data["companies"] = _companies_in_region(region)
        return Response(data)

    @require_permissions(_EDIT_PERM)
    def patch(self, request, pk):
        region = _get_region(pk, request)
        serializer = RegionSerializer(region, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        _check_conflict(serializer.validated_data, exclude_id=pk)
        serializer.update(region, serializer.validated_data)
        emit_resource_changed("region", region.id, region.competition_id, "updated")
        return Response(_serialize(region))

    @require_permissions(_EDIT_PERM)
    def delete(self, request, pk):
        region = _get_region(pk, request)
        raw = request.query_params.get("competitionId")
        try:
            competition_id = int(raw) if raw else None
        except (TypeError, ValueError):
            competition_id = None
        assert_same_competition(region.competition_id, competition_id)

        # 阻断：若有 MapNode 使用 region==name
        from apps.maps.models import MapNode

        if MapNode.objects.filter(
            competition_id=region.competition_id, region=region.name
        ).exists():
            raise BusinessError("该区域下仍有地图节点，无法删除", code=400, status_code=400)

        region_id = region.id
        region_competition_id = region.competition_id
        with transaction.atomic():
            # 解除该区域下公司的 region 关联（Company.region 为 SET_NULL）
            region.companies.update(region=None)
            region.delete()
        emit_resource_changed("region", region_id, region_competition_id, "deleted")
        return Response({"ok": True})


# ==================== /regions/:id/companies ====================
class CompaniesView(APIView):
    """GET /api/regions/:id/companies —— 区域内公司列表。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        region = _get_region(pk, request)
        return Response(_companies_in_region(region))


# ==================== /regions/:id/overview ====================
class OverviewView(APIView):
    """GET /api/regions/:id/overview —— {id, name, cards: 解析后卡片}。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        region = _get_region(pk, request)
        cards = _resolve_cards(parse_json_array(region.overview_cards), region.competition_id)
        return Response({"id": region.id, "name": region.name, "cards": cards})


# ==================== /regions/:id/overview-cards ====================
class SaveOverviewCardsView(APIView):
    """PUT /api/regions/:id/overview-cards —— 保存概览卡片。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def put(self, request, pk):
        region = _get_region(pk, request)
        cleaned = _validate_cards(request.data.get("cards", []))
        region.overview_cards = json.dumps(cleaned, ensure_ascii=False)
        region.save()
        emit_resource_changed("region", region.id, region.competition_id, "updated")
        return Response({"success": True})
