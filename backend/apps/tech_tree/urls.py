"""科技树路由：挂在 /api 前缀下。

- GET/POST  /api/tech-nodes
- GET/PUT/PATCH/DELETE /api/tech-nodes/:id
- GET /api/tech-nodes/:id/impact
"""
from apps.common.base_crud import crud_urlpatterns

from .views import CollectionAPIView, ImpactView, ItemAPIView

app_name = "tech_tree"

urlpatterns = crud_urlpatterns(
    "tech-nodes", CollectionAPIView, ItemAPIView, ImpactView
)
