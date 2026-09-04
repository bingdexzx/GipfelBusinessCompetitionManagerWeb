"""日志查看器视图：登录（绑定 Django 后台超级管理员）、会话、日志读取。"""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import logutil


def _json_body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        return {}


def _superuser_or_401(request):
    """校验已登录且为 Django 后台超级管理员；否则返回 JsonResponse(401)。"""
    u = request.user
    if not (u.is_authenticated and getattr(u, "is_superuser", False)):
        return JsonResponse({"ok": False, "message": "未登录或无管理员权限"}, status=401)
    return None


def _frontend_url(request) -> str:
    """前端主站地址：优先 .env 的 LOGVIEWER_FRONTEND_URL；缺省按请求 Host 推导。

    日志查看器挂在 log.<域名>（域名部署）或 :8120（纯 IP 部署），
    前端主站在 <域名>（:80/:443）或 :80，故剥掉 log. 前缀或 :8120 端口即得主站。
    本地开发（回环地址）前端在 vite dev 的 :5173，剥掉 :8120 后需补该端口，
    否则弹回 127.0.0.1:80 会出现白屏。
    """
    cfg = (getattr(settings, "LOGVIEWER_FRONTEND_URL", "") or "").strip()
    if cfg:
        return cfg
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host()
    if ":" in host:
        host = host.rsplit(":", 1)[0]
    if host.startswith("log."):
        host = host[len("log."):]
    if host in ("127.0.0.1", "localhost") and scheme == "http":
        return f"{scheme}://{host}:5173/"
    return f"{scheme}://{host}/"


def _frontend_redirect(request) -> HttpResponseRedirect:
    """直连（无有效令牌）自动跳转回前端主站 SPA，避免展示后台或拒绝页。"""
    return HttpResponseRedirect(_frontend_url(request))


# ==================== 页面 ====================
@ensure_csrf_cookie
def index(request):
    """单页应用外壳；附带 ensure_csrf_cookie 写 csrftoken，供登录 POST 使用。

    防直连网关（思路一：入口需令牌）：
    - 携带有效一次性 ?token= → 渲染 SPA（token 保留在 URL，不重定向到干净地址，
      以保证刷新/重开仍带 token；令牌 120s 过期后直连即跳转回前端）；
    - 其余（直接输入网址/书签/无令牌/令牌过期）→ 302 自动重定向回前端主站，
      既不展示后台、也不显示拒绝页，行为与主后端 /admin/ 网关一致。
    """
    token = request.GET.get("token")
    if token:
        signer = TimestampSigner(key=settings.SECRET_KEY, salt=settings.LOGVIEWER_GATE_SALT)
        try:
            signer.unsign(token, max_age=settings.LOGVIEWER_GATE_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return _frontend_redirect(request)
        return render(request, "index.html")

    return _frontend_redirect(request)


@ensure_csrf_cookie
@require_GET
def csrf_cookie(request):
    return JsonResponse({"ok": True})


# ==================== 会话 ====================
@require_GET
def whoami(request):
    u = request.user
    if u.is_authenticated and getattr(u, "is_superuser", False):
        return JsonResponse({"authenticated": True, "username": u.username})
    return JsonResponse({"authenticated": False, "username": None})


@require_POST
def login_view(request):
    """校验 Django 后台超级管理员（auth_user.is_superuser）账号密码。"""
    data = _json_body(request)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return JsonResponse({"ok": False, "message": "用户名和密码不能为空"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_superuser:
        return JsonResponse(
            {"ok": False, "message": "用户名或密码错误，或无管理员权限"}, status=401
        )

    login(request, user)
    return JsonResponse({"ok": True, "username": user.username})


@csrf_exempt
@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


# ==================== 日志 ====================
@require_GET
def log_files(request):
    denied = _superuser_or_401(request)
    if denied:
        return denied
    return JsonResponse({"files": logutil.list_log_files()})


@require_GET
def logs_view(request):
    denied = _superuser_or_401(request)
    if denied:
        return denied
    filename = request.GET.get("file") or logutil.settings.LOG_FILE_NAME
    mode = request.GET.get("mode") or "tail"
    try:
        lines = int(request.GET.get("lines") or 300)
    except ValueError:
        lines = 300
    lines = max(1, min(lines, 5000))
    level = request.GET.get("level") or "ALL"
    q = request.GET.get("q") or ""
    try:
        result = logutil.read_logs(filename, mode=mode, lines=lines, level=level, q=q)
    except ValueError as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)
    return JsonResponse(result)
