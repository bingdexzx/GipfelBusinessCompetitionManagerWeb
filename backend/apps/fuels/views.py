"""燃料视图：基于通用 CRUD 基类组合。

权限：view=data:fuel:view，edit=data:fuel:edit。
路由由 backend.urls 以 path("api/", include("apps.fuels.urls")) 引入。
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

from .models import Fuel
from .serializers import FuelSerializer


class _CrudBase:
    model = Fuel
    serializer_class = FuelSerializer
    view_permission = "data:fuel:view"
    edit_permission = "data:fuel:edit"
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
    def get_delete_impact(self, instance: Fuel) -> dict:
        from apps.vehicles.models import Vehicle

        count = Vehicle.objects.filter(fuel_id=instance.id).count()
        return {
            "name": str(instance),
            "children": [{"label": "关联的载具", "count": count}],
        }
