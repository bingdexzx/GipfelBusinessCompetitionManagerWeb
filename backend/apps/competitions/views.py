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
from apps.realtime.emit import emit_to_competition

from .models import Competition, FiscalYear
from .serializers import CompetitionSerializer, FiscalYearSerializer

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)

EVENT_FISCAL_YEAR_CHANGED = "fiscal-year:changed"


def _broadcast_fiscal_year(fy: FiscalYear) -> None:
    """广播 fiscal-year:changed，载荷对齐 NestJS：{competitionId, fiscalYear}。

    前端 stores/competition.ts 的 handleFiscalYearChanged 依赖该事件即时同步顶部栏
    财年标签（无需 HTTP 回源），并作废本地比赛缓存。
    """
    emit_to_competition(
        fy.competition_id,
        EVENT_FISCAL_YEAR_CHANGED,
        {
            "competitionId": fy.competition_id,
            "fiscalYear": FiscalYearSerializer(fy).data,
        },
    )


def _apply_fiscal_year_timer(competition_id: int, trigger: str) -> None:
    """触发财年定时器（对齐 NestJS applyFiscalYearTimer）。

    延迟导入 company_fields.timer 避免模块间循环依赖；并广播受影响公司的字段变更，
    使同比赛前端（公司详情/区域总览）即刻刷新。无启用定时器字段时该函数静默返回。
    """
    from apps.company_fields.timer import apply_fiscal_year_timer as _impl
    from apps.realtime.emit import emit_to_competition as _emit

    affected = _impl(competition_id, trigger)
    # 定时器写入会改动本比赛相关公司字段，统一广播让前端刷新（company-field:changed 房间事件）。
    _emit(
        competition_id,
        "company-field:changed",
        {"competitionId": competition_id, "trigger": trigger},
    )
    return affected


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
        # prefetch_related：序列化器内联 fiscalYears，不预取会按比赛条数产生 N+1 查询。
        qs = Competition.objects.all().prefetch_related("fiscal_years")
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
        # 新建财年即「财年开始」，与 update 对齐广播，使各端顶部栏即刻同步。
        _broadcast_fiscal_year(fy)
        # 财年定时器：FY_START 触发本比赛全部启用该时机的产业字段写入（对齐 NestJS）。
        _apply_fiscal_year_timer(comp.id, "FY_START")
        return Response(FiscalYearSerializer(fy).data)


class FiscalYearUpdateView(APIView):
    """PATCH /api/competitions/fiscal-years/:id {status} —— 更新财年（超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("competition:manage")
    def patch(self, request, pk):
        fy = _get_fiscal_year(pk, request.user)
        serializer = FiscalYearSerializer(fy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        prev_status = fy.status
        if "status" in serializer.validated_data:
            fy.status = serializer.validated_data["status"]
        if "year" in serializer.validated_data:
            new_year = serializer.validated_data["year"]
            # 唯一性修复（M16）：更新财年年份时校验 (competition, year) 不冲突，
            # 与创建接口的约束保持一致，避免同比赛出现重复财年。
            if new_year != fy.year and FiscalYear.objects.filter(
                competition_id=fy.competition_id, year=new_year
            ).exclude(pk=fy.pk).exists():
                raise BusinessError("该财年已存在", code=409, status_code=409)
            fy.year = new_year
        fy.save()
        # 财年开始/关闭后广播，使各端顶部栏与财年列表即刻同步。
        _broadcast_fiscal_year(fy)
        # 财年定时器：非 ACTIVE→ACTIVE 视为 FY_START；非 CLOSED→CLOSED 视为 FY_END
        # （对齐 NestJS updateFiscalYear 的 trigger 推导；其它状态切换不触发）。
        new_status = fy.status
        if prev_status != "ACTIVE" and new_status == "ACTIVE":
            _apply_fiscal_year_timer(fy.competition_id, "FY_START")
        elif prev_status != "CLOSED" and new_status == "CLOSED":
            _apply_fiscal_year_timer(fy.competition_id, "FY_END")
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
