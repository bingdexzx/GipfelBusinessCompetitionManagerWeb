"""地图视图：对应原 NestJS MapController / MapNodeTypeController /
PathTypeController / MapNodeController / MapEdgeController。

- GET /api/maps/full —— 一次性返回完整地图数据
- /api/map-node-types CRUD
- /api/path-types CRUD
- /api/map-nodes CRUD（含 nodeType 嵌套）
- /api/map-edges CRUD（含 fromNode/toNode/pathType 嵌套）
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.base_crud import (
    CrudCreateView,
    CrudDeleteView,
    CrudDetailView,
    CrudImpactView,
    CrudListView,
    CrudUpdateView,
    CrudPermission,
    make_collection_view,
    make_item_view,
)
from apps.common.exceptions import BusinessError
from apps.common.guards import apply_competition_scope

from .models import MapEdge, MapNode, MapNodeType, PathType
from .serializers import (
    MapEdgeSerializer,
    MapNodeSerializer,
    MapNodeTypeSerializer,
    PathTypeSerializer,
)

_PERM = (IsAuthenticated, CrudPermission)


# ==================== /maps/full ====================
class MapFullView(APIView):
    """GET /api/maps/full —— 返回 {nodes, edges, nodeTypes, pathTypes}。"""

    permission_classes = _PERM
    view_permission = "data:map:view"
    edit_permission = "data:map:edit"

    def get(self, request):
        comp_id = request.query_params.get("competitionId")
        nodes_qs = apply_competition_scope(MapNode.objects.all(), request.user, comp_id)
        edges_qs = apply_competition_scope(MapEdge.objects.all(), request.user, comp_id)
        node_types_qs = apply_competition_scope(MapNodeType.objects.all(), request.user, comp_id)
        path_types_qs = apply_competition_scope(PathType.objects.all(), request.user, comp_id)

        nodes = [MapNodeSerializer(n).data for n in nodes_qs.select_related("node_type")]
        edges = [
            MapEdgeSerializer(e).data
            for e in edges_qs.select_related("from_node", "to_node", "path_type")
        ]
        node_types = [MapNodeTypeSerializer(t).data for t in node_types_qs]
        path_types = [PathTypeSerializer(t).data for t in path_types_qs]
        return Response({"nodes": nodes, "edges": edges, "nodeTypes": node_types, "pathTypes": path_types})


# ==================== MapNodeType ====================
class _NodeTypeBase:
    model = MapNodeType
    serializer_class = MapNodeTypeSerializer
    view_permission = "data:map:view"
    edit_permission = "data:map:edit"
    unique_fields = ["competitionId", "name"]


class NodeTypeListView(_NodeTypeBase, CrudListView):
    pass


class NodeTypeCreateView(_NodeTypeBase, CrudCreateView):
    pass


class NodeTypeDetailView(_NodeTypeBase, CrudDetailView):
    pass


class NodeTypeUpdateView(_NodeTypeBase, CrudUpdateView):
    pass


class NodeTypeDeleteView(_NodeTypeBase, CrudDeleteView):
    pass


class NodeTypeImpactView(_NodeTypeBase, CrudImpactView):
    def get_delete_impact(self, instance) -> dict:
        children = []
        node_ids = list(MapNode.objects.filter(node_type_id=instance.id).values_list("id", flat=True))
        if node_ids:
            children.append({"label": "下属地图节点（含其关联地图边）", "count": len(node_ids)})
            edge_count = MapEdge.objects.filter(
                from_node_id__in=node_ids
            ).count() + MapEdge.objects.filter(to_node_id__in=node_ids).count()
            if edge_count > 0:
                children.append({"label": "关联的地图边", "count": edge_count})
        return {"name": instance.name, "children": children}


# ==================== PathType ====================
class _PathTypeBase:
    model = PathType
    serializer_class = PathTypeSerializer
    view_permission = "data:map:view"
    edit_permission = "data:map:edit"
    unique_fields = ["competitionId", "name"]


class PathTypeListView(_PathTypeBase, CrudListView):
    pass


class PathTypeCreateView(_PathTypeBase, CrudCreateView):
    pass


class PathTypeDetailView(_PathTypeBase, CrudDetailView):
    pass


class PathTypeUpdateView(_PathTypeBase, CrudUpdateView):
    pass


class PathTypeDeleteView(_PathTypeBase, CrudDeleteView):
    pass


class PathTypeImpactView(_PathTypeBase, CrudImpactView):
    def get_delete_impact(self, instance) -> dict:
        children = []
        edge_count = MapEdge.objects.filter(path_type_id=instance.id).count()
        if edge_count > 0:
            children.append({"label": "使用该类型的地图边", "count": edge_count})
        try:
            from apps.vehicles.models import VehiclePathType

            vehicle_count = VehiclePathType.objects.filter(path_type_id=instance.id).count()
            if vehicle_count > 0:
                children.append({"label": "载具通行配置", "count": vehicle_count})
        except Exception:
            pass
        return {"name": instance.name, "children": children}


# ==================== MapNode ====================
class _MapNodeBase:
    model = MapNode
    serializer_class = MapNodeSerializer
    view_permission = "data:map:view"
    edit_permission = "data:map:edit"
    unique_fields = ["competitionId", "name"]


class MapNodeListView(_MapNodeBase, CrudListView):
    pass


class MapNodeCreateView(_MapNodeBase, CrudCreateView):
    pass


class MapNodeDetailView(_MapNodeBase, CrudDetailView):
    pass


class MapNodeUpdateView(_MapNodeBase, CrudUpdateView):
    pass


class MapNodeDeleteView(_MapNodeBase, CrudDeleteView):
    pass


class MapNodeImpactView(_MapNodeBase, CrudImpactView):
    def get_delete_impact(self, instance) -> dict:
        children = []
        edge_count = MapEdge.objects.filter(
            from_node_id=instance.id
        ).count() + MapEdge.objects.filter(to_node_id=instance.id).count()
        if edge_count > 0:
            children.append({"label": "关联的地图边", "count": edge_count})
        return {"name": instance.name, "children": children}


# ==================== MapEdge ====================
class _MapEdgeBase:
    model = MapEdge
    serializer_class = MapEdgeSerializer
    view_permission = "data:map:view"
    edit_permission = "data:map:edit"
    unique_fields = []


class MapEdgeListView(_MapEdgeBase, CrudListView):
    pass


class MapEdgeCreateView(_MapEdgeBase, CrudCreateView):
    pass


class MapEdgeDetailView(_MapEdgeBase, CrudDetailView):
    pass


class MapEdgeUpdateView(_MapEdgeBase, CrudUpdateView):
    pass


class MapEdgeDeleteView(_MapEdgeBase, CrudDeleteView):
    pass


class MapEdgeImpactView(_MapEdgeBase, CrudImpactView):
    def get_delete_impact(self, instance) -> dict:
        return {"name": f"边#{instance.id}", "children": []}


# ==================== 组合视图 ====================
NodeTypeCollection = make_collection_view(NodeTypeListView, NodeTypeCreateView)
NodeTypeItem = make_item_view(NodeTypeDetailView, NodeTypeUpdateView, NodeTypeDeleteView)
PathTypeCollection = make_collection_view(PathTypeListView, PathTypeCreateView)
PathTypeItem = make_item_view(PathTypeDetailView, PathTypeUpdateView, PathTypeDeleteView)
MapNodeCollection = make_collection_view(MapNodeListView, MapNodeCreateView)
MapNodeItem = make_item_view(MapNodeDetailView, MapNodeUpdateView, MapNodeDeleteView)
MapEdgeCollection = make_collection_view(MapEdgeListView, MapEdgeCreateView)
MapEdgeItem = make_item_view(MapEdgeDetailView, MapEdgeUpdateView, MapEdgeDeleteView)
