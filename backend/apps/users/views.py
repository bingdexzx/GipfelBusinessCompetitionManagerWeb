"""用户管理视图：对应原 NestJS UsersController（/api/users）。

响应经 apps.common.response.JSONRenderer 自动包装为 {code,message,data}，
视图返回 Response(data) 即可。鉴权依赖 IsAuthenticated + PermissionsPermission，
细粒度权限由 @require_permissions("account:manage") 标注。

注意：Django 按路径（非方法）路由，同一路径的多 HTTP 方法需在同一视图类中
承载。为保持各端点视图类独立可测，采用多继承组合：将同名端点视图组合为
「集合视图」「条目视图」注册到路由。
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission, require_permissions
from apps.common.pagination import paginated_response, parse_pagination
from apps.common.permissions import assert_grant_allowed

from .models import User
from .serializers import UserSerializer, dump_json_scope

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


def _get_user(pk) -> User:
    try:
        return User.objects.get(pk=pk)
    except User.DoesNotExist:
        raise BusinessError("用户不存在", code=404, status_code=404)


def _assert_grant(request, target_role, permissions) -> None:
    """授予上限校验：操作者必须为超管，且授予的权限不越界。"""
    perms = permissions if permissions is not None else []
    allowed, violations = assert_grant_allowed(
        getattr(request.user, "role", None), target_role, perms
    )
    if not allowed:
        raise BusinessError("；".join(violations), code=400, status_code=400)


class UserListView(APIView):
    """GET /api/users —— 列出用户（分页），可按 competitionId 过滤。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def get(self, request):
        qs = User.objects.all()
        # competitionId 过滤：null/"null" = 未归属比赛的系统账号
        cid_raw = request.query_params.get("competitionId")
        if cid_raw is not None and cid_raw != "null":
            try:
                cid = int(cid_raw)
            except ValueError:
                raise BusinessError("competitionId 参数非法", code=400, status_code=400)
            qs = qs.filter(competition_id=cid)
        elif cid_raw == "null":
            qs = qs.filter(competition_id__isnull=True)

        page, page_size, skip = parse_pagination(request.query_params)
        total = qs.count()
        items = UserSerializer(
            qs.order_by("-updated_at")[skip : skip + page_size], many=True
        ).data
        return Response(paginated_response(items, total, page, page_size))


class UserCreateView(APIView):
    """POST /api/users —— 创建用户（含密码）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # 授予上限校验（以新角色为准）
        _assert_grant(
            request,
            serializer.validated_data.get("role", "PLAYER"),
            serializer.validated_data.get("permissions"),
        )
        serializer.save()
        return Response(UserSerializer(serializer.instance).data)


class UserDetailView(APIView):
    """GET /api/users/:id —— 用户详情。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def get(self, request, pk):
        user = _get_user(pk)
        return Response(UserSerializer(user).data)


class UserUpdateView(APIView):
    """PATCH /api/users/:id —— 更新用户（禁止改名）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def patch(self, request, pk):
        user = _get_user(pk)
        serializer = UserSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # 授予上限校验：以新角色为准，权限取「提交值或既有值」
        effective_role = serializer.validated_data.get("role", user.role)
        effective_perms = serializer.validated_data.get(
            "permissions", user.permissions_list
        )
        _assert_grant(request, effective_role, effective_perms)
        serializer.save()
        return Response(UserSerializer(user).data)


class UserDeleteView(APIView):
    """DELETE /api/users/:id —— 删除用户。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def delete(self, request, pk):
        user = _get_user(pk)
        if user.id == request.user.id:
            raise BusinessError("不能删除当前登录账号", code=400, status_code=400)
        user.delete()
        return Response({"ok": True})


class UserPasswordView(APIView):
    """PATCH /api/users/:id/password —— 管理员重置密码。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def patch(self, request, pk):
        user = _get_user(pk)
        password = request.data.get("password") or request.data.get("newPassword")
        if not password:
            raise BusinessError("密码不能为空", code=400, status_code=400)
        if len(password) < 8:
            raise BusinessError("密码长度不能少于 8 位", code=400, status_code=400)
        user.set_password(password)
        # 可选 mustChangePassword：传入则覆盖，否则保留现状
        must_change = request.data.get("mustChangePassword")
        if must_change is not None:
            user.must_change_password = bool(must_change)
        user.save(update_fields=["password_hash", "must_change_password", "updated_at"])
        return Response(UserSerializer(user).data)


class UserPermissionsView(APIView):
    """POST /api/users/:id/permissions —— 授予权限（按角色模板/授予上限校验）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions("account:manage")
    def post(self, request, pk):
        user = _get_user(pk)
        permissions = request.data.get("permissions")
        if not isinstance(permissions, list):
            raise BusinessError("permissions 必须是数组", code=400, status_code=400)
        _assert_grant(request, user.role, permissions)
        user.permissions = dump_json_scope(permissions) if permissions else None
        # 每一次赋权都 bump permission_version：前端收到 permissions:changed 后刷新缓存并重算 can()
        user.permission_version = (user.permission_version or 0) + 1
        user.save(update_fields=["permissions", "permission_version", "updated_at"])

        # 实时推送给该用户，让前端立即重算权限按钮显隐
        try:
            from apps.realtime.emit import emit_permissions_changed
            emit_permissions_changed(user.id, user.permission_version)
        except Exception:  # noqa: BLE001
            pass
        return Response(UserSerializer(user).data)


# ==================== 路由组合视图 ====================
# 同一路径承载多 HTTP 方法：组合上述端点视图，按方法由 DRF dispatch 分发。
class UserCollectionAPIView(UserListView, UserCreateView):
    """GET/POST /api/users —— list + create 组合。"""


class UserItemAPIView(UserDetailView, UserUpdateView, UserDeleteView):
    """GET/PATCH/DELETE /api/users/:id —— detail + update + delete 组合。"""
