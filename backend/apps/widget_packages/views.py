"""控件包视图。

上传仅超管可操作；列表/详情所有登录用户可读（前端加载控件包需要）。
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission

from .models import WidgetPackage

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)
_WIDGETS_DIR = "widget-packages"  # MEDIA_ROOT 下的子目录


def _to_dict(wp: WidgetPackage) -> dict:
    return {
        "id": wp.id,
        "name": wp.name,
        "widgetType": wp.widget_type,
        "description": wp.description,
        "version": wp.version,
        "manifest": wp.manifest,
        "isActive": wp.is_active,
        # 前端加载组件 JS 的完整 URL
        "componentUrl": f"{settings.MEDIA_URL}{wp.extract_dir}/component.js",
        "createdAt": wp.created_at.isoformat() if wp.created_at else None,
    }


class CollectionView(APIView):
    """GET 列表 + POST 上传控件包。"""

    permission_classes = _PERM_CLASSES

    def get(self, request):
        qs = WidgetPackage.objects.all()
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            qs = qs.filter(is_active=True)
        return Response([_to_dict(wp) for wp in qs])

    def post(self, request):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可上传控件包", code=403, status_code=403)

        uploaded = request.FILES.get("file")
        if not uploaded:
            raise BusinessError("请上传 zip 文件", code=400, status_code=400)
        if not uploaded.name.endswith(".zip"):
            raise BusinessError("仅支持 .zip 格式", code=400, status_code=400)
        if uploaded.size > 5 * 1024 * 1024:
            raise BusinessError("文件大小不能超过 5MB", code=400, status_code=400)

        # 解压到临时目录，校验 manifest.json
        uid = uuid.uuid4().hex[:12]
        base_dir = os.path.join(settings.MEDIA_ROOT, _WIDGETS_DIR)
        extract_dir_name = f"{_WIDGETS_DIR}/{uid}"
        extract_full = os.path.join(settings.MEDIA_ROOT, extract_dir_name)
        zip_path = os.path.join(base_dir, f"{uid}.zip")

        os.makedirs(base_dir, exist_ok=True)

        # 保存 zip
        with open(zip_path, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        # 解压
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # 安全检查：不允许路径穿越
                for name in zf.namelist():
                    if ".." in name or name.startswith("/"):
                        raise BusinessError("zip 文件包含非法路径", code=400, status_code=400)
                zf.extractall(extract_full)
        except zipfile.BadZipFile:
            os.remove(zip_path)
            raise BusinessError("无法解析 zip 文件", code=400, status_code=400)
        except BusinessError:
            # 清理
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if os.path.exists(extract_full):
                shutil.rmtree(extract_full)
            raise
        except Exception:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if os.path.exists(extract_full):
                shutil.rmtree(extract_full)
            raise BusinessError("解压失败", code=500, status_code=500)

        # 处理常见情况：zip 内嵌套了单个子目录（如 progress-bar/manifest.json）
        # 自动将内容上移一级，使 manifest.json 在 extract_full 根目录
        entries = os.listdir(extract_full)
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_full, entries[0])):
            nested = os.path.join(extract_full, entries[0])
            if os.path.exists(os.path.join(nested, "manifest.json")):
                for item in os.listdir(nested):
                    shutil.move(os.path.join(nested, item), os.path.join(extract_full, item))
                os.rmdir(nested)

        # 读取 manifest.json
        manifest_path = os.path.join(extract_full, "manifest.json")
        if not os.path.exists(manifest_path):
            shutil.rmtree(extract_full)
            os.remove(zip_path)
            raise BusinessError("zip 中缺少 manifest.json", code=400, status_code=400)

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            shutil.rmtree(extract_full)
            os.remove(zip_path)
            raise BusinessError("manifest.json 格式错误", code=400, status_code=400)

        widget_type = (manifest.get("type") or "").strip()
        if not widget_type:
            shutil.rmtree(extract_full)
            os.remove(zip_path)
            raise BusinessError("manifest.json 缺少 type 字段", code=400, status_code=400)

        # 检查 component.js 是否存在
        component_file = manifest.get("component", "component.js")
        if not os.path.exists(os.path.join(extract_full, component_file)):
            shutil.rmtree(extract_full)
            os.remove(zip_path)
            raise BusinessError(f"zip 中缺少 {component_file}", code=400, status_code=400)

        # 如果已存在同 type 的控件包，删除旧的
        old = WidgetPackage.objects.filter(widget_type=widget_type).first()
        if old:
            old_dir = os.path.join(settings.MEDIA_ROOT, old.extract_dir)
            if os.path.exists(old_dir):
                shutil.rmtree(old_dir)
            old_zip = os.path.join(settings.MEDIA_ROOT, old.file_path)
            if os.path.exists(old_zip):
                os.remove(old_zip)
            old.delete()

        # 创建记录
        wp = WidgetPackage.objects.create(
            name=manifest.get("label", widget_type),
            widget_type=widget_type,
            description=manifest.get("description", ""),
            version=manifest.get("version", "1.0.0"),
            manifest=manifest,
            file_path=f"{_WIDGETS_DIR}/{uid}.zip",
            extract_dir=extract_dir_name,
        )

        return Response(_to_dict(wp))


class ItemView(APIView):
    """PATCH 启停 + DELETE 删除。"""

    permission_classes = _PERM_CLASSES

    def _get(self, pk):
        try:
            return WidgetPackage.objects.get(pk=pk)
        except WidgetPackage.DoesNotExist:
            raise BusinessError("控件包不存在", code=404, status_code=404)

    def patch(self, request, pk):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可操作", code=403, status_code=403)
        wp = self._get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        if "isActive" in data:
            wp.is_active = bool(data["isActive"])
            wp.save()
        return Response(_to_dict(wp))

    def delete(self, request, pk):
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可删除", code=403, status_code=403)
        wp = self._get(pk)
        # 清理文件
        extract_full = os.path.join(settings.MEDIA_ROOT, wp.extract_dir)
        zip_full = os.path.join(settings.MEDIA_ROOT, wp.file_path)
        if os.path.exists(extract_full):
            shutil.rmtree(extract_full)
        if os.path.exists(zip_full):
            os.remove(zip_full)
        wp.delete()
        return Response({"ok": True})
