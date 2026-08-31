"""产业类型路由：挂在 /api 前缀下（由 backend.urls 以 path("api/", include(...)) 引入）。

前端契约（api/index.ts industryTypesApi）：
- GET    /industry-types                  列表（支持 updatedAfter 增量同步）
- POST   /industry-types                  创建
- GET    /industry-types/:id              详情
- PATCH  /industry-types/:id              更新
- DELETE /industry-types/:id              删除
- GET    /industry-types/:id/fields       字段列表
- POST   /industry-types/:id/fields       创建字段
- PATCH  /industry-types/fields/:fieldId  更新字段
- DELETE /industry-types/fields/:fieldId  删除字段

注意路由顺序：fields/:fieldId 须置于 :id 之前，避免与 :id 路由冲突。
"""
from django.urls import path

from .views import CollectionView, FieldItemView, FieldListView, ItemView

app_name = "industry_types"

urlpatterns = [
    path("industry-types", CollectionView.as_view(), name="industry-type-collection"),
    path(
        "industry-types/fields/<int:field_id>",
        FieldItemView.as_view(),
        name="industry-field-item",
    ),
    path("industry-types/<int:pk>", ItemView.as_view(), name="industry-type-item"),
    path(
        "industry-types/<int:pk>/fields",
        FieldListView.as_view(),
        name="industry-field-collection",
    ),
]
