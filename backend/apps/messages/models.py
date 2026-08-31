"""消息中心模型：对应原 Prisma Message / MessageRecipient。

收件人在发布时一次性结算为 MessageRecipient 行（「本比赛全体」与显式选人
取并集去重），因此收件箱与未读状态以 MessageRecipient 为权威来源，与比赛
隔离逻辑解耦——离线用户登录后也能在收件箱看到消息并带未读红点。
"""
from django.db import models


class Message(models.Model):
    """消息：发布者一次推送的标题 + 正文 + 图片。删除时级联删除其收件人记录。"""

    title = models.CharField(max_length=255)
    content = models.TextField()
    # Prisma 字段 senderId；按需查用户昵称，不建立反向关系以外的耦合
    sender = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    # 归属比赛（上下文展示 + 选人默认范围）；super-admin 跨比赛发布时为 null
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
    )
    # 是否「全体（可选范围内用户）」：true 时收件人 = 所有可选用户
    targets_all = models.BooleanField(default=False)
    # 显式指定收件人用户 id（JSON 数组，int）；与 targetsAll 取并集后去重
    target_user_ids = models.TextField(default="[]")
    # 消息附带图片（JSON 数组，元素 {url, filename}）；删除消息时清理落盘文件
    images = models.TextField(null=True, blank=True, default="[]")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "messages"
        indexes = [
            models.Index(fields=["competition"]),
            models.Index(fields=["competition", "updated_at"]),
            models.Index(fields=["sender"]),
        ]

    def __str__(self):
        return self.title


class MessageRecipient(models.Model):
    """消息与收件人的关联（含已读状态）。发布时按解析后的收件人批量写入。"""

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    # Prisma 字段 receivedMessages
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="received_messages",
    )
    read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "message_recipients"
        unique_together = (("message", "user"),)
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return f"message {self.message_id} -> user {self.user_id}"
