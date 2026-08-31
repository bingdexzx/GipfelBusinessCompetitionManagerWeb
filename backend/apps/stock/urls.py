"""股票系统路由：挂在 /api 前缀下（无尾随斜杠）。

路由顺序：静态子路径置于 <id> 之前，避免被 <int:pk> 误匹配。
"""
from django.urls import path

from .views import (
    AccountCollectionView,
    AccountHoldingsView,
    AccountItemView,
    AccountListView,
    AccountOverviewView,
    AdvanceRoundView,
    CandlesView,
    CollectionView,
    HoldingListView,
    ItemView,
    OrderCollectionView,
    OrderItemView,
    OrderListView,
    PbSourcesView,
)

app_name = "stock"

urlpatterns = [
    # 静态子路径（须置于 <id> 之前）
    path("stocks/pb-sources", PbSourcesView.as_view(), name="pb-sources"),
    path("stocks/accounts/list", AccountListView.as_view(), name="account-list"),
    path("stocks/accounts/overview", AccountOverviewView.as_view(), name="account-overview"),
    path("stocks/accounts", AccountCollectionView.as_view(), name="account-collection"),
    path("stocks/accounts/<int:pk>", AccountItemView.as_view(), name="account-item"),
    path("stocks/accounts/<int:pk>/holdings", AccountHoldingsView.as_view(), name="account-holdings"),
    path("stocks/orders/list", OrderListView.as_view(), name="order-list"),
    path("stocks/orders", OrderCollectionView.as_view(), name="order-collection"),
    path("stocks/orders/<int:pk>", OrderItemView.as_view(), name="order-item"),
    path("stocks/holdings/list", HoldingListView.as_view(), name="holding-list"),
    path("stocks/advance-round", AdvanceRoundView.as_view(), name="advance-round"),
    # 股票基础 CRUD
    path("stocks", CollectionView.as_view(), name="collection"),
    path("stocks/<int:pk>/candles", CandlesView.as_view(), name="candles"),
    path("stocks/<int:pk>", ItemView.as_view(), name="item"),
]
