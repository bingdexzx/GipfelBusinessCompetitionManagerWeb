"""认证路由。

由 backend.urls 以 path("api/auth/", include("apps.auth.urls")) 引入，
故本文件路由前缀为 api/auth/。
"""
from django.urls import path

from .views import (
    BackendTokenView,
    ChangePasswordView,
    LoginView,
    LogViewerTokenView,
    MeView,
)

urlpatterns = [
    path("login", LoginView.as_view(), name="auth-login"),
    path("me", MeView.as_view(), name="auth-me"),
    path("change-password", ChangePasswordView.as_view(), name="auth-change-password"),
    path("logviewer-token", LogViewerTokenView.as_view(), name="auth-logviewer-token"),
    path("backend-token", BackendTokenView.as_view(), name="auth-backend-token"),
]
