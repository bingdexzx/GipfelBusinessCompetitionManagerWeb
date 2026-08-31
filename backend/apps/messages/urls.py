"""消息中心路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约（与 frontend messagesApi 一致）：
- GET    /api/messages                          当前用户已发布列表（分页，可选 competitionId）
- POST   /api/messages                          发布消息
- GET    /api/messages/inbox                    收件箱（分页）
- GET    /api/messages/sent                     已发布（含 _count.recipients + senderName）
- GET    /api/messages/unread-count             未读计数
- GET    /api/messages/selectable-users         可选收件人（可选 competitionId）
- POST   /api/messages/read-all                 全部标记已读
- POST   /api/messages/upload-image            上传图片
- GET    /api/messages/:id                      详情
- DELETE /api/messages/:id                      删除（级联收件人）
- PATCH  /api/messages/:id/read                 标记单条已读

注意：静态子路径必须排在 <int:pk> 之前，否则 /messages/inbox 等会被
/messages/<int:pk> 捕获（inbox 非整数 → 404）。
"""
from django.urls import path

from .views import (
    CollectionView,
    InboxView,
    ItemView,
    MarkReadView,
    ReadAllView,
    SelectableUsersView,
    SentView,
    UnreadCountView,
    UploadImageView,
)

app_name = "messages"

urlpatterns = [
    path("messages/inbox", InboxView.as_view(), name="inbox"),
    path("messages/sent", SentView.as_view(), name="sent"),
    path("messages/unread-count", UnreadCountView.as_view(), name="unread-count"),
    path("messages/selectable-users", SelectableUsersView.as_view(), name="selectable-users"),
    path("messages/read-all", ReadAllView.as_view(), name="read-all"),
    path("messages/upload-image", UploadImageView.as_view(), name="upload-image"),
    path("messages", CollectionView.as_view(), name="collection"),
    path("messages/<int:pk>/read", MarkReadView.as_view(), name="mark-read"),
    path("messages/<int:pk>", ItemView.as_view(), name="item"),
]
