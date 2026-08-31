"""合同路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/contract-types              列表（增量）
- POST   /api/contract-types              创建
- GET    /api/contract-types/:id          详情
- PATCH  /api/contract-types/:id          更新
- DELETE /api/contract-types/:id          删除
- GET    /api/contracts                    列表（分页/增量/公司范围过滤）
- POST   /api/contracts                    创建
- GET    /api/contracts/:id                详情
- DELETE /api/contracts/:id                删除（仅超管）
- POST   /api/contracts/:id/execute       执行（会签落账）
- PATCH  /api/contracts/:id/party-numbers 分步补全编号
- POST   /api/contracts/:id/precheck       预检
- PATCH  /api/contracts/:id/status         标记状态（仅 TERMINATED）
- GET    /api/contracts/:id/impact         删除影响
"""
from django.urls import path

from .views import (
    ContractCollectionAPIView,
    ContractExecuteAPIView,
    ContractImpactAPIView,
    ContractItemAPIView,
    ContractPartyNumbersAPIView,
    ContractPrecheckAPIView,
    ContractStatusAPIView,
    ContractTypeCollectionAPIView,
    ContractTypeItemAPIView,
)

app_name = "contracts"

urlpatterns = [
    # 合同类型（全局，无比赛域）
    path("contract-types", ContractTypeCollectionAPIView.as_view(), name="contract-types-collection"),
    path("contract-types/<int:pk>", ContractTypeItemAPIView.as_view(), name="contract-types-item"),
    # 合同（比赛级）
    path("contracts", ContractCollectionAPIView.as_view(), name="contracts-collection"),
    path("contracts/<int:pk>", ContractItemAPIView.as_view(), name="contracts-item"),
    path("contracts/<int:pk>/execute", ContractExecuteAPIView.as_view(), name="contracts-execute"),
    path("contracts/<int:pk>/party-numbers", ContractPartyNumbersAPIView.as_view(), name="contracts-party-numbers"),
    path("contracts/<int:pk>/precheck", ContractPrecheckAPIView.as_view(), name="contracts-precheck"),
    path("contracts/<int:pk>/status", ContractStatusAPIView.as_view(), name="contracts-status"),
    path("contracts/<int:pk>/impact", ContractImpactAPIView.as_view(), name="contracts-impact"),
]
