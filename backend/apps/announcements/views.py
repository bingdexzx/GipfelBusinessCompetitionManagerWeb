"""更新公告视图。

权限：读取无需额外权限（已登录即可），增删改仅超级管理员。
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission, require_permissions

from .models import Announcement

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


def _to_dict(a: Announcement) -> dict:
    return {
        "id": a.id,
        "version": a.version,
        "title": a.title,
        "date": a.date,
        "content": a.content,
        "isActive": a.is_active,
        "createdAt": a.created_at.isoformat() if a.created_at else None,
        "updatedAt": a.updated_at.isoformat() if a.updated_at else None,
    }


class CollectionView(APIView):
    """GET /api/announcements（列表）+ POST /api/announcements（创建，仅超管）。"""

    permission_classes = _PERM_CLASSES

    def get(self, request):
        qs = Announcement.objects.all()
        # 非超管仅可见已启用的公告
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            qs = qs.filter(is_active=True)
        return Response([_to_dict(a) for a in qs])

    def post(self, request):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可发布更新公告", code=403, status_code=403)
        data = request.data if isinstance(request.data, dict) else {}
        version = (data.get("version") or "").strip()
        title = (data.get("title") or "").strip()
        content = (data.get("content") or "").strip()
        date = (data.get("date") or "").strip()
        if not version:
            raise BusinessError("版本号不能为空", code=400, status_code=400)
        if not title:
            raise BusinessError("标题不能为空", code=400, status_code=400)
        if not content:
            raise BusinessError("内容不能为空", code=400, status_code=400)
        if not date:
            from datetime import date as dt_date
            date = dt_date.today().isoformat()
        a = Announcement.objects.create(
            version=version,
            title=title,
            date=date,
            content=content,
            is_active=data.get("isActive", True),
        )
        return Response(_to_dict(a))


class ItemView(APIView):
    """GET/PATCH/DELETE /api/announcements/:id。"""

    permission_classes = _PERM_CLASSES

    def _get(self, pk):
        try:
            return Announcement.objects.get(pk=pk)
        except Announcement.DoesNotExist:
            raise BusinessError("公告不存在", code=404, status_code=404)

    def get(self, request, pk):
        a = self._get(pk)
        if not a.is_active and getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("公告不存在", code=404, status_code=404)
        return Response(_to_dict(a))

    def patch(self, request, pk):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可编辑更新公告", code=403, status_code=403)
        a = self._get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        if "version" in data:
            a.version = (data["version"] or "").strip()
        if "title" in data:
            a.title = (data["title"] or "").strip()
        if "content" in data:
            a.content = (data["content"] or "").strip()
        if "date" in data:
            a.date = (data["date"] or "").strip()
        if "isActive" in data:
            a.is_active = bool(data["isActive"])
        a.save()
        return Response(_to_dict(a))

    def delete(self, request, pk):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可删除更新公告", code=403, status_code=403)
        a = self._get(pk)
        a.delete()
        return Response({"ok": True})
