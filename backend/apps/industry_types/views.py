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
import logging
import math
import re

logger = logging.getLogger("gipfel")

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.field_ref_cleanup import cleanup_field_references, rename_field_references
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


# ==================== 计算字段依赖校验 / 级联重算 ====================
# 会影响计算字段结果的定义项：公式本身、被引用的键名、参与运算的默认值 / 类型 / 配置。
# 不含 sortOrder / visible / timer*（仅展示或定时写入，不改变公式求值结果）。
_CALC_RELEVANT_KEYS = {
    "calcGraph",
    "isCalculated",
    "fieldKey",
    "defaultValue",
    "fieldType",
    "config",
}


def _has_calc_fields(industry_type_id: int) -> bool:
    """该产业类型下是否存在计算字段（无则可跳过级联重算）。"""
    return IndustryField.objects.filter(
        industry_type_id=industry_type_id, is_calculated=True
    ).exists()


def _detect_calc_field_cycle(
    industry_type_id: int,
    edited_field_id: int | None,
    edited_field_key: str,
    edited_refs: set[str] | None,
    renamed_from: str | None = None,
    known_keys: set[str] | None = None,
) -> list[str] | None:
    """检测计算字段之间的循环依赖（跨字段引用成环，含公式模式变量引用）。

    返回成环节点的 fieldKey 序列（如 [a, b, a]），无环返回 None。
    edited_field 表示本次正在创建/编辑的字段（尚未落库或键已变更），
    用其「编辑后的 key + 编辑后的 calcGraph 引用」替换库中的旧数据参与构图。

    renamed_from：本次编辑同时改了 fieldKey 时传入旧键。库中兄弟字段的计算图
    此刻仍引用旧键（rename_field_references 要等 save 之后才改写），若不做映射
    会断链导致成环漏检。
    known_keys：本产业类型全部字段键集合，用于把公式表达式里的局部变量（assign 产出）
    与真实字段键区分开，避免产生假边污染环检测；为 None 时自动查询补全。
    """
    from apps.company_fields.calc import _graph_field_refs

    if known_keys is None:
        known_keys = set(
            IndustryField.objects.filter(industry_type_id=industry_type_id)
            .values_list("field_key", flat=True)
        )

    graph: dict[str, set[str]] = {}
    for f in IndustryField.objects.filter(
        industry_type_id=industry_type_id, is_calculated=True
    ):
        if f.id == edited_field_id:
            continue  # 正在编辑的字段用 edited 数据替代
        refs = _graph_field_refs(f.calc_graph, known_keys)
        if renamed_from and renamed_from in refs:
            # 预演改名后的引用关系，与 rename_field_references 的效果保持一致
            refs = (refs - {renamed_from}) | {edited_field_key}
        if refs:
            graph[f.field_key] = refs
    if edited_refs:
        # 编辑方自身的引用也按 known_keys 过滤，去掉 assign 局部变量等干扰项
        filtered = {r for r in edited_refs if r in known_keys} if known_keys else set(edited_refs)
        if filtered:
            graph[edited_field_key] = filtered

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {k: WHITE for k in graph}
    stack: list[str] = []
    cycle: list[str] = []

    def dfs(node: str) -> bool:
        color[node] = GRAY
        stack.append(node)
        for nxt in graph.get(node, ()):
            if nxt not in graph:
                continue
            if color.get(nxt) == GRAY:
                idx = stack.index(nxt)
                cycle.extend(stack[idx:])
                cycle.append(nxt)  # 闭环，便于提示里呈现 a → b → a
                return True
            if color.get(nxt) == WHITE and dfs(nxt):
                return True
        color[node] = BLACK
        stack.pop()
        return False

    for k in list(graph):
        if color[k] == WHITE and dfs(k):
            return cycle
    return None


def _recompute_industry_type(industry_type_id: int) -> None:
    """字段定义变更后，级联重算该产业类型下全部公司的计算字段并广播刷新。

    计算字段值写入 CompanyFieldValue 后须经 company-field 广播，
    否则仪表盘/公司详情/行情等订阅方停留在旧值（与上一轮修复的定时器/股票缺口同源）。
    """
    from apps.companies.models import Company
    from apps.company_fields.calc import recompute_calc_fields
    from apps.realtime.emit import emit_resource_changed

    for cid, comp_id in Company.objects.filter(
        industry_type_id=industry_type_id
    ).values_list("id", "competition_id"):
        try:
            recompute_calc_fields(cid)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[industry-types] 重算公司 #%s 计算字段失败：%s", cid, getattr(e, "message", e)
            )
            continue
        emit_resource_changed("company-field", cid, comp_id, "updated")


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
        user = request.user
        industry_type = _get_industry_type(pk)
        count = _count_companies(pk)
        if count > 0:
            from apps.companies.models import Company

            # 跨租户泄露修复（L6）：产业类型为全局资源，删除报错原本会列出
            # 所有比赛的公司名（含其他比赛的），造成租户间信息泄露。
            # 非超管仅展示当前比赛范围内的公司，超管才可见全量。
            is_super = getattr(user, "role", None) == "SUPER_ADMIN"
            own_cid = getattr(user, "competition_id", None)
            qs = (
                Company.objects.filter(industry_type_id=pk)
                .select_related("competition")
                .order_by("id")
            )
            if not is_super:
                if own_cid is not None:
                    qs = qs.filter(competition_id=own_cid)
                else:
                    qs = qs.none()
            blocking = list(qs[:20])
            listed = "、".join(f"「{c.name}」" for c in blocking)
            more = f" 等共 {count} 家" if count > len(blocking) else ""
            note = "" if is_super else "（仅列出当前比赛范围内的公司）"
            raise BusinessError(
                f"该产业类型下仍有公司在使用，无法删除。涉及：{listed}{more}。"
                "请先切换到对应比赛，在「公司管理」中移除这些公司的产业类型（或删除公司）后再试。"
                + note
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

        # 循环依赖检测（计算字段）：创建前即拦截，避免写入互相引用的非法公式
        if bool(data.get("isCalculated")):
            from apps.company_fields.calc import _graph_field_refs

            edited_refs = _graph_field_refs(data.get("calcGraph"))
            cycle = _detect_calc_field_cycle(pk, None, field_key, edited_refs)
            if cycle:
                raise BusinessError(
                    f"产业字段计算图存在循环依赖：{' → '.join(cycle)}"
                    "（请检查计算字段之间的相互引用）"
                )

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
        # 新计算字段需为已有公司补算初值；若类型已有其它计算字段，本次也需联动重算
        if bool(data.get("isCalculated")) or _has_calc_fields(pk):
            _recompute_industry_type(pk)
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
        old_field_key = field.field_key

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
            # validate_field 只在「同时传 isCalculated」时才校验计算图；单独 PATCH
            # calcGraph 会绕过校验写入非法图（缺 output 节点 / 缺端口等）。此处无条件
            # 校验，保证任何写入路径落库的图都合法。
            validate_calc_graph(data["calcGraph"])
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

        # 循环依赖检测（计算字段）：保存前拦截，避免非法公式落库后
        # 只在重算时打一条服务端 warning、前端毫无感知。
        # 此处 field 已带上本次编辑后的 field_key / is_calculated / calc_graph。
        renamed_from = old_field_key if old_field_key != field.field_key else None
        if field.is_calculated:
            from apps.company_fields.calc import _graph_field_refs

            cycle = _detect_calc_field_cycle(
                field.industry_type_id,
                field.id,
                field.field_key,
                _graph_field_refs(field.calc_graph),
                renamed_from=renamed_from,
            )
            if cycle:
                raise BusinessError(
                    f"产业字段计算图存在循环依赖：{' → '.join(cycle)}"
                    "（请检查计算字段之间的相互引用）"
                )

        field.save()
        # 字段键改名：同步同产业类型内的财年定时器引用与计算图引用
        # （合同类型效果为全局模板、可能跨产业复用，不做静默改写，rename 内部仅告警）
        if renamed_from:
            rename_field_references(field.industry_type_id, old_field_key, field.field_key)
        # 定义变更后级联重算：公式改了、被引用的键改名了、默认值/类型变了都会影响结果。
        # 仅排序/可见性/定时器这类 PATCH 不重算，避免拖拽排序时逐条全量算。
        if set(data) & _CALC_RELEVANT_KEYS and _has_calc_fields(field.industry_type_id):
            _recompute_industry_type(field.industry_type_id)
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
        # 引用被清理后依赖该字段的公式结果已变化，需级联重算并广播
        if _has_calc_fields(industry_type_id):
            _recompute_industry_type(industry_type_id)
        return Response({"ok": True})
