"""原料视图：基于通用 CRUD 基类组合。

权限：view=data:material:view，edit=data:material:edit。
路由由 backend.urls 以 path("api/", include("apps.materials.urls")) 引入。
"""
from __future__ import annotations

from apps.common.base_crud import (
    CrudCreateView,
    CrudDeleteView,
    CrudDetailView,
    CrudImpactView,
    CrudListView,
    CrudUpdateView,
    make_collection_view,
    make_item_view,
)

from .models import Material
from .serializers import MaterialSerializer


class _CrudBase:
    model = Material
    serializer_class = MaterialSerializer
    view_permission = "data:material:view"
    edit_permission = "data:material:edit"
    unique_fields = ["competitionId", "name"]


class ListView(_CrudBase, CrudListView):
    pass


class CreateView(_CrudBase, CrudCreateView):
    pass


CollectionAPIView = make_collection_view(ListView, CreateView)


class DetailView(_CrudBase, CrudDetailView):
    pass


class UpdateView(_CrudBase, CrudUpdateView):
    pass


class DeleteView(_CrudBase, CrudDeleteView):
    pass


ItemAPIView = make_item_view(DetailView, UpdateView, DeleteView)


class ImpactView(_CrudBase, CrudImpactView):
    def get_delete_impact(self, instance: Material) -> dict:
        from apps.parts.models import PartMaterial

        count = PartMaterial.objects.filter(material_id=instance.id).count()
        return {
            "name": str(instance),
            "children": [{"label": "关联的零件配比关系", "count": count}],
        }
