"""区域路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/regions                              列表（分页/增量）
- POST   /api/regions                              创建
- GET    /api/regions/map-overview                 地图概览聚合
- PUT    /api/regions/by-name/<name>/overview-cards 按名保存概览卡片
- GET    /api/regions/:id                          详情（含 companies）
- PATCH  /api/regions/:id                          更新
- DELETE /api/regions/:id                          删除
- GET    /api/regions/:id/companies                区域内公司
- GET    /api/regions/:id/overview                 概览（解析后卡片）
- PUT    /api/regions/:id/overview-cards           保存概览卡片

注意路由顺序：map-overview / by-name/<name> 必须在 <int:pk> 之前。
"""
from django.urls import path

from .views import (
    CollectionView,
    CompaniesView,
    ItemView,
    MapOverviewView,
    OverviewView,
    SaveByNameView,
    SaveOverviewCardsView,
)

app_name = "regions"

urlpatterns = [
    path("regions", CollectionView.as_view(), name="regions-collection"),
    path("regions/map-overview", MapOverviewView.as_view(), name="regions-map-overview"),
    path(
        "regions/by-name/<str:name>/overview-cards",
        SaveByNameView.as_view(),
        name="regions-save-by-name",
    ),
    path("regions/<int:pk>", ItemView.as_view(), name="regions-item"),
    path("regions/<int:pk>/companies", CompaniesView.as_view(), name="regions-companies"),
    path("regions/<int:pk>/overview", OverviewView.as_view(), name="regions-overview"),
    path(
        "regions/<int:pk>/overview-cards",
        SaveOverviewCardsView.as_view(),
        name="regions-overview-cards",
    ),
]
