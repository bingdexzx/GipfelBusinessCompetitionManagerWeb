"""文件应用路由：挂在 /api 前缀下（无尾随斜杠）。

路由顺序：transform 置于 map-background/<...> 之前。
"""
from django.urls import path

from .views import (
    MapBackgroundTransformView,
    MapBackgroundView,
    UploadView,
)

app_name = "files"

urlpatterns = [
    path("files/upload", UploadView.as_view(), name="upload"),
    path("files/map-background/transform", MapBackgroundTransformView.as_view(), name="map-background-transform"),
    path("files/map-background", MapBackgroundView.as_view(), name="map-background"),
]
