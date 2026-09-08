"""公司路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/companies             列表（分页/增量）
- POST   /api/companies             创建
- POST   /api/companies/recompute-all  全量重算计算字段（仅超管）
- GET    /api/companies/:id         详情
- PATCH  /api/companies/:id         更新
- DELETE /api/companies/:id         删除
- GET    /api/companies/:id/impact  删除影响
"""
from django.urls import path

from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ImpactView, ItemAPIView, RecomputeAllAPIView

app_name = "companies"

urlpatterns = crud_urlpatterns(
    "companies",
    CollectionAPIView,
    ItemAPIView,
    ImpactView,
) + [
    # 必须能匹配到：<int:pk> 不会吞掉非数字段 "recompute-all"，追加顺序安全
    path(
        "companies/recompute-all",
        RecomputeAllAPIView.as_view(),
        name="companies-recompute-all",
    ),
]
