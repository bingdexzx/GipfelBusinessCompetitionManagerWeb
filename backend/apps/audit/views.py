"""审计日志视图：对应原 NestJS AuditLogController（/api/audit-logs）。

只读列表端点，需登录 + account:manage（超管可见全部审计日志）。
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.guards import PermissionsPermission, require_permissions
from apps.common.pagination import paginated_response, parse_pagination

from .models import AuditLog
from .serializers import AuditLogSerializer

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


class AuditLogListView(APIView):
    """GET /api/audit-logs —— 审计日志列表（分页，可按 kind/model/operatorId/competitionId 过滤）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def get(self, request):
        qs = AuditLog.objects.all()

        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)

        model = request.query_params.get("model")
        if model:
            qs = qs.filter(model=model)

        op = request.query_params.get("operatorId")
        if op and op != "null":
            try:
                qs = qs.filter(operator_id=int(op))
            except ValueError:
                pass

        cid = request.query_params.get("competitionId")
        if cid and cid != "null":
            try:
                qs = qs.filter(competition_id=int(cid))
            except ValueError:
                pass

        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = AuditLogSerializer(
            qs.order_by("-created_at")[skip : skip + page_size], many=True
        ).data
        return Response(paginated_response(items, total, page, page_size))
