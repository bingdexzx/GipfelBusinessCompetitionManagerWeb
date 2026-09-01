"""日志查看器中间件：动态将当前请求来源加入 CSRF_TRUSTED_ORIGINS。

背景：
- Django 4.0+ 的 CsrfViewMiddleware 会校验请求 ``Origin`` 头是否命中 ``CSRF_TRUSTED_ORIGINS``；
  不匹配则 403「Origin checking failed」。
- 本工具以动态 IP:端口（或域名）方式部署，``CSRF_TRUSTED_ORIGINS`` 无法静态写死覆盖所有情况。
- 故改为「运行时把当前 Host 对应的 origin 自动纳入信任」，使同源 POST（如 ``/api/auth/login``）
  不再因 Origin 校验被 403 拒绝，同时仍保留 CSRF 令牌校验（防跨站）。

仅在此内部运维工具使用；若生产锁定具体域名，可直接写死 CSRF_TRUSTED_ORIGINS 而无需本中间件。
"""
from __future__ import annotations

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class LogViewerCsrfTrustMiddleware(MiddlewareMixin):
    """在每个请求的处理前，将请求自身的 origin 追加进 CSRF_TRUSTED_ORIGINS。

    必须位于 django.middleware.csrf.CsrfViewMiddleware 之前，保证 CSRF 校验时该 origin 已受信。
    """

    def process_request(self, request):
        origin = f"{request.scheme}://{request.get_host()}"
        trusted = settings.CSRF_TRUSTED_ORIGINS
        if origin not in trusted:
            trusted.append(origin)
        return None
