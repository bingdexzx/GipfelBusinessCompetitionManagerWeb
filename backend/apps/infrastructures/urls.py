"""基建路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/infrastructures      列表
- POST   /api/infrastructures      创建
- GET    /api/infrastructures/:id  详情
- PUT    /api/infrastructures/:id  更新
- PATCH  /api/infrastructures/:id  部分更新
- DELETE /api/infrastructures/:id  删除
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ItemAPIView

app_name = "infrastructures"

urlpatterns = crud_urlpatterns(
    "infrastructures",
    CollectionAPIView,
    ItemAPIView,
)
