"""权限守卫装饰器与 DRF permission 类。

对应原 NestJS：
- @RequirePermissions() → require_permissions 装饰器
- PermissionsGuard → PermissionsPermission
- CompetitionScopeGuard → CompetitionScopePermission
- OwnershipGuard → 视图 get_object 覆写 + OwnershipPermission
- MustChangePasswordGuard → MustChangePasswordPermission
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .permissions import has_permission


# ==================== 视图级权限装饰器 ====================
def require_permissions(*required: str):
    """视图方法装饰器：标注所需权限 key。

    实际校验由 PermissionsPermission 在 permission_classes 链中执行；
    装饰器把 required 写入 view._required_permissions 供 permission 类读取。
    """

    def decorator(func):
        existing = getattr(func, "_required_permissions", ()) or ()
        func._required_permissions = tuple(existing) + tuple(required)
        return func

    return decorator


def no_competition_scope(func):
    """标记视图跳过比赛域自动注入/校验（对应 @NoCompetitionScope）。"""

    func._no_competition_scope = True
    return func


# ==================== DRF Permission 类 ====================
class MustChangePasswordPermission(permissions.BasePermission):
    """强制改密拦截：mustChangePassword=true 时除改密接口外全部拒绝。"""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return True  # 未认证交给 IsAuthenticated
        # 改密接口自身放行
        if getattr(view, "_allow_must_change_password", False):
            return True
        if getattr(user, "must_change_password", False):
            raise PermissionDenied("账号需先修改初始密码")
        return True


class PermissionsPermission(permissions.BasePermission):
    """RBAC：读取视图方法上的 @require_permissions 标注并校验。"""

    def has_permission(self, request, view):
        # 取当前 action 对应方法上的标注
        handler = getattr(view, request.method.lower(), None)
        required: Iterable[str] = ()
        if handler is not None:
            required = getattr(handler, "_required_permissions", ()) or ()
        if not required:
            return True  # 无标注默认放行（鉴权由 IsAuthenticated 保证）
        user = request.user
        perms = user.permissions_list if hasattr(user, "permissions_list") else []
        if not has_permission(getattr(user, "role", None), perms, list(required)):
            raise PermissionDenied("没有权限执行此操作")
        return True


class CompetitionScopePermission(permissions.BasePermission):
    """比赛域隔离：非 SUPER_ADMIN 自动校验/注入 competitionId。

    实际的 queryset 过滤由各视图的 get_queryset 配合 _apply_competition_scope 完成；
    此 permission 仅做粗校验（SUPER_ADMIN 跳过，其余必须有比赛上下文）。
    """

    def has_permission(self, request, view):
        # 标注 @no_competition_scope 的视图跳过
        handler = getattr(view, request.method.lower(), None)
        if handler is not None and getattr(handler, "_no_competition_scope", False):
            return True
        if getattr(view, "_no_competition_scope_class", False):
            return True
        user = request.user
        if getattr(user, "role", None) == "SUPER_ADMIN":
            return True
        # 非 SUPER_ADMIN 必须有比赛上下文（写操作时由视图注入 competitionId）
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            cid = request.data.get("competitionId") if request.data else None
            if cid is None and getattr(user, "competition_id", None) is None:
                raise PermissionDenied("缺少比赛上下文")
        return True


def apply_competition_scope(queryset, user, competition_id=None):
    """对 queryset 应用比赛域过滤。

    - SUPER_ADMIN：若显式传入 competitionId 则按其过滤，否则不过滤
    - 其余角色：强制按 user.competition_id 过滤（防越权读其他比赛）
    """
    if getattr(user, "role", None) == "SUPER_ADMIN":
        if competition_id is not None:
            return queryset.filter(competition_id=competition_id)
        return queryset
    cid = competition_id or getattr(user, "competition_id", None)
    if cid is None:
        return queryset.none()
    return queryset.filter(competition_id=cid)
