"""地图路由：挂在 /api 前缀下。

- GET /api/maps/full
- GET/POST /api/map-node-types, GET/PUT/PATCH/DELETE /api/map-node-types/:id, /impact
- GET/POST /api/path-types, GET/PUT/PATCH/DELETE /api/path-types/:id, /impact
- GET/POST /api/map-nodes, GET/PUT/PATCH/DELETE /api/map-nodes/:id, /impact
- GET/POST /api/map-edges, GET/PUT/PATCH/DELETE /api/map-edges/:id, /impact
"""
from django.urls import path

from apps.common.base_crud import crud_urlpatterns

from .views import (
    MapEdgeCollection,
    MapEdgeImpactView,
    MapEdgeItem,
    MapFullView,
    MapNodeCollection,
    MapNodeImpactView,
    MapNodeItem,
    NodeTypeCollection,
    NodeTypeImpactView,
    NodeTypeItem,
    PathTypeCollection,
    PathTypeImpactView,
    PathTypeItem,
)

app_name = "maps"

urlpatterns = [
    path("maps/full", MapFullView.as_view(), name="map-full"),
]
urlpatterns += crud_urlpatterns("map-node-types", NodeTypeCollection, NodeTypeItem, NodeTypeImpactView)
urlpatterns += crud_urlpatterns("path-types", PathTypeCollection, PathTypeItem, PathTypeImpactView)
urlpatterns += crud_urlpatterns("map-nodes", MapNodeCollection, MapNodeItem, MapNodeImpactView)
urlpatterns += crud_urlpatterns("map-edges", MapEdgeCollection, MapEdgeItem, MapEdgeImpactView)
