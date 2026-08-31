"""用户路由：挂在 /api 前缀下（与 competitions 一致，子路由非空、无尾随斜杠）。

由 backend.urls 以 path("api/", include("apps.users.urls")) 引入，
故本文件路由前缀为 api/。前端契约：
- GET    /api/users                  列表
- POST   /api/users                  创建
- GET    /api/users/:id              详情
- PATCH  /api/users/:id              更新
- PATCH  /api/users/:id/password     重置密码
- DELETE /api/users/:id              删除
- POST   /api/users/:id/permissions  授予权限
"""
from django.urls import path

from .views import (
    UserCollectionAPIView,
    UserItemAPIView,
    UserPasswordView,
    UserPermissionsView,
)

app_name = "users"

urlpatterns = [
    path("users", UserCollectionAPIView.as_view(), name="user-collection"),
    path("users/<int:pk>", UserItemAPIView.as_view(), name="user-item"),
    path(
        "users/<int:pk>/password",
        UserPasswordView.as_view(),
        name="user-password",
    ),
    path(
        "users/<int:pk>/permissions",
        UserPermissionsView.as_view(),
        name="user-permissions",
    ),
]
