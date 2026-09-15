"""比赛准备路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET  /api/preparations/plan                              准备清单（统计 + 体检 + 明细）
- GET  /api/preparations/plan/export?format=markdown|json   导出归档文件（附件下载）
- GET  /api/preparations/scopes                            可选导出/导入分组
- GET  /api/preparations/archive/export?scope=all|<分组>    按分组导出可再导入的 JSON
- POST /api/preparations/archive/import?scope=<分组>&dryRun=  导入归档（默认仅预览）
"""
from django.urls import path

from .views import (
    PreparationArchiveExportAPIView,
    PreparationArchiveImportAPIView,
    PreparationExportAPIView,
    PreparationPlanAPIView,
    PreparationScopesAPIView,
)

app_name = "preparation"

urlpatterns = [
    path("preparations/plan", PreparationPlanAPIView.as_view(), name="preparations-plan"),
    path("preparations/plan/export", PreparationExportAPIView.as_view(), name="preparations-export"),
    path("preparations/scopes", PreparationScopesAPIView.as_view(), name="preparations-scopes"),
    path(
        "preparations/archive/export",
        PreparationArchiveExportAPIView.as_view(),
        name="preparations-archive-export",
    ),
    path(
        "preparations/archive/import",
        PreparationArchiveImportAPIView.as_view(),
        name="preparations-archive-import",
    ),
]
