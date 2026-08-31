from django.http import JsonResponse
from django.urls import path
from django.views.decorators.http import require_GET, require_POST

from . import views


@require_GET
def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", views.index, name="index"),
    path("api/health", health, name="health"),
    path("api/csrf/", views.csrf_cookie, name="csrf"),
    path("api/auth/whoami", views.whoami, name="whoami"),
    path("api/auth/login", views.login_view, name="login"),
    path("api/auth/logout", views.logout_view, name="logout"),
    path("api/logs/files", views.log_files, name="log-files"),
    path("api/logs", views.logs_view, name="logs"),
]
