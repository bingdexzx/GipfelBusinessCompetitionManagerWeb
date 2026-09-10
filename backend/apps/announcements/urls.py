"""更新公告路由。

- GET    /api/announcements          列表（非超管仅返回 isActive=true）
- POST   /api/announcements          创建（仅超管）
- GET    /api/announcements/:id      详情
- PATCH  /api/announcements/:id      编辑（仅超管）
- DELETE /api/announcements/:id      删除（仅超管）
"""
from django.urls import path

from .views import CollectionView, ItemView

app_name = "announcements"

urlpatterns = [
    path("announcements", CollectionView.as_view(), name="collection"),
    path("announcements/<int:pk>", ItemView.as_view(), name="item"),
]
