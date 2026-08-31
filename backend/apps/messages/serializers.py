"""消息中心序列化器：camelCase 对齐前端契约。

- MessageSerializer：发布入参校验 + 单条消息表示。
- serialize_sent_item：已发布条目（含 _count.recipients + senderName）。
- serialize_inbox_item：收件箱条目（recipientId / read / readAt + 嵌套 message + senderName）。
"""
from __future__ import annotations

from rest_framework import serializers

from apps.common.json_util import parse_json_array

from .models import Message, MessageRecipient


def _parse_target_user_ids(raw) -> list[int]:
    arr = parse_json_array(raw)
    return [int(i) for i in arr if isinstance(i, (int, float)) and i > 0]


def _parse_images(raw):
    """解析消息 images(JSON 字符串) 为元信息数组；为 null 时返回 null。"""
    if raw is None:
        return None
    arr = parse_json_array(raw)
    return [
        {"url": it["url"], "filename": it["filename"]}
        for it in arr
        if isinstance(it, dict)
        and isinstance(it.get("url"), str)
        and isinstance(it.get("filename"), str)
    ]


def message_to_dict(instance: Message) -> dict:
    """单条消息的 camelCase 表示。"""
    return {
        "id": instance.id,
        "title": instance.title,
        "content": instance.content,
        "senderId": instance.sender_id,
        "competitionId": instance.competition_id,
        "targetsAll": instance.targets_all,
        "targetUserIds": _parse_target_user_ids(instance.target_user_ids),
        "images": _parse_images(instance.images),
        "createdAt": instance.created_at,
        "updatedAt": instance.updated_at,
    }


def serialize_sent_item(instance: Message, sender_name: str, recipients_count: int) -> dict:
    """已发布条目：消息体 + _count.recipients + senderName。"""
    data = message_to_dict(instance)
    data["_count"] = {"recipients": recipients_count}
    data["senderName"] = sender_name
    return data


def serialize_inbox_item(recipient: MessageRecipient, sender_name: str) -> dict:
    """收件箱条目：recipientId / read / readAt + 嵌套 message + senderName。"""
    return {
        "recipientId": recipient.id,
        "read": recipient.read,
        "readAt": recipient.read_at,
        "message": message_to_dict(recipient.message),
        "senderName": sender_name,
    }


class MessageSerializer(serializers.Serializer):
    """发布消息入参：对应原 CreateMessageDto。"""

    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(max_length=255, trim_whitespace=True)
    content = serializers.CharField(allow_blank=True)
    senderId = serializers.IntegerField(read_only=True)
    competitionId = serializers.IntegerField(allow_null=True, required=False)
    targetsAll = serializers.BooleanField(required=False, default=False)
    targetUserIds = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )
    images = serializers.ListField(required=False, allow_null=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Message) -> dict:
        return message_to_dict(instance)

    def validate_title(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("标题不能为空")
        return value

    def validate_content(self, value: str) -> str:
        # 对应原 @MinLength(1)：仅拒绝空字符串，保留正文空白与换行
        if not value:
            raise serializers.ValidationError("内容不能为空")
        return value

    def validate_targetUserIds(self, value) -> list[int]:
        if value is None:
            return []
        return [int(i) for i in value]

    def validate_images(self, value) -> list:
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("images 必须为数组")
        cleaned = []
        for it in value:
            if not isinstance(it, dict):
                raise serializers.ValidationError("images 元素需含 url 与 filename")
            url = it.get("url")
            filename = it.get("filename")
            if not isinstance(url, str) or not isinstance(filename, str):
                raise serializers.ValidationError("images 元素需含 url 与 filename")
            cleaned.append({"url": url, "filename": filename})
        return cleaned
