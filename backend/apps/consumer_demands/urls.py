"""消费者需求路由：挂在 /api 前缀下（无尾随斜杠）。

前端契约：
- GET    /api/consumer-demands        列表（按区域过滤）
- POST   /api/consumer-demands        创建
- PATCH  /api/consumer-demands/:id    更新
- DELETE /api/consumer-demands/:id    删除
"""
from django.urls import path

from .views import CollectionView, ItemView

app_name = "consumer_demands"

urlpatterns = [
    path("consumer-demands", CollectionView.as_view(), name="consumer-demands-collection"),
    path("consumer-demands/<int:pk>", ItemView.as_view(), name="consumer-demands-item"),
]
