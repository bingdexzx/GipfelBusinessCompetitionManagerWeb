"""自定义 CORS 中间件：反射本地/私网来源并带凭据，公网须白名单。

由于 corsheaders 不支持「反射私网来源」动态判断，此处接管 CORS 响应头。
settings.MIDDLEWARE 中 corsheaders.CorsMiddleware 仍保留用于 OPTIONS 预检，
本中间件在 SecurityHeaders 之后执行，确保响应头一致。
"""
from __future__ import annotations

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class DynamicCorsMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        origin = request.headers.get("Origin", "")
        if not origin:
            return response
        if not settings.cors_origin_validator(origin):
            return response
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Credentials"] = "true"
        # 允许前端使用的响应头
        response["Access-Control-Expose-Headers"] = "Content-Length, Content-Type"
        return response

    def process_request(self, request):
        # OPTIONS 预检由 corsheaders 处理；此处不拦截
        return None
