"""原料路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/materials             列表
- POST   /api/materials             创建
- GET    /api/materials/:id         详情
- PUT    /api/materials/:id         更新
- PATCH  /api/materials/:id         部分更新
- DELETE /api/materials/:id         删除
- GET    /api/materials/:id/impact  删除影响
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ImpactView, ItemAPIView

app_name = "materials"

urlpatterns = crud_urlpatterns(
    "materials",
    CollectionAPIView,
    ItemAPIView,
    ImpactView,
)
