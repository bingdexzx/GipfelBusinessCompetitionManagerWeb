"""生产线视图：基于通用 CRUD 基类组合。

权限：view=data:productionLine:view，edit=data:productionLine:edit。
路由由 backend.urls 以 path("api/", include("apps.production_lines.urls")) 引入。
"""
from __future__ import annotations

from apps.common.base_crud import (
    CrudCreateView,
    CrudDeleteView,
    CrudDetailView,
    CrudListView,
    CrudUpdateView,
    make_collection_view,
    make_item_view,
)

from .models import ProductionLine
from .serializers import ProductionLineSerializer


class _CrudBase:
    model = ProductionLine
    serializer_class = ProductionLineSerializer
    view_permission = "data:productionLine:view"
    edit_permission = "data:productionLine:edit"
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
