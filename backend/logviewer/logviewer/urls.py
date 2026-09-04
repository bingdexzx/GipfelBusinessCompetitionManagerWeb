from django.conf import settings
from django.http import JsonResponse
from django.urls import path, re_path
from django.views.decorators.http import require_GET, require_POST
from django.views.static import serve as static_serve

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

# 静态资源：DEBUG=False（生产默认）时 Django 不自动托管，与主后端同法无条件挂载。
# 页面引用 /static/vendor/*、/static/app.css|js，源文件在 logviewer/static/（单目录、
# 无应用级静态资源，直接指向源目录即可，无需 collectstatic）。
urlpatterns += [
    re_path(
        r"^static/(?P<path>.*)$",
        static_serve,
        {"document_root": str(settings.BASE_DIR / "static")},
    ),
]
