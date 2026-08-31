"""统一响应包装：对应原 NestJS ResponseInterceptor。

成功：{ code:0, message:"成功", data }
错误：{ code:<http或业务码>, message:"中文提示", data:null }

所有 REST 响应都经 JSONRenderer 包装为该格式。
"""
from __future__ import annotations

from rest_framework.renderers import JSONRenderer as DRFJSONRenderer


class JSONRenderer(DRFJSONRenderer):
    """把 DRF 响应数据统一包装为 { code, message, data }。

    - 视图直接返回 dict/list/None：视为 data，code=0, message="成功"
    - 视图显式返回已包装结构（含 'code' 键）：原样返回
    - 异常由 exception_handler 处理后同样走此渲染器
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # 已包装（含 code 键）原样返回，避免双重包装
        if isinstance(data, dict) and "code" in data:
            return super().render(data, accepted_media_type, renderer_context)

        wrapped = {
            "code": 0,
            "message": "成功",
            "data": data,
        }
        return super().render(wrapped, accepted_media_type, renderer_context)


def success(data=None, message: str = "成功"):
    """视图内显式构造成功响应（通常直接 return data 即可，此函数用于需要自定义 message）。"""
    return {"code": 0, "message": message, "data": data}


def error(code: int, message: str, data=None):
    """构造错误响应体（供异常处理器使用）。"""
    return {"code": code, "message": message, "data": data}
