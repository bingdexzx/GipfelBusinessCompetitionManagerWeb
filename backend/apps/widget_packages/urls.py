"""控件包路由。

- GET    /api/widget-packages          列表（超管含停用）
- POST   /api/widget-packages          上传 zip（仅超管）
- PATCH  /api/widget-packages/:id      启停（仅超管）
- DELETE /api/widget-packages/:id      删除（仅超管）
"""
from django.urls import path

from .views import CollectionView, ItemView

app_name = "widget_packages"

urlpatterns = [
    path("widget-packages", CollectionView.as_view(), name="collection"),
    path("widget-packages/<int:pk>", ItemView.as_view(), name="item"),
]
