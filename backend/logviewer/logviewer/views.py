"""日志查看器视图：登录（绑定 Django 后台超级管理员）、会话、日志读取。"""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
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


def _gate_denied() -> HttpResponse:
    """直接访问（无有效令牌、未通过网关）的拒绝页：实现「直接输入网址无法跳转」。"""
    html = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>拒绝访问</title></head><body style='font-family:system-ui,sans-serif;"
        "max-width:560px;margin:12vh auto;padding:0 16px;color:#333'>"
        "<h2 style='color:#c0392b'>拒绝直接访问</h2>"
        "<p>日志查看器仅允许从「系统设置 → 日志查看器」按钮跳转进入。</p>"
        "<p>直接输入网址、书签或复制链接均无法访问。请回到主系统，"
        "以超级管理员身份点击「日志查看器」按钮后再次进入。</p>"
        "</body></html>"
    )
    return HttpResponse(html, status=403, content_type="text/html; charset=utf-8")


# ==================== 页面 ====================
@ensure_csrf_cookie
def index(request):
    """单页应用外壳；附带 ensure_csrf_cookie 写 csrftoken，供登录 POST 使用。

    防直连网关：
    - 已通过网关（会话标记）→ 直接渲染；
    - 携带有效一次性 ?token= → 标记网关通过并重定向到干净地址（避免令牌残留 URL）；
    - 其余（直接输入网址/书签/无令牌）→ 403 拒绝。
    """
    if request.session.get(settings.LOGVIEWER_GATE_SESSION_KEY):
        return render(request, "index.html")

    token = request.GET.get("token")
    if token:
        signer = TimestampSigner(key=settings.SECRET_KEY, salt=settings.LOGVIEWER_GATE_SALT)
        try:
            signer.unsign(token, max_age=settings.LOGVIEWER_GATE_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return _gate_denied()
        # 令牌有效：写入签名 cookie 会话（无需数据库），重定向到干净地址。
        request.session[settings.LOGVIEWER_GATE_SESSION_KEY] = True
        return HttpResponseRedirect("/")

    return _gate_denied()


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
