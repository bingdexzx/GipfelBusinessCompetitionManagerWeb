"""仓库路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/warehouses      列表
- POST   /api/warehouses      创建
- GET    /api/warehouses/:id  详情
- PUT    /api/warehouses/:id  更新
- PATCH  /api/warehouses/:id  部分更新
- DELETE /api/warehouses/:id  删除
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ItemAPIView

app_name = "warehouses"

urlpatterns = crud_urlpatterns(
    "warehouses",
    CollectionAPIView,
    ItemAPIView,
)
