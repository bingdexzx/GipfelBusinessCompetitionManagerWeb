"""认证路由：对应原 NestJS AuthController 的 /auth/* 端点。

由 backend.urls 以 path("api/auth/", include("apps.auth.urls")) 引入，
故本文件路由前缀为 api/auth/。
"""
from django.urls import path

from .views import ChangePasswordView, LoginView, MeView

urlpatterns = [
    path("login", LoginView.as_view(), name="auth-login"),
    path("me", MeView.as_view(), name="auth-me"),
    path("change-password", ChangePasswordView.as_view(), name="auth-change-password"),
]
