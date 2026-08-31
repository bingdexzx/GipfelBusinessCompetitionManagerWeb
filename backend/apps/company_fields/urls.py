"""公司产业字段路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET /api/company-fields/:companyId           读取字段值
- PUT /api/company-fields/:companyId           批量写入
- PUT /api/company-fields/:companyId/:fieldId  单字段写入
"""
from django.urls import path

from .views import CompanyFieldItemView, CompanyFieldsView

app_name = "company_fields"

urlpatterns = [
    path(
        "company-fields/<int:company_id>",
        CompanyFieldsView.as_view(),
        name="company-fields-collection",
    ),
    path(
        "company-fields/<int:company_id>/<int:field_id>",
        CompanyFieldItemView.as_view(),
        name="company-fields-item",
    ),
]
