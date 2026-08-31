"""公司产业字段视图：对应原 NestJS CompanyFieldsController / CompanyFieldsService。

权限：读 company:view，写 company:manage。
路由前缀 /api（由 backend.urls include）。
"""
from __future__ import annotations

import json

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError, FieldWriteConflictException
from apps.common.guards import PermissionsPermission, require_permissions
from apps.common.permissions import has_permission
from apps.realtime.emit import emit_resource_changed

from apps.companies.models import Company, CompanyFieldValue

from .serializers import SetFieldSerializer, SetValuesSerializer

_VIEW_PERM = "company:view"
_MANAGE_PERM = "company:manage"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


def _can_manage(user) -> bool:
    return has_permission(user.role, user.permissions_list, _MANAGE_PERM)


def _truthy(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _get_company(company_id, user) -> Company:
    """取公司并做比赛域隔离，越权视作不存在。"""
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(user, "role", None) != "SUPER_ADMIN" and company.competition_id != getattr(
        user, "competition_id", None
    ):
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return company


def _parse_json(value):
    """JSON 字符串 → 对象；已是对象/None 原样返回。"""
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _field_to_dict(field, fv, company_name: str | None) -> dict:
    """单字段 + 其值 → 前端契约 dict。"""
    default_value = getattr(field, "default_value", "") or ""
    return {
        "industryFieldId": field.id,
        "fieldKey": getattr(field, "field_key", None),
        "name": getattr(field, "name", None),
        "fieldType": getattr(field, "field_type", None),
        "config": _parse_json(getattr(field, "config", None)),
        "defaultValue": default_value,
        "value": fv.value if fv else default_value,
        "version": fv.version if fv else 0,
        "visible": getattr(field, "visible", True),
        "isCalculated": getattr(field, "is_calculated", False),
        "sortOrder": getattr(field, "sort_order", 0),
        "companyName": company_name,
    }


def _write_field_value(
    company_id: int, industry_field_id: int, value: str, version: int | None
) -> None:
    """乐观锁写入单个字段值。

    - 不存在：创建（version=1）
    - 存在：WHERE id AND version=<期望版本> 更新并自增；未命中则 409 冲突
      期望版本取 body.version，缺省取当前 version（即无条件更新）
    """
    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=industry_field_id
    ).first()
    if fv is None:
        CompanyFieldValue.objects.create(
            company_id=company_id,
            industry_field_id=industry_field_id,
            value=value,
            version=1,
        )
        return
    expected_version = version if version is not None else fv.version
    updated = CompanyFieldValue.objects.filter(
        pk=fv.pk, version=expected_version
    ).update(
        value=value,
        version=expected_version + 1,
    )
    if not updated:
        raise FieldWriteConflictException()


def _recompute_calc_fields(company_id: int) -> None:
    """计算字段级联重算（计算引擎为独立模块，待接入）。"""
    # TODO: 接入 calcGraph 引擎后调用 recompute_calc_fields(company_id)


class CompanyFieldsView(APIView):
    """GET /company-fields/:companyId 读字段值；PUT 批量写。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, company_id):
        company = _get_company(company_id, request.user)
        include_hidden = _truthy(request.query_params.get("includeHidden"))
        industry_type = company.industry_type
        if industry_type is None:
            return Response([])

        # 延迟导入：industry_types app 可能尚未就绪，避免本模块导入期失败
        from apps.industry_types.models import IndustryField

        fields_qs = IndustryField.objects.filter(industry_type=industry_type)
        # 发布可见性：includeHidden=true 且有 company:manage 权限 → 全部；否则仅可见字段
        can_see_all = request.user.role == "SUPER_ADMIN" or _can_manage(request.user)
        if not (include_hidden and can_see_all):
            fields_qs = fields_qs.filter(visible=True)
        fields = list(fields_qs.order_by("sort_order", "id"))

        fvs = {
            fv.industry_field_id: fv
            for fv in CompanyFieldValue.objects.filter(company=company)
        }
        result = [_field_to_dict(f, fvs.get(f.id), company.name) for f in fields]
        return Response(result)

    @require_permissions(_MANAGE_PERM)
    def put(self, request, company_id):
        company = _get_company(company_id, request.user)
        serializer = SetValuesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["fields"]
        with transaction.atomic():
            for item in items:
                _write_field_value(
                    company_id=company.id,
                    industry_field_id=item["industryFieldId"],
                    value=item.get("value") or "",
                    version=item.get("version"),
                )
        _recompute_calc_fields(company.id)
        emit_resource_changed(
            "company-field", company.id, company.competition_id, "updated"
        )
        return Response({"ok": True})


class CompanyFieldItemView(APIView):
    """PUT /company-fields/:companyId/:fieldId 单字段写入。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_MANAGE_PERM)
    def put(self, request, company_id, field_id):
        company = _get_company(company_id, request.user)
        serializer = SetFieldSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = serializer.validated_data.get("value") or ""
        version = serializer.validated_data.get("version")
        with transaction.atomic():
            _write_field_value(company.id, field_id, value, version)
        _recompute_calc_fields(company.id)
        emit_resource_changed(
            "company-field", company.id, company.competition_id, "updated"
        )
        return Response({"ok": True})
