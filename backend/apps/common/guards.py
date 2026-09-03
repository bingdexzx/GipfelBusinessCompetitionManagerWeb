"""权限守卫装饰器与 DRF permission 类。

- @RequirePermissions() → require_permissions 装饰器
- PermissionsGuard → PermissionsPermission
- CompetitionScopeGuard → CompetitionScopePermission
- OwnershipGuard → 视图 get_object 覆写 + OwnershipPermission
- MustChangePasswordGuard → MustChangePasswordPermission
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .permissions import has_permission

logger = logging.getLogger(__name__)


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
            # 契约（显式化）：未标注 @require_permissions 的视图，默认仅「已登录」即可访问。
            # 这并非越权缺口，而是设计基线：
            #   - 登录态由 IsAuthenticated 保证；
            #   - 比赛域隔离由 CompetitionScopePermission 全局兜底；
            #   - 敏感写操作应在视图方法上显式标注 @require_permissions（A 组已补全）。
            # 护栏：对未标注且为非只读（写/删）方法的视图，在 DEBUG 下告警，
            # 便于在开发期发现遗漏的权限标注。生产环境（DEBUG=False）零行为变化。
            _maybe_warn_missing_permission(request, view)
            return True
        user = request.user
        perms = user.permissions_list if hasattr(user, "permissions_list") else []
        if not has_permission(getattr(user, "role", None), perms, list(required)):
            raise PermissionDenied("没有权限执行此操作")
        return True


def _maybe_warn_missing_permission(request, view):
    """DEBUG 护栏：未标注 @require_permissions 却处理写/删请求时告警。

    仅用于开发期发现「本应加权限标注却遗漏」的视图；不拦截、不影响生产行为。
    """
    if not getattr(settings, "DEBUG", False):
        return
    if request.method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    view_name = type(view).__name__
    logger.warning(
        "[security] 视图 %s.%s 未标注 @require_permissions 但处理写/删请求，"
        "请确认是否遗漏权限标注（当前仅依赖登录态与比赛域隔离）。",
        view_name, request.method.upper(),
    )


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


def create_competition_id(user, data: dict | None = None):
    """create 时确定资源归属比赛：非超管强制用自身比赛，杜绝跨比赛写入。

    超管可显式指定 competitionId；非超管一律忽略请求体中的 competitionId，
    强制归属到 request.user.competition_id。
    """
    data = data or {}
    if getattr(user, "role", None) == "SUPER_ADMIN":
        cid = data.get("competitionId")
        if not cid:
            raise PermissionDenied("缺少比赛上下文")
        return cid
    cid = getattr(user, "competition_id", None)
    if not cid:
        raise PermissionDenied("当前账号未归属任何比赛")
    return cid


def strip_competition_fields(data: dict) -> dict:
    """从更新数据中剔除 competitionId/competition_id，防止跨比赛迁移。"""
    return {k: v for k, v in data.items() if k not in ("competitionId", "competition_id")}


def _normalize_competition_id(value):
    """把前端可能传来的各种「无值」形态统一为 None 或 int。

    防御：前端在比赛未选中时可能把 competitionId 传成字符串 "null" / 空串，
    或传入非整数；若直接交给 queryset.filter(competition_id=...) 会触发
    Field 'id' expected a number but got 'null' 的 500。这里在过滤前归一成
    None（视为「不限/无上下文」）或可比较的 int。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        s = value.strip()
        if s == "" or s.lower() == "null":
            return None
        try:
            return int(s)
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def apply_competition_scope(queryset, user, competition_id=None):
    """对 queryset 应用比赛域过滤。

    - SUPER_ADMIN：若显式传入 competitionId 则按其过滤，否则不过滤
    - 其余角色：强制按 user.competition_id 过滤（忽略前端传入的 competitionId，
      防越权读其他比赛）；无比赛上下文则返回空集
    """
    competition_id = _normalize_competition_id(competition_id)
    if getattr(user, "role", None) == "SUPER_ADMIN":
        if competition_id is not None:
            return queryset.filter(competition_id=competition_id)
        return queryset
    # 非超管：始终按其所属比赛隔离，前端传入的 competitionId 不被信任
    cid = _normalize_competition_id(getattr(user, "competition_id", None))
    if cid is None:
        return queryset.none()
    return queryset.filter(competition_id=cid)
