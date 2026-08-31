"""燃料路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/fuels             列表
- POST   /api/fuels             创建
- GET    /api/fuels/:id         详情
- PUT    /api/fuels/:id         更新
- PATCH  /api/fuels/:id         部分更新
- DELETE /api/fuels/:id         删除
- GET    /api/fuels/:id/impact  删除影响
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ImpactView, ItemAPIView

app_name = "fuels"

urlpatterns = crud_urlpatterns(
    "fuels",
    CollectionAPIView,
    ItemAPIView,
    ImpactView,
)
