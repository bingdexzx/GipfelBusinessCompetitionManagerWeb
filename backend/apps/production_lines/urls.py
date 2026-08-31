"""生产线路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/production-lines      列表
- POST   /api/production-lines      创建
- GET    /api/production-lines/:id  详情
- PUT    /api/production-lines/:id  更新
- PATCH  /api/production-lines/:id  部分更新
- DELETE /api/production-lines/:id  删除
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ItemAPIView

app_name = "production_lines"

urlpatterns = crud_urlpatterns(
    "production-lines",
    CollectionAPIView,
    ItemAPIView,
)
