"""零件路由：挂在 /api 前缀下（无尾随斜杠）。

由 backend.urls 以 path("api/", include("apps.parts.urls")) 引入，故本文件路由
前缀为 api/。前端契约：
- GET/POST            /api/parts                  列表 / 创建
- GET/PUT/PATCH/DELETE /api/parts/:id             详情 / 更新 / 删除
- GET                 /api/parts/:id/impact       删除影响
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ImpactAPIView, ItemAPIView

app_name = "parts"

urlpatterns = crud_urlpatterns("parts", CollectionAPIView, ItemAPIView, ImpactAPIView)
