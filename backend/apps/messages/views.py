"""消息中心视图：对应原 NestJS message.controller / message.service。

权限：view=message:view（读 / 已读标记），manage=message:manage（发布 / 删除 / 上传图片）。
路由由 backend.urls 以 path("api/", include("apps.messages.urls")) 引入。

收件箱 / 未读 / 已读以当前用户（userId）为过滤维度，不依赖 competitionId，
故整体不套用比赛域隔离（对应原 @NoCompetitionScope）。
"""
from __future__ import annotations

import json
import os
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission, require_permissions
from apps.common.json_util import parse_json_array
from apps.common.pagination import paginated_response, parse_pagination
from apps.realtime.emit import emit_resource_changed_to_users, emit_to_users

from .models import Message, MessageRecipient
from .serializers import (
    MessageSerializer,
    message_to_dict,
    serialize_inbox_item,
    serialize_sent_item,
)

# 消息图片落盘子目录（相对 MEDIA_ROOT，前端经 /uploads/message-images/ 跨源加载）
_MSG_IMAGE_SUBDIR = "message-images"
# 允许上传的图片 MIME 与扩展名（对应原 common/image-mime）
_IMAGE_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_MAX_RECIPIENTS = 500
_SENT_TAKE = 500  # 与原 NestJS sent/inbox 的 take 上限一致


# ==================== 辅助 ====================
def _msg_image_dir() -> str:
    return os.path.join(settings.MEDIA_ROOT, _MSG_IMAGE_SUBDIR)


def _sender_name_map(user_ids):
    """批量查用户 id -> 显示名（displayName 优先，回退 username）。"""
    from apps.users.models import User

    ids = [uid for uid in user_ids if uid is not None]
    if not ids:
        return {}
    users = User.objects.filter(id__in=ids).values("id", "display_name", "username")
    return {u["id"]: u["display_name"] or u["username"] for u in users}


def _resolve_name(sender_map, uid) -> str:
    return sender_map.get(uid) or f"用户{uid}"


def _actor_name(actor) -> str:
    return actor.display_name or actor.username or f"用户{actor.id}"


def _selectable_user_ids(actor, competition_id):
    """当前发布者可选收件人 id 列表。

    - 超管：传 competitionId 时为「所选比赛内账号 ∪ 无归属比赛的系统账号」；
      不传则为全部用户（全站广播）。
    - 其余角色：仅同比赛用户。
    """
    from apps.users.models import User

    qs = User.objects.all()
    if actor.role == "SUPER_ADMIN":
        if competition_id is not None:
            qs = qs.filter(Q(competition_id=competition_id) | Q(competition_id__isnull=True))
    else:
        qs = qs.filter(competition_id=actor.competition_id)
    return list(qs.values_list("id", flat=True).order_by("id"))


def _delete_message_images(raw) -> None:
    """解析消息 images(JSON 字符串) 并逐个删除落盘文件（忽略缺失 / 异常）。"""
    arr = parse_json_array(raw)
    upload_dir = _msg_image_dir()
    for it in arr:
        if not isinstance(it, dict):
            continue
        filename = it.get("filename")
        if not isinstance(filename, str) or not filename:
            continue
        try:
            p = os.path.join(upload_dir, os.path.basename(filename))
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            # 文件删除失败不影响主流程
            pass


def _parse_query_competition_id(params):
    """解析可选 competitionId 查询参数，未传 / 非法时分别返回 (None, error)。"""
    raw = params.get("competitionId")
    if raw is None or raw == "":
        return None, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, BusinessError("competitionId 非法", code=400, status_code=400)


# ==================== 收件箱 / 已发布 / 未读 ====================
class InboxView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def get(self, request):
        user = request.user
        page, page_size, skip = parse_pagination(request.query_params)
        qs = (
            MessageRecipient.objects.filter(user_id=user.id)
            .select_related("message")
            .order_by("-created_at")
        )
        total = qs.count()
        recipients = list(qs[skip : skip + page_size])
        sender_ids = {r.message.sender_id for r in recipients}
        sender_map = _sender_name_map(sender_ids)
        items = [
            serialize_inbox_item(r, _resolve_name(sender_map, r.message.sender_id))
            for r in recipients
        ]
        return Response(paginated_response(items, total, page, page_size))


class SentView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def get(self, request):
        actor = request.user
        qs = (
            Message.objects.filter(sender_id=actor.id)
            .annotate(_recipients_count=Count("recipients"))
            .order_by("-created_at")[:_SENT_TAKE]
        )
        sender_name = _actor_name(actor)
        items = [serialize_sent_item(m, sender_name, m._recipients_count) for m in qs]
        return Response(items)


class UnreadCountView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def get(self, request):
        count = MessageRecipient.objects.filter(
            user_id=request.user.id, read=False
        ).count()
        return Response({"count": count})


class SelectableUsersView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def get(self, request):
        actor = request.user
        cid, err = _parse_query_competition_id(request.query_params)
        if err is not None:
            raise err
        user_ids = _selectable_user_ids(actor, cid)
        from apps.users.models import User

        rows = (
            User.objects.filter(id__in=user_ids)
            .order_by("id")
            .values("id", "username", "display_name", "role", "competition_id")
        )
        return Response(
            [
                {
                    "id": u["id"],
                    "username": u["username"],
                    "displayName": u["display_name"],
                    "role": u["role"],
                    "competitionId": u["competition_id"],
                }
                for u in rows
            ]
        )


# ==================== 已读标记 ====================
class MarkReadView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def patch(self, request, pk):
        try:
            rec = MessageRecipient.objects.get(
                message_id=pk, user_id=request.user.id
            )
        except MessageRecipient.DoesNotExist:
            raise BusinessError("消息不存在或不属于你", code=404, status_code=404)
        if not rec.read:
            rec.read = True
            rec.read_at = timezone.now()
            rec.save(update_fields=["read", "read_at"])
        return Response({"message": "已标记为已读"})


class ReadAllView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def post(self, request):
        now = timezone.now()
        MessageRecipient.objects.filter(
            user_id=request.user.id, read=False
        ).update(read=True, read_at=now)
        return Response({"message": "已全部标记为已读"})


# ==================== 图片上传 ====================
class UploadImageView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:manage")
    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            raise BusinessError("未收到文件", code=400, status_code=400)
        mime = (file.content_type or "").lower()
        if mime not in _IMAGE_MIME_EXT:
            raise BusinessError(
                "仅支持 PNG / JPEG / GIF / WebP 图片", code=400, status_code=400
            )
        ext = _IMAGE_MIME_EXT[mime]
        upload_dir = _msg_image_dir()
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(upload_dir, safe_name)
        with open(dest, "wb") as out:
            for chunk in file.chunks():
                out.write(chunk)
        return Response(
            {"url": f"/uploads/message-images/{safe_name}", "filename": safe_name}
        )


# ==================== 列表 + 发布 / 详情 + 删除 ====================
class CollectionView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def get(self, request):
        """当前用户已发布消息列表（可选 competitionId 过滤，分页）。"""
        actor = request.user
        cid, err = _parse_query_competition_id(request.query_params)
        if err is not None:
            raise err
        page, page_size, skip = parse_pagination(request.query_params)
        qs = Message.objects.filter(sender_id=actor.id).order_by("-created_at")
        if cid is not None:
            qs = qs.filter(competition_id=cid)
        total = qs.count()
        msgs = list(qs[skip : skip + page_size])
        items = [message_to_dict(m) for m in msgs]
        return Response(paginated_response(items, total, page, page_size))

    @require_permissions("message:manage")
    def post(self, request):
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        actor = request.user

        # 超管可经 dto.competitionId 把收件范围收敛到指定比赛；归属账号忽略该字段
        dto_competition_id = data.get("competitionId")
        selectable_ids = _selectable_user_ids(actor, dto_competition_id)
        selectable_set = set(selectable_ids)

        recipient_ids: set[int] = set()
        target_user_ids = data.get("targetUserIds") or []
        for uid in target_user_ids:
            if uid not in selectable_set:
                raise BusinessError(
                    f"收件人 {uid} 不在你可发布的范围内",
                    code=403,
                    status_code=403,
                )
            recipient_ids.add(uid)
        if data.get("targetsAll"):
            recipient_ids.update(selectable_set)
        if not recipient_ids:
            raise BusinessError("未选择任何接收人", code=400, status_code=400)
        if len(recipient_ids) > _MAX_RECIPIENTS:
            raise BusinessError(
                f"收件人数量超过上限（{_MAX_RECIPIENTS}）", code=400, status_code=400
            )

        images = data.get("images") or []
        recipient_id_list = list(recipient_ids)

        with transaction.atomic():
            message = Message.objects.create(
                title=data["title"],
                content=data["content"],
                sender_id=actor.id,
                competition_id=actor.competition_id,
                targets_all=bool(data.get("targetsAll")),
                target_user_ids=json.dumps(target_user_ids),
                images=json.dumps(images),
            )
            MessageRecipient.objects.bulk_create(
                [
                    MessageRecipient(message_id=message.id, user_id=uid)
                    for uid in recipient_id_list
                ]
            )

        sender_name = _actor_name(actor)
        # 实时推送：向每位在线收件人私有房间推送新消息（离线用户登录后于收件箱看到未读）
        emit_to_users(
            recipient_id_list,
            "message:new",
            {
                "id": message.id,
                "title": message.title,
                "content": message.content,
                "senderId": message.sender_id,
                "senderName": sender_name,
                "createdAt": message.created_at.isoformat(),
                "images": images,
            },
        )
        # 统一资源变更事件（任务要求：resource:changed "message"）
        emit_resource_changed_to_users(
            "message",
            message.id,
            recipient_id_list,
            "created",
            competition_id=message.competition_id,
        )

        return Response({**message_to_dict(message), "senderName": sender_name})


class ItemView(APIView):
    permission_classes = (IsAuthenticated, PermissionsPermission)

    @require_permissions("message:view")
    def get(self, request, pk):
        try:
            msg = Message.objects.get(pk=pk)
        except Message.DoesNotExist:
            raise BusinessError("消息不存在", code=404, status_code=404)
        sender_map = _sender_name_map([msg.sender_id])
        return Response(
            {**message_to_dict(msg), "senderName": _resolve_name(sender_map, msg.sender_id)}
        )

    @require_permissions("message:manage")
    def delete(self, request, pk):
        actor = request.user
        try:
            msg = Message.objects.get(pk=pk)
        except Message.DoesNotExist:
            raise BusinessError("消息不存在", code=404, status_code=404)
        if actor.role != "SUPER_ADMIN" and msg.sender_id != actor.id:
            raise BusinessError(
                "只能删除自己发布的消息", code=403, status_code=403
            )
        # 删除前抓取收件人 id（删除后用于实时通知）+ 清理落盘图片
        recipient_ids = list(msg.recipients.values_list("user_id", flat=True))
        competition_id = msg.competition_id
        message_id = msg.id
        _delete_message_images(msg.images)
        msg.delete()  # 级联删除收件人记录
        emit_resource_changed_to_users(
            "message", message_id, recipient_ids, "deleted", competition_id=competition_id
        )
        return Response({"message": "已删除"})
