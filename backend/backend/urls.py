"""
URL 路由：聚合所有 REST 模块 + 静态资源 + 健康检查 / 版本。

所有业务路由前缀 /api，与原 NestJS app.setGlobalPrefix('api') 一致。
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

from apps.auth.views import HealthView, VersionView

urlpatterns = [
    # 管理后台（Django admin）：仅用于临时排查/修数，业务管理仍走前端 Vue 界面
    path("admin/", admin.site.urls),
    # 健康检查与版本（无鉴权，对应原 health.controller / version.controller）
    path("api/health", HealthView.as_view(), name="health"),
    path("api/version", VersionView.as_view(), name="version"),
    # 认证与用户
    path("api/auth/", include("apps.auth.urls")),
    # users 挂在 api/ 下（与 competitions 一致），子路由非空，避免 POST /api/users 触发尾随斜杠重定向
    path("api/", include("apps.users.urls")),
    # 业务模块（保持原 NestJS Controller 前缀）
    path("api/", include("apps.competitions.urls")),
    path("api/", include("apps.materials.urls")),
    path("api/", include("apps.parts.urls")),
    path("api/", include("apps.products.urls")),
    path("api/", include("apps.tech_tree.urls")),
    path("api/", include("apps.maps.urls")),
    path("api/", include("apps.infrastructures.urls")),
    path("api/", include("apps.fuels.urls")),
    path("api/", include("apps.vehicles.urls")),
    path("api/", include("apps.warehouses.urls")),
    path("api/", include("apps.production_lines.urls")),
    path("api/", include("apps.industry_types.urls")),
    path("api/", include("apps.companies.urls")),
    path("api/", include("apps.company_fields.urls")),
    path("api/", include("apps.contracts.urls")),
    path("api/", include("apps.regions.urls")),
    path("api/", include("apps.consumer_demands.urls")),
    path("api/", include("apps.messages.urls")),
    path("api/", include("apps.stock.urls")),
    path("api/", include("apps.files.urls")),
    path("api/", include("apps.audit.urls")),
]

# /uploads 静态托管（CORP cross-origin 由中间件设置）
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 管理后台静态资源（/admin 样式与脚本）。DEBUG=False 时 django.conf.urls.static 不挂载，
# 故此处无条件以 re_path 托管 STATIC_ROOT，仅匹配 /static/，不影响 /api、/uploads、/socket.io。
urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", static_serve, {"document_root": settings.STATIC_ROOT}),
]
