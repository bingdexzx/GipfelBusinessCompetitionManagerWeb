"""比赛与财年视图：对应原 NestJS CompetitionsController / FiscalYearsController。

权限：
- 列表/详情（GET）仅需登录；非超管只能看到自己所属比赛（比赛域隔离）。
- 增删改（POST/PATCH/DELETE）需 competition:manage（超管专属）。

响应经 apps.common.response.JSONRenderer 自动包装为 {code,message,data}。
同一路径多 HTTP 方法通过组合视图承载（与 users 模块一致）。
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission, require_permissions
from apps.common.pagination import paginated_response, parse_pagination

from .models import Competition, FiscalYear
from .serializers import CompetitionSerializer, FiscalYearSerializer

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


def _get_competition(pk, user) -> Competition:
    """取比赛并做比赛域隔离：非超管仅能访问自己所属的比赛，否则视作不存在。"""
    try:
        comp = Competition.objects.get(pk=pk)
    except Competition.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(user, "role", None) != "SUPER_ADMIN" and comp.id != getattr(
        user, "competition_id", None
    ):
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return comp


def _get_fiscal_year(pk, user) -> FiscalYear:
    try:
        fy = FiscalYear.objects.get(pk=pk)
    except FiscalYear.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(user, "role", None) != "SUPER_ADMIN" and fy.competition_id != getattr(
        user, "competition_id", None
    ):
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return fy


# ==================== 比赛 ====================
class CompetitionListView(APIView):
    """GET /api/competitions —— 列出比赛（分页）；非超管仅见自己所属比赛。"""

    permission_classes = _PERM_CLASSES

    def get(self, request):
        qs = Competition.objects.all()
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            cid = getattr(request.user, "competition_id", None)
            qs = qs.filter(pk=cid) if cid else qs.none()
        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = CompetitionSerializer(
            qs.order_by("-updated_at")[skip : skip + page_size], many=True
        ).data
        return Response(paginated_response(items, total, page, page_size))


class CompetitionCreateView(APIView):
    """POST /api/competitions —— 创建比赛（超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def post(self, request):
        serializer = CompetitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        if Competition.objects.filter(name=name).exists():
            raise BusinessError("比赛名称已存在", code=409, status_code=409)
        serializer.save()
        return Response(CompetitionSerializer(serializer.instance).data)


class CompetitionDetailView(APIView):
    """GET /api/competitions/:id —— 比赛详情。"""

    permission_classes = _PERM_CLASSES

    def get(self, request, pk):
        comp = _get_competition(pk, request.user)
        return Response(CompetitionSerializer(comp).data)


class CompetitionUpdateView(APIView):
    """PATCH /api/competitions/:id —— 更新比赛（超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def patch(self, request, pk):
        comp = _get_competition(pk, request.user)
        serializer = CompetitionSerializer(comp, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data.get("name")
        if name and name != comp.name and Competition.objects.filter(name=name).exists():
            raise BusinessError("比赛名称已存在", code=409, status_code=409)
        serializer.save()
        return Response(CompetitionSerializer(comp).data)


class CompetitionDeleteView(APIView):
    """DELETE /api/competitions/:id —— 删除比赛（超管，级联删除子资源）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def delete(self, request, pk):
        comp = _get_competition(pk, request.user)
        comp.delete()
        return Response({"ok": True})


# ==================== 财年 ====================
class FiscalYearListView(APIView):
    """GET /api/competitions/:id/fiscal-years —— 列出某比赛财年（分页）。"""

    permission_classes = _PERM_CLASSES

    def get(self, request, cid):
        comp = _get_competition(cid, request.user)
        qs = comp.fiscal_years.all().order_by("-year")
        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = FiscalYearSerializer(
            qs[skip : skip + page_size], many=True
        ).data
        return Response(paginated_response(items, total, page, page_size))


class FiscalYearCreateView(APIView):
    """POST /api/competitions/:id/fiscal-years {year} —— 创建财年（超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def post(self, request, cid):
        comp = _get_competition(cid, request.user)
        serializer = FiscalYearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        year = serializer.validated_data["year"]
        if FiscalYear.objects.filter(competition=comp, year=year).exists():
            raise BusinessError("该财年已存在", code=409, status_code=409)
        fy = FiscalYear.objects.create(
            competition=comp,
            year=year,
            status=serializer.validated_data.get("status", "ACTIVE"),
        )
        return Response(FiscalYearSerializer(fy).data)


class FiscalYearUpdateView(APIView):
    """PATCH /api/competitions/fiscal-years/:id {status} —— 更新财年（超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def patch(self, request, pk):
        fy = _get_fiscal_year(pk, request.user)
        serializer = FiscalYearSerializer(fy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "status" in serializer.validated_data:
            fy.status = serializer.validated_data["status"]
        if "year" in serializer.validated_data:
            fy.year = serializer.validated_data["year"]
        fy.save()
        return Response(FiscalYearSerializer(fy).data)


class FiscalYearDeleteView(APIView):
    """DELETE /api/competitions/fiscal-years/:id —— 删除财年（超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def delete(self, request, pk):
        fy = _get_fiscal_year(pk, request.user)
        fy.delete()
        return Response({"ok": True})


# ==================== 路由组合视图 ====================
class CompetitionCollectionAPIView(CompetitionListView, CompetitionCreateView):
    """GET/POST /api/competitions —— list + create 组合。"""


class CompetitionItemAPIView(
    CompetitionDetailView, CompetitionUpdateView, CompetitionDeleteView
):
    """GET/PATCH/DELETE /api/competitions/:id —— detail + update + delete 组合。"""


class FiscalYearCollectionAPIView(FiscalYearListView, FiscalYearCreateView):
    """GET/POST /api/competitions/:id/fiscal-years —— list + create 组合。"""


class FiscalYearItemAPIView(FiscalYearUpdateView, FiscalYearDeleteView):
    """PATCH/DELETE /api/competitions/fiscal-years/:id —— update + delete 组合。"""
