"""科技树视图：对应原 NestJS TechTreeController（/api/tech-nodes）。

使用 base_crud 基类 + 覆写删除影响。
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

from .models import TechNode
from .serializers import TechNodeSerializer


class _Base:
    model = TechNode
    serializer_class = TechNodeSerializer
    view_permission = "data:tech:view"
    edit_permission = "data:tech:edit"
    unique_fields = ["competitionId", "name"]


class ListView(_Base, CrudListView):
    pass


class CreateView(_Base, CrudCreateView):
    pass


class DetailView(_Base, CrudDetailView):
    pass


class UpdateView(_Base, CrudUpdateView):
    pass


class DeleteView(_Base, CrudDeleteView):
    pass


class ImpactView(_Base, CrudImpactView):
    def get_delete_impact(self, instance) -> dict:
        children = []
        part_req = 0
        product_req = 0
        # 延迟导入避免循环依赖
        try:
            from apps.parts.models import PartTechRequirement

            part_req = PartTechRequirement.objects.filter(tech_node_id=instance.id).count()
        except Exception:
            pass
        try:
            from apps.products.models import ProductTechRequirement

            product_req = ProductTechRequirement.objects.filter(tech_node_id=instance.id).count()
        except Exception:
            pass
        if part_req > 0:
            children.append({"label": "零件科技需求", "count": part_req})
        if product_req > 0:
            children.append({"label": "产品科技需求", "count": product_req})
        requires = instance.prerequisites.count()
        if requires > 0:
            children.append({"label": "该节点的前提依赖关系", "count": requires})
        required_by = instance.required_by.count()
        if required_by > 0:
            children.append({"label": "以该科技为前提的科技关系", "count": required_by})
        return {"name": instance.name, "children": children}


CollectionAPIView = make_collection_view(ListView, CreateView)
ItemAPIView = make_item_view(DetailView, UpdateView, DeleteView)
