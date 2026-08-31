"""产业类型视图：对应原 NestJS IndustryTypeController / IndustryTypeService。

产业类型为全局资源（无 competitionId），故不走比赛域隔离；权限 key：
- 读（GET）：industryType:view
- 写（POST/PATCH/DELETE）：industryType:manage

路由（挂载于 /api 前缀下，与前端 api/index.ts industryTypesApi 对齐）：
- GET    /industry-types                  列表（支持 updatedAfter 增量同步）
- POST   /industry-types                  创建（自动分配 code 与「所在地」字段）
- GET    /industry-types/:id              详情（含 fields + _count.companies）
- PATCH  /industry-types/:id              更新
- DELETE /industry-types/:id              删除（被公司引用时阻止）
- GET    /industry-types/:id/fields       字段列表
- POST   /industry-types/:id/fields       创建字段
- PATCH  /industry-types/fields/:fieldId  更新字段
- DELETE /industry-types/fields/:fieldId  删除字段（被公司字段值引用时阻止）
"""
from __future__ import annotations

import json
import math
import re

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.field_ref_cleanup import cleanup_field_references
from apps.common.guards import PermissionsPermission, require_permissions
from apps.common.sync import apply_updated_after, build_incremental_result

from .models import IndustryField, IndustryType
from .serializers import (
    IndustryFieldSerializer,
    IndustryTypeSerializer,
    _count_companies,
)

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)

FIELD_TYPES = ["STRING", "NUMBER", "BOOLEAN", "DICTIONARY", "LIST"]
FIELD_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ==================== 字段校验（移植自 industry-type.service.ts） ====================
def validate_calc_graph(raw):
    """校验产业计算图：须为合法 GGraph JSON（{ nodes, edges }），恰好一个 output 节点。"""
    if raw is None or not str(raw).strip():
        return  # 允许空（非计算字段）
    try:
        g = json.loads(raw)
    except (ValueError, TypeError):
        raise BusinessError("产业计算图不是合法的 JSON")
    if (
        not g
        or not isinstance(g, dict)
        or not isinstance(g.get("nodes"), list)
        or not isinstance(g.get("edges"), list)
    ):
        raise BusinessError("产业计算图格式错误：须含 nodes / edges 数组")
    nodes = g["nodes"]
    edges = g["edges"]
    outputs = [n for n in nodes if n and n.get("type") == "output"]
    if len(outputs) == 0:
        raise BusinessError("产业计算图必须包含恰好一个「输出」节点")
    if len(outputs) > 1:
        raise BusinessError("产业计算图只能包含一个「输出」节点")
    for n in nodes:
        if not n or not isinstance(n, dict) or not n.get("id") or not n.get("type"):
            raise BusinessError("产业计算图节点缺少 id / type")
    for e in edges:
        if (
            not e
            or not e.get("source")
            or not e.get("target")
            or not e.get("sourceHandle")
            or not e.get("targetHandle")
        ):
            raise BusinessError("产业计算图连线缺少 source / target / 端口")


def validate_field_config(field_type, config):
    """校验结构化字段 config：DICTIONARY -> { entries, valueType }；LIST -> { itemType }。"""
    cfg = config if isinstance(config, dict) else {}
    if field_type == "DICTIONARY":
        entries = cfg.get("entries")
        if not isinstance(entries, list):
            raise BusinessError("字典字段 entries 必须是数组")
        keys = set()
        for e in entries:
            key = e.get("key") if isinstance(e, dict) else None
            if not isinstance(key, str) or not FIELD_KEY_RE.match(key):
                raise BusinessError(
                    f"字典项 key 非法：{key}（只能字母/数字/下划线，且不以数字开头）"
                )
            label = e.get("label")
            if not isinstance(label, str) or not label.strip():
                raise BusinessError(f"字典项「{key}」缺少 label")
            if key in keys:
                raise BusinessError(f"字典项 key 重复：{key}")
            keys.add(key)
        value_type = cfg.get("valueType") or "NUMBER"
        if value_type not in ("NUMBER", "STRING", "BOOLEAN"):
            raise BusinessError(f"字典 valueType 非法：{value_type}")
    elif field_type == "LIST":
        item_type = cfg.get("itemType") or "STRING"
        if item_type not in ("NUMBER", "STRING", "BOOLEAN"):
            raise BusinessError(f"列表 itemType 非法：{item_type}")


def validate_timer_spec(field_type, trigger, value):
    """校验财年定时器设定：触发时机 FY_START/FY_END，设定值按字段类型校验。"""
    if not trigger or trigger not in ("FY_START", "FY_END"):
        raise BusinessError("财年定时器触发时机必须是 FY_START 或 FY_END")
    if value is None or not str(value).strip():
        raise BusinessError("启用财年定时器时必须填写触发后写入的设定值")
    # 字段引用模式：timerValue 形如 `field:<fieldKey>`，跳过字面量类型校验
    if isinstance(value, str) and value.startswith("field:"):
        if not value[len("field:"):].strip():
            raise BusinessError("定时器的字段引用格式必须为 field:<字段键>")
        return
    v = str(value)
    if field_type == "NUMBER":
        try:
            if not math.isfinite(float(v)):
                raise BusinessError("定时器设定值必须为数值")
        except (ValueError, TypeError):
            raise BusinessError("定时器设定值必须为数值")
    elif field_type == "BOOLEAN":
        if v.strip().lower() not in ("true", "false"):
            raise BusinessError("定时器设定值必须为 true 或 false")
    elif field_type == "DICTIONARY":
        try:
            o = json.loads(v)
        except (ValueError, TypeError):
            raise BusinessError("字典定时器的设定值必须是合法 JSON 对象")
        if not o or not isinstance(o, dict) or isinstance(o, list):
            raise BusinessError("字典定时器的设定值必须是 JSON 对象")
    elif field_type == "LIST":
        try:
            a = json.loads(v)
        except (ValueError, TypeError):
            raise BusinessError("列表定时器的设定值必须是合法 JSON 数组")
        if not isinstance(a, list):
            raise BusinessError("列表定时器的设定值必须是 JSON 数组")
    # STRING / 其它：任意值放行


def validate_field(data: dict, effective_type: str | None = None) -> None:
    """移植自 NestJS validateField：类型/config/计算图/定时器联合校验。"""
    field_type = effective_type or data.get("fieldType") or "NUMBER"
    ft = data.get("fieldType")
    if ft is not None and ft not in FIELD_TYPES:
        raise BusinessError(f"字段类型只能是 {' / '.join(FIELD_TYPES)}")
    if "config" in data:
        validate_field_config(field_type, data["config"])
    if data.get("isCalculated"):
        calc_graph = data.get("calcGraph")
        if not calc_graph or not str(calc_graph).strip():
            raise BusinessError("计算字段必须配置产业计算图（可视化蓝图）")
        validate_calc_graph(calc_graph)
    if data.get("timerEnabled"):
        if data.get("isCalculated"):
            raise BusinessError(
                "财年定时器字段不可同时设为计算字段（定时器写入值会被级联重算覆盖）"
            )
        validate_timer_spec(field_type, data.get("timerTrigger"), data.get("timerValue"))


# ==================== 辅助函数 ====================
def _get_industry_type(pk: int) -> IndustryType:
    try:
        return IndustryType.objects.get(pk=pk)
    except IndustryType.DoesNotExist:
        raise BusinessError("产业类型不存在", code=404, status_code=404)


def _get_field(field_id: int) -> IndustryField:
    try:
        return IndustryField.objects.get(pk=field_id)
    except IndustryField.DoesNotExist:
        raise BusinessError("产业字段不存在", code=404, status_code=404)


def _next_code() -> int:
    last = IndustryType.objects.order_by("-code").first()
    return (last.code if last else 100) + 1


def _ensure_location_field(industry_type_id: int) -> None:
    """为产业类型创建默认「所在地」字段（fieldKey=location，config.isLocation=true）。"""
    if IndustryField.objects.filter(
        industry_type_id=industry_type_id, field_key="location"
    ).exists():
        return
    IndustryField.objects.create(
        industry_type_id=industry_type_id,
        name="所在地",
        field_key="location",
        field_type="STRING",
        config=json.dumps({"isLocation": True}, ensure_ascii=False),
        default_value=None,
        is_calculated=False,
        formula=None,
        sort_order=-1,
    )


def _serialize_type(instance: IndustryType) -> dict:
    return IndustryTypeSerializer(instance).data


# ==================== 产业类型：列表 / 创建 ====================
class CollectionView(APIView):
    permission_classes = _PERM_CLASSES

    @require_permissions("industryType:view")
    def get(self, request):
        """列表（全局，无比赛过滤）；支持 updatedAfter 增量同步。"""
        updated_after = request.query_params.get("updatedAfter")
        require_existing_ids = request.query_params.get("requireExistingIds") == "true"

        where, incremental, _baseline = apply_updated_after({}, updated_after)
        if incremental:
            rows = list(IndustryType.objects.filter(**where).order_by("code"))
            items = [_serialize_type(r) for r in rows]
            all_current_ids = []
            if require_existing_ids:
                all_current_ids = list(
                    IndustryType.objects.values_list("id", flat=True)
                )
            return Response(build_incremental_result(items, all_current_ids))

        items = [_serialize_type(r) for r in IndustryType.objects.order_by("code")]
        return Response(items)

    @require_permissions("industryType:manage")
    def post(self, request):
        """创建产业类型；code 未传则自动分配（max+1，默认基线 100）。"""
        serializer = IndustryTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessError("产业类型名称不能为空")

        code = data.get("code")
        if code is None:
            code = _next_code()
        if IndustryType.objects.filter(code=code).exists():
            raise BusinessError(f"产业编号 {code} 已被占用")

        industry_type = IndustryType.objects.create(
            name=name,
            code=code,
            description=data.get("description"),
            icon=data.get("icon"),
        )
        _ensure_location_field(industry_type.id)
        return Response(_serialize_type(industry_type))


# ==================== 产业类型：详情 / 更新 / 删除 ====================
class ItemView(APIView):
    permission_classes = _PERM_CLASSES

    @require_permissions("industryType:view")
    def get(self, request, pk):
        return Response(_serialize_type(_get_industry_type(pk)))

    @require_permissions("industryType:manage")
    def patch(self, request, pk):
        industry_type = _get_industry_type(pk)
        serializer = IndustryTypeSerializer(industry_type, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "code" in data and IndustryType.objects.filter(code=data["code"]).exclude(pk=pk).exists():
            raise BusinessError(f"产业编号 {data['code']} 已被占用")
        if "name" in data:
            industry_type.name = data["name"].strip()
        if "code" in data:
            industry_type.code = data["code"]
        if "description" in data:
            industry_type.description = data["description"]
        if "icon" in data:
            industry_type.icon = data["icon"]
        industry_type.save()
        return Response(_serialize_type(industry_type))

    @require_permissions("industryType:manage")
    def delete(self, request, pk):
        industry_type = _get_industry_type(pk)
        count = _count_companies(pk)
        if count > 0:
            from apps.companies.models import Company

            blocking = list(
                Company.objects.filter(industry_type_id=pk)
                .select_related("competition")
                .order_by("id")[:20]
            )
            listed = "、".join(
                f"「{c.name}」（比赛：{c.competition.name if c.competition_id else '未归属比赛'}）"
                for c in blocking
            )
            more = f" 等共 {count} 家" if count > len(blocking) else ""
            raise BusinessError(
                f"该产业类型下仍有公司在使用，无法删除。涉及：{listed}{more}。"
                "请先切换到对应比赛，在「公司管理」中移除这些公司的产业类型（或删除公司）后再试。"
            )
        industry_type.delete()
        return Response({"ok": True})


# ==================== 产业字段：列表 / 创建 ====================
class FieldListView(APIView):
    permission_classes = _PERM_CLASSES

    @require_permissions("industryType:view")
    def get(self, request, pk):
        _get_industry_type(pk)  # 404 若产业类型不存在
        fields = IndustryField.objects.filter(industry_type_id=pk).order_by(
            "sort_order", "id"
        )
        return Response(IndustryFieldSerializer(fields, many=True).data)

    @require_permissions("industryType:manage")
    def post(self, request, pk):
        _get_industry_type(pk)  # 404 若产业类型不存在
        serializer = IndustryFieldSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessError("字段名称不能为空")
        field_key = (data.get("fieldKey") or "").strip()
        if not FIELD_KEY_RE.match(field_key):
            raise BusinessError("字段键只能包含字母、数字、下划线，且不能以数字开头")
        validate_field(data)

        if IndustryField.objects.filter(
            industry_type_id=pk, field_key=field_key
        ).exists():
            raise BusinessError(f"字段键 {field_key} 已存在")

        timer_enabled = bool(data.get("timerEnabled"))
        field = IndustryField.objects.create(
            industry_type_id=pk,
            name=name,
            field_key=field_key,
            field_type=data.get("fieldType", "NUMBER"),
            config=json.dumps(data.get("config") or {}, ensure_ascii=False),
            default_value=data.get("defaultValue"),
            is_calculated=bool(data.get("isCalculated")),
            calc_graph=data.get("calcGraph"),
            formula=None,  # 旧公式引擎已废弃，新计算字段一律用 calcGraph
            sort_order=data.get("sortOrder", 0),
            visible=data.get("visible", True),
            timer_enabled=timer_enabled,
            timer_trigger=data.get("timerTrigger") if timer_enabled else None,
            timer_value=data.get("timerValue") if timer_enabled else None,
        )
        return Response(IndustryFieldSerializer(field).data)


# ==================== 产业字段：更新 / 删除 ====================
class FieldItemView(APIView):
    permission_classes = _PERM_CLASSES

    @require_permissions("industryType:manage")
    def patch(self, request, field_id):
        field = _get_field(field_id)
        serializer = IndustryFieldSerializer(field, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        validate_field(data, effective_type=field.field_type)
        # 计算定时器启用有效值：timerEnabled 未传时沿用已有值，避免部分更新误清空 trigger/value
        eff_timer_enabled = (
            data.get("timerEnabled") if "timerEnabled" in data else bool(field.timer_enabled)
        )

        if "fieldKey" in data:
            fk = (data["fieldKey"] or "").strip()
            if not FIELD_KEY_RE.match(fk):
                raise BusinessError("字段键只能包含字母、数字、下划线，且不能以数字开头")
            if (
                IndustryField.objects.filter(
                    industry_type_id=field.industry_type_id, field_key=fk
                )
                .exclude(pk=field_id)
                .exists()
            ):
                raise BusinessError(f"字段键 {fk} 已存在")
            field.field_key = fk

        if "name" in data:
            field.name = data["name"].strip()
        if "fieldType" in data:
            field.field_type = data["fieldType"]
        if "config" in data:
            field.config = json.dumps(data["config"], ensure_ascii=False)
        if "defaultValue" in data:
            field.default_value = data["defaultValue"]
        if "isCalculated" in data:
            field.is_calculated = data["isCalculated"]
        if "calcGraph" in data:
            field.calc_graph = data["calcGraph"]
        if "formula" in data:
            field.formula = None  # 旧公式引擎已废弃
        if "sortOrder" in data:
            field.sort_order = data["sortOrder"]
        if "visible" in data:
            field.visible = data["visible"]
        if "timerEnabled" in data:
            field.timer_enabled = data["timerEnabled"]
        if "timerTrigger" in data:
            field.timer_trigger = data["timerTrigger"] if eff_timer_enabled else None
        if "timerValue" in data:
            field.timer_value = data["timerValue"] if eff_timer_enabled else None

        field.save()
        return Response(IndustryFieldSerializer(field).data)

    @require_permissions("industryType:manage")
    def delete(self, request, field_id):
        field = _get_field(field_id)
        from apps.companies.models import CompanyFieldValue

        count = CompanyFieldValue.objects.filter(industry_field_id=field_id).count()
        if count > 0:
            raise BusinessError(
                f"该产业字段已被 {count} 家公司填写了字段值，无法删除。"
                "请先在这些公司的「资料」中清除该字段的值后再试。"
            )
        industry_type_id = field.industry_type_id
        field_key = field.field_key
        field.delete()
        # 清理兄弟字段对该字段的悬空引用（财年定时器 field: 引用、计算图 value 节点）
        cleanup_field_references(industry_type_id, field_key)
        return Response({"ok": True})
