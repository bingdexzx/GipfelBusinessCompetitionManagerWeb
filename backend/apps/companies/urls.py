"""公司路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/companies             列表（分页/增量）
- POST   /api/companies             创建
- GET    /api/companies/:id         详情
- PATCH  /api/companies/:id         更新
- DELETE /api/companies/:id         删除
- GET    /api/companies/:id/impact  删除影响
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ImpactView, ItemAPIView

app_name = "companies"

urlpatterns = crud_urlpatterns(
    "companies",
    CollectionAPIView,
    ItemAPIView,
    ImpactView,
)
