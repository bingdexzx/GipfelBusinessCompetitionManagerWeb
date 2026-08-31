"""文件上传视图：对应原 NestJS FilesController / FilesService。

权限：map-background 读 data:map:view，写 data:map:edit；generic upload 仅需认证。
路由由 backend.urls 以 path("api/", include("apps.files.urls")) 引入。

前端契约（与 filesApi + mapsApi.mapBackground 对齐）：
- POST   /files/upload                       通用上传
- POST   /files/map-background               上传地图背景
- DELETE /files/map-background?competitionId 删除地图背景
- GET    /files/map-background?competitionId 获取地图背景
- PATCH  /files/map-background/transform     更新背景变换
"""
from __future__ import annotations

import json
import math
import os
import struct
import time

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission, require_permissions
from apps.realtime.emit import emit_resource_changed

from .serializers import MapBackgroundTransformSerializer

_VIEW_PERM = "data:map:view"
_EDIT_PERM = "data:map:edit"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)

# 各 MIME 类型对应的 magic bytes（文件头前缀）
_MAGIC_BYTES: dict[str, bytes] = {
    "image/png": b"\x89\x50\x4e\x47",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": b"\x47\x49\x46\x38",
    "image/webp": b"\x52\x49\x46\x46",  # RIFF....WEBP 需额外校验偏移 8..11
    "image/bmp": b"\x42\x4d",
}

_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

_ALLOWED_IMAGE_MIME = list(_MIME_TO_EXT.keys())


def _assert_image_mime(mime: str) -> str:
    """校验 MIME 为允许的图片类型，返回扩展名。"""
    if mime not in _MIME_TO_EXT:
        raise BusinessError(
            "仅支持图片文件（PNG / JPEG / GIF / WebP / BMP）",
            code=400, status_code=400,
        )
    return _MIME_TO_EXT[mime]


def _validate_magic_bytes(buf: bytes, mime: str) -> bool:
    """校验文件头 magic bytes，确保内容与声称的 MIME 类型一致。"""
    expected = _MAGIC_BYTES.get(mime)
    if expected is None:
        return True  # 无已知签名则跳过
    if len(buf) < len(expected):
        return False
    if buf[: len(expected)] != expected:
        return False
    # WebP 特殊处理：RIFF 头之后偏移 8..11 必须为 "WEBP"
    if mime == "image/webp":
        if len(buf) < 12:
            return False
        if buf[8:12] != b"WEBP":
            return False
    return True


def _read_dimensions(buf: bytes, mime: str) -> tuple[int | None, int | None]:
    """解析 PNG / JPEG 的像素尺寸；其他格式或失败返回 (None, None)。"""
    try:
        if mime == "image/png" and len(buf) >= 24:
            width = struct.unpack(">I", buf[16:20])[0]
            height = struct.unpack(">I", buf[20:24])[0]
            return width, height
        if mime == "image/jpeg":
            off = 2
            while off + 9 < len(buf):
                if buf[off] != 0xFF:
                    break
                marker = buf[off + 1]
                # SOF0..SOF15 中除 0xC4/0xC8/0xCC 外含尺寸信息
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    height = struct.unpack(">H", buf[off + 5 : off + 7])[0]
                    width = struct.unpack(">H", buf[off + 7 : off + 9])[0]
                    return width, height
                length = struct.unpack(">H", buf[off + 2 : off + 4])[0]
                off += 2 + length
    except (struct.error, IndexError):
        pass
    return None, None


def _resolve_target(user, requested: int | None) -> int:
    """解析目标比赛 ID。

    - 超管：使用请求中指定的 competitionId（必填）
    - 归属账号：强制使用其所属比赛（忽略请求值）
    """
    if getattr(user, "role", None) == "SUPER_ADMIN":
        if requested is None:
            raise BusinessError("请指定比赛 ID", code=400, status_code=400)
        return requested
    own = getattr(user, "competition_id", None)
    if own is None:
        raise BusinessError("账号未归属比赛，无法操作地图背景", code=403, status_code=403)
    return own


def _parse_meta(raw: str | None) -> dict | None:
    """解析 Competition.map_background JSON 字符串。"""
    if not raw:
        return None
    try:
        m = json.loads(raw)
        if m and isinstance(m, dict) and isinstance(m.get("url"), str):
            return m
    except (ValueError, TypeError):
        pass
    return None


def _dump_meta(meta: dict) -> str:
    return json.dumps(meta, ensure_ascii=False)


def _delete_file_safe(filename: str | None, subdir: str) -> None:
    """安全删除已落盘的文件（防路径遍历）。"""
    if not filename:
        return
    try:
        if "/" in filename or "\\" in filename or ".." in filename:
            return
        target_dir = os.path.join(settings.MEDIA_ROOT, subdir)
        p = os.path.join(target_dir, filename)
        resolved = os.path.abspath(p)
        if not resolved.startswith(os.path.abspath(target_dir)):
            return
        if os.path.exists(resolved):
            os.remove(resolved)
    except OSError:
        pass


def _broadcast_map_background(cid: int) -> None:
    """背景变更实时广播。"""
    emit_resource_changed("map-background", cid, cid, "updated")


# ==================== 通用上传 ====================
class UploadView(APIView):
    """POST /files/upload — 通用文件上传。"""

    permission_classes = _PERM_CLASSES

    def post(self, request):
        f = request.FILES.get("file")
        if not f:
            raise BusinessError("未收到文件", code=400, status_code=400)
        subdir = "uploads"
        target_dir = os.path.join(settings.MEDIA_ROOT, subdir)
        os.makedirs(target_dir, exist_ok=True)
        safe_name = f"upload-{int(time.time() * 1000)}-{f.name}"
        # 防路径遍历
        safe_name = os.path.basename(safe_name)
        full_path = os.path.join(target_dir, safe_name)
        with open(full_path, "wb") as dest:
            for chunk in f.chunks():
                dest.write(chunk)
        url = f"{settings.MEDIA_URL}{subdir}/{safe_name}"
        return Response({"url": url, "filename": safe_name})


# ==================== 地图背景 ====================
class MapBackgroundView(APIView):
    """GET/POST/DELETE /files/map-background — 地图背景图。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        raw = request.query_params.get("competitionId")
        try:
            requested = int(raw) if raw else None
        except (TypeError, ValueError):
            requested = None
        cid = _resolve_target(request.user, requested)
        from apps.competitions.models import Competition

        comp = Competition.objects.filter(pk=cid).first()
        if not comp:
            raise BusinessError("比赛不存在", code=404, status_code=404)
        return Response(_parse_meta(comp.map_background))

    @require_permissions(_EDIT_PERM)
    def post(self, request):
        f = request.FILES.get("file")
        if not f:
            raise BusinessError("未收到文件", code=400, status_code=400)
        mime = f.content_type or ""
        ext = _assert_image_mime(mime)
        buf = f.read()
        if not _validate_magic_bytes(buf, mime):
            raise BusinessError("文件内容与声称的格式不一致", code=400, status_code=400)

        try:
            requested = int(request.data.get("competitionId"))
        except (TypeError, ValueError):
            requested = None
        cid = _resolve_target(request.user, requested)
        from apps.competitions.models import Competition

        comp = Competition.objects.filter(pk=cid).first()
        if not comp:
            raise BusinessError("比赛不存在", code=404, status_code=404)

        subdir = "map-backgrounds"
        target_dir = os.path.join(settings.MEDIA_ROOT, subdir)
        os.makedirs(target_dir, exist_ok=True)
        safe_name = f"comp-{cid}-{int(time.time() * 1000)}{ext}"
        full_path = os.path.join(target_dir, safe_name)
        with open(full_path, "wb") as dest:
            dest.write(buf)

        width, height = _read_dimensions(buf, mime)

        # 清理旧背景文件
        old_meta = _parse_meta(comp.map_background)
        if old_meta:
            _delete_file_safe(old_meta.get("filename"), subdir)

        meta = {
            "url": f"{settings.MEDIA_URL}{subdir}/{safe_name}",
            "filename": safe_name,
            "width": width,
            "height": height,
            "transform": None,
        }
        comp.map_background = _dump_meta(meta)
        comp.save(update_fields=["map_background"])
        _broadcast_map_background(cid)
        return Response(meta)

    @require_permissions(_EDIT_PERM)
    def delete(self, request):
        raw = request.query_params.get("competitionId")
        try:
            requested = int(raw) if raw else None
        except (TypeError, ValueError):
            requested = None
        # DELETE 可能经 body 传 competitionId（兼容旧前端）
        if requested is None and request.data:
            try:
                requested = int(request.data.get("competitionId"))
            except (TypeError, ValueError):
                requested = None
        cid = _resolve_target(request.user, requested)
        from apps.competitions.models import Competition

        comp = Competition.objects.filter(pk=cid).first()
        if not comp:
            raise BusinessError("比赛不存在", code=404, status_code=404)
        old_meta = _parse_meta(comp.map_background)
        if old_meta:
            _delete_file_safe(old_meta.get("filename"), "map-backgrounds")
            comp.map_background = None
            comp.save(update_fields=["map_background"])
            _broadcast_map_background(cid)
        return Response({"ok": True})


class MapBackgroundTransformView(APIView):
    """PATCH /files/map-background/transform — 更新背景变换。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def patch(self, request):
        serializer = MapBackgroundTransformSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            requested = int(data["competitionId"]) if data.get("competitionId") is not None else None
        except (TypeError, ValueError):
            requested = None
        cid = _resolve_target(request.user, requested)
        from apps.competitions.models import Competition

        comp = Competition.objects.filter(pk=cid).first()
        if not comp:
            raise BusinessError("比赛不存在", code=404, status_code=404)

        old_meta = _parse_meta(comp.map_background)
        if not old_meta:
            raise BusinessError("该比赛尚未设置背景图，无法编辑变换", code=400, status_code=400)

        # 限制 scale 范围
        scale = max(0.1, min(10, data["scale"]))
        transform = {"x": data["x"], "y": data["y"], "scale": scale}
        meta = dict(old_meta)
        meta["transform"] = transform
        comp.map_background = _dump_meta(meta)
        comp.save(update_fields=["map_background"])
        _broadcast_map_background(cid)
        return Response(meta)
