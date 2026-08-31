"""合同视图：对应原 NestJS ContractController / ContractService +
ContractTypeController / ContractTypeService。

权限：
- 合同类型：读 contractType:view，写 contractType:manage（全局，无比赛域隔离）
- 合同：读 contract:view，写 contract:manage（比赛域隔离 + 公司范围过滤）
- 执行/预检/编号补全：至少 contract:audit（会签范围校验由视图层完成）

路由由 backend.urls 以 path("api/", include("apps.contracts.urls")) 引入。
"""
from __future__ import annotations

import json
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import (
    PermissionsPermission,
    apply_competition_scope,
    no_competition_scope,
    require_permissions,
)
from apps.common.json_util import parse_json_array
from apps.common.pagination import paginated_response, parse_pagination
from apps.common.permissions import has_permission
from apps.common.scope import assert_same_competition
from apps.common.sync import apply_updated_after, build_incremental_result
from apps.realtime.emit import emit_resource_changed

from .engine import ContractEngine
from .models import Contract, ContractFieldEffect, ContractType
from .serializers import ContractSerializer, ContractTypeSerializer

# ==================== 权限常量 ====================

_CT_VIEW_PERM = "contractType:view"
_CT_MANAGE_PERM = "contractType:manage"
_CONTRACT_VIEW_PERM = "contract:view"
_CONTRACT_AUDIT_PERM = "contract:audit"
_CONTRACT_MANAGE_PERM = "contract:manage"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)

_engine = ContractEngine()


# ==================== 合同类型视图 ====================

class ContractTypeCollectionAPIView(APIView):
    """GET/POST /api/contract-types —— 列表（增量）+ 创建。

    全局资源，无比赛域隔离（@NoCompetitionScope）。
    """

    permission_classes = _PERM_CLASSES

    @no_competition_scope
    @require_permissions(_CT_VIEW_PERM)
    def get(self, request):
        qs = ContractType.objects.all()
        enabled_only = _truthy(request.query_params.get("enabledOnly"))
        if enabled_only:
            qs = qs.filter(enabled=True)

        # 增量同步
        updated_after = request.query_params.get("updatedAfter")
        base_where = {"enabled": True} if enabled_only else {}
        where, incremental, _ = apply_updated_after(base_where, updated_after)
        if incremental:
            rows = list(qs.filter(**where).order_by("id"))
            items = [ContractTypeSerializer(ct).data for ct in rows]
            require_existing = _truthy(request.query_params.get("requireExistingIds"))
            all_current_ids = []
            if require_existing:
                base_qs = ContractType.objects.filter(**base_where)
                all_current_ids = list(base_qs.values_list("pk", flat=True))
            previous_ids = _parse_previous_ids(request.query_params.get("previousIds"))
            return Response(
                build_incremental_result(items, all_current_ids, previous_ids, total=len(items))
            )

        items = [ContractTypeSerializer(ct).data for ct in qs.order_by("id")]
        return Response({"items": items, "total": len(items)})

    @no_competition_scope
    @require_permissions(_CT_MANAGE_PERM)
    def post(self, request):
        serializer = ContractTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ct = serializer.create(serializer.validated_data)
        return Response(ContractTypeSerializer(ct).data)


class ContractTypeItemAPIView(APIView):
    """GET/PATCH/DELETE /api/contract-types/:id —— 详情 + 更新 + 删除。"""

    permission_classes = _PERM_CLASSES

    @no_competition_scope
    @require_permissions(_CT_VIEW_PERM)
    def get(self, request, pk):
        ct = _get_contract_type(pk)
        return Response(ContractTypeSerializer(ct).data)

    @no_competition_scope
    @require_permissions(_CT_MANAGE_PERM)
    def patch(self, request, pk):
        ct = _get_contract_type(pk)
        serializer = ContractTypeSerializer(ct, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.update(ct, serializer.validated_data)
        return Response(ContractTypeSerializer(ct).data)

    @no_competition_scope
    @require_permissions(_CT_MANAGE_PERM)
    def delete(self, request, pk):
        ct = _get_contract_type(pk)
        # 有合同实例引用的合同类型不允许删除
        contract_count = Contract.objects.filter(contract_type=ct).count()
        if contract_count > 0:
            sample = list(
                Contract.objects.filter(contract_type=ct)
                .select_related("competition")
                .order_by("id")[:5]
            )
            detail = "、".join(
                f"「{c.name}」（比赛：{c.competition.name if c.competition_id else '未关联'}）"
                for c in sample
            )
            more = f" 等共 {contract_count} 份" if contract_count > len(sample) else ""
            raise BusinessError(
                f"该合同类型下仍有 {contract_count} 份合同实例，无法删除。涉及：{detail}{more}。"
                "请先删除这些合同实例后再试。",
                code=400,
                status_code=400,
            )
        ct.delete()
        return Response({"ok": True})


# ==================== 合同视图 ====================

class ContractCollectionAPIView(APIView):
    """GET/POST /api/contracts —— 列表（分页/增量/公司范围过滤）+ 创建。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_VIEW_PERM)
    def get(self, request):
        qs = Contract.objects.select_related("contract_type").all()
        qs = apply_competition_scope(
            qs, request.user, request.query_params.get("competitionId")
        )
        # 状态过滤
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)

        # 增量同步
        updated_after = request.query_params.get("updatedAfter")
        base_where = {}
        cid_raw = request.query_params.get("competitionId")
        if cid_raw:
            try:
                base_where["competition_id"] = int(cid_raw)
            except (TypeError, ValueError):
                pass
        if status:
            base_where["status"] = status
        where, incremental, _ = apply_updated_after(base_where, updated_after)
        if incremental:
            updated_qs = qs.filter(**where).order_by("-created_at")
            changed = [_serialize_contract(c) for c in updated_qs]
            changed = _filter_by_scope(changed, request.user)
            require_existing = _truthy(request.query_params.get("requireExistingIds"))
            all_current_ids = []
            if require_existing:
                base_rows = list(qs.order_by("-created_at"))
                scoped_base = _filter_by_scope(
                    [_serialize_contract(c) for c in base_rows], request.user
                )
                all_current_ids = [c["id"] for c in scoped_base]
            previous_ids = _parse_previous_ids(request.query_params.get("previousIds"))
            return Response(
                build_incremental_result(changed, all_current_ids, previous_ids, total=len(changed))
            )

        # 判断是否需要公司范围过滤（需解析 JSON parties 字段，无法下推到数据库 where）
        needs_scope = _needs_scope_filter(request.user)
        if not needs_scope:
            page, page_size, skip = parse_pagination(request.query_params)
            total = qs.count()
            rows = list(qs.order_by("-created_at")[skip : skip + page_size])
            items = _enrich_party_companies([_serialize_contract(c) for c in rows])
            return Response(paginated_response(items, total, page, page_size))

        # 有范围限制：需解析 JSON parties 做内存过滤，无法下推到数据库
        all_rows = list(qs.order_by("-created_at"))
        serialized = [_serialize_contract(c) for c in all_rows]
        filtered = _filter_by_scope(serialized, request.user)
        total = len(filtered)
        page, page_size, skip = parse_pagination(request.query_params)
        paged = filtered[skip : skip + page_size]
        paged = _enrich_party_companies(paged)
        return Response(paginated_response(paged, total, page, page_size))

    @require_permissions(_CONTRACT_MANAGE_PERM)
    def post(self, request):
        serializer = ContractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contract = serializer.create(serializer.validated_data)
        emit_resource_changed(
            "contract", contract.id, contract.competition_id, "created"
        )
        return Response(_serialize_contract(contract))


class ContractItemAPIView(APIView):
    """GET/DELETE /api/contracts/:id —— 详情 + 删除。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_VIEW_PERM)
    def get(self, request, pk):
        contract = _get_contract(pk, request.user)
        _assert_view_scope(request.user, contract)
        data = _serialize_contract(contract)
        return Response(_enrich_party_companies([data])[0])

    @require_permissions(_CONTRACT_MANAGE_PERM)
    def delete(self, request, pk):
        # 删除为高危操作：仅超级管理员可执行
        if getattr(request.user, "role", None) != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可删除合同", code=403, status_code=403)
        contract = _get_contract(pk, request.user)
        raw = request.query_params.get("competitionId")
        try:
            competition_id = int(raw) if raw else None
        except (TypeError, ValueError):
            competition_id = None
        assert_same_competition(contract.competition_id, competition_id)

        # 复原判定基于「是否曾落账」（ContractFieldEffect 记录存在）
        effect_count = ContractFieldEffect.objects.filter(contract_id=contract.id).count()
        with transaction.atomic():
            if effect_count > 0:
                engine_dict = _contract_to_engine_dict(contract)
                _engine.revert_contract(engine_dict)
            contract.delete()

        # 复原基础字段后级联重算计算字段
        parties = parse_json_array(contract.parties)
        affected = [
            p for p in parties
            if isinstance(p, dict) and not p.get("isHost") and isinstance(p.get("companyId"), int)
        ]
        for p in affected:
            _recompute_calc_fields_safe(p["companyId"])
            emit_resource_changed(
                "company-field", p["companyId"], contract.competition_id, "updated"
            )
        return Response({"ok": True})


class ContractExecuteAPIView(APIView):
    """POST /api/contracts/:id/execute —— 执行合同（会签落账）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_AUDIT_PERM)
    def post(self, request, pk):
        contract = _get_contract(pk, request.user)
        if contract.status == "EXECUTED":
            raise BusinessError("合同已执行，不可重复执行", code=400, status_code=400)
        if contract.status == "TERMINATED":
            raise BusinessError("合同已终止，不可再次执行", code=400, status_code=400)

        # 执行方范围校验（会签模型核心）
        _assert_execute_scope(request.user, contract)

        # 编号分步补全：执行前校验所有非主办方参与方均已填写编号
        parties = parse_json_array(contract.parties)
        selectable = [p for p in parties if not p.get("isHost")]
        for p in selectable:
            cn = p.get("contractNumber")
            if cn is None or str(cn).strip() == "":
                raise BusinessError(
                    f"存在未编号的参与方，无法执行：角色 {p.get('role', '?')}",
                    code=400,
                    status_code=400,
                )

        # 执行时可覆盖输入参数
        inputs_override = request.data.get("inputs") if isinstance(request.data, dict) else None
        inputs_raw = (
            json.dumps(inputs_override, ensure_ascii=False) if inputs_override is not None
            else contract.inputs
        )

        engine_dict = _contract_to_engine_dict(contract)
        engine_dict["inputs"] = inputs_raw

        with transaction.atomic():
            engine_result = _engine.execute(engine_dict)
            contract.inputs = inputs_raw
            contract.status = "EXECUTED"
            contract.signed_at = contract.signed_at or timezone.now()
            contract.executed_at = timezone.now()
            contract.execution_log = json.dumps(engine_result["log"], ensure_ascii=False)
            contract.execution_result = json.dumps(engine_result["result"], ensure_ascii=False)
            contract.save()

        # 级联重算计算字段 + 广播刷新
        affected_companies = set()
        for key in (engine_result.get("result") or {}).get("fields", {}):
            try:
                cid = int(key.split(":")[0])
                if cid:
                    affected_companies.add(cid)
            except (ValueError, TypeError):
                pass
        for cid in affected_companies:
            _recompute_calc_fields_safe(cid)
            emit_resource_changed("company-field", cid, contract.competition_id, "updated")

        emit_resource_changed("contract", contract.id, contract.competition_id, "updated")
        return Response(_serialize_contract(contract))


class ContractPartyNumbersAPIView(APIView):
    """PATCH /api/contracts/:id/party-numbers —— 分步补全合同编号。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_AUDIT_PERM)
    def patch(self, request, pk):
        contract = _get_contract(pk, request.user)
        if contract.status == "EXECUTED":
            raise BusinessError("合同已执行，编号不可再修改", code=400, status_code=400)

        party_numbers = request.data.get("partyNumbers") if isinstance(request.data, dict) else None
        if not isinstance(party_numbers, dict):
            raise BusinessError("partyNumbers 必须为对象", code=400, status_code=400)

        parties = parse_json_array(contract.parties)
        role_set = {p.get("role") for p in parties if isinstance(p, dict)}
        for role in party_numbers:
            if role not in role_set:
                raise BusinessError(f"合同不存在角色 {role}", code=400, status_code=400)

        for p in parties:
            if not isinstance(p, dict) or p.get("isHost"):
                continue
            role = p.get("role")
            if role not in party_numbers:
                continue
            # 权限隔离：只能改自己审核范围内公司的编号
            _assert_edit_party_scope(request.user, p.get("companyId"), role)
            v = party_numbers[role]
            p["contractNumber"] = v if (v is not None and str(v).strip()) else None

        # 自动升降 PENDING_EXEC
        new_status = contract.status
        if contract.status in ("DRAFT", "PENDING_EXEC"):
            selectable = [p for p in parties if isinstance(p, dict) and not p.get("isHost")]
            all_filled = (
                len(selectable) > 0
                and all(
                    p.get("contractNumber") is not None and str(p["contractNumber"]).strip() != ""
                    for p in selectable
                )
            )
            new_status = "PENDING_EXEC" if all_filled else "DRAFT"

        contract.parties = json.dumps(parties, ensure_ascii=False)
        contract.status = new_status
        contract.save()

        emit_resource_changed("contract", contract.id, contract.competition_id, "updated")
        return Response(_serialize_contract(contract))


class ContractPrecheckAPIView(APIView):
    """POST /api/contracts/:id/precheck —— 预检条件（不落账）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_AUDIT_PERM)
    def post(self, request, pk):
        contract = _get_contract(pk, request.user)
        _assert_execute_scope(request.user, contract)
        engine_dict = _contract_to_engine_dict(contract)
        checks = _engine.precheck(engine_dict)
        return Response({"checks": checks})


class ContractStatusAPIView(APIView):
    """PATCH /api/contracts/:id/status —— 标记合同状态（仅 TERMINATED）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_MANAGE_PERM)
    def patch(self, request, pk):
        contract = _get_contract(pk, request.user)
        status = request.data.get("status") if isinstance(request.data, dict) else None
        if status == "EXECUTED":
            raise BusinessError("禁止直接置为已执行，请走执行流程", code=400, status_code=400)
        if status in ("DRAFT", "PENDING_EXEC"):
            raise BusinessError("禁止直接回退合同状态，请走编号补全/执行流程", code=400, status_code=400)
        if status != "TERMINATED":
            raise BusinessError("不允许的状态值", code=400, status_code=400)

        contract.status = status
        contract.save()
        emit_resource_changed("contract", contract.id, contract.competition_id, "updated")
        return Response(_serialize_contract(contract))


class ContractImpactAPIView(APIView):
    """GET /api/contracts/:id/impact —— 删除影响。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_CONTRACT_VIEW_PERM)
    def get(self, request, pk):
        contract = _get_contract(pk, request.user)
        effect_count = ContractFieldEffect.objects.filter(contract_id=contract.id).count()
        children = []
        if effect_count > 0:
            children.append({"label": "合同字段效果", "count": effect_count})
        return Response({"name": contract.name, "children": children})


# ==================== 工具函数 ====================

def _truthy(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_previous_ids(raw) -> list | None:
    if not raw:
        return None
    ids: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            pass
    return ids or None


def _get_contract_type(pk: int) -> ContractType:
    try:
        return ContractType.objects.get(pk=pk)
    except ContractType.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)


def _get_contract(pk: int, user) -> Contract:
    """取合同并做比赛域隔离，越权视作不存在。"""
    try:
        contract = Contract.objects.select_related("contract_type").get(pk=pk)
    except Contract.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(user, "role", None) != "SUPER_ADMIN":
        if contract.competition_id != getattr(user, "competition_id", None):
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return contract


def _serialize_contract(contract: Contract) -> dict:
    """序列化合同（不含 party companyName 补全，由 _enrich_party_companies 后置）。"""
    return ContractSerializer(contract).data


def _contract_to_engine_dict(contract: Contract) -> dict:
    """把 Django Contract 模型实例转为引擎所需的 dict。

    引擎期望 contract_type 子字典含 camelCase 键 inputSchema
    （与原 NestJS Prisma 字段名一致），其余 effects/conditions 键名相同。
    """
    ct = contract.contract_type
    return {
        "id": contract.id,
        "competition_id": contract.competition_id,
        "parties": contract.parties,
        "inputs": contract.inputs,
        "executed_at": contract.executed_at,
        "created_at": contract.created_at,
        "contract_type": {
            "id": ct.id,
            "effects": ct.effects,
            "conditions": ct.conditions or "[]",
            "inputSchema": ct.input_schema or "[]",
        },
    }


def _enrich_party_companies(items: list[dict]) -> list[dict]:
    """给合同参与方补全公司名称（仅用于列表/详情展示，不写入存储）。

    一次性收集所有 companyId 后批量查表，避免 N+1；
    主办方(isHost)无公司，公司名置 None。
    """
    company_ids: set[int] = set()
    for it in items:
        parties = it.get("parties") if isinstance(it.get("parties"), list) else []
        for p in parties:
            if isinstance(p, dict) and p.get("companyId") is not None:
                company_ids.add(int(p["companyId"]))
    name_by_id: dict[int, str] = {}
    if company_ids:
        from apps.companies.models import Company

        for c in Company.objects.filter(pk__in=company_ids).values("id", "name"):
            name_by_id[c["id"]] = c["name"]
    for it in items:
        parties = it.get("parties") if isinstance(it.get("parties"), list) else []
        for p in parties:
            if not isinstance(p, dict):
                continue
            if p.get("isHost"):
                p["companyName"] = None
            elif p.get("companyId") is not None:
                p["companyName"] = name_by_id.get(int(p["companyId"]))
            else:
                p["companyName"] = None
    return items


# ==================== 范围过滤（会签模型核心） ====================

def _get_party_company_ids(parties_raw: str) -> list[int]:
    """取合同实际参与方（非主办方）的公司 id 列表。"""
    parties = parse_json_array(parties_raw)
    return [
        int(p["companyId"])
        for p in parties
        if isinstance(p, dict)
        and not p.get("isHost")
        and isinstance(p.get("companyId"), (int, float))
    ]


def _contract_in_scopes(parties_raw: str, scopes: list[int]) -> bool:
    """合同是否至少有一个参与方公司落在范围内（接受 JSON 字符串或已解析列表）。

    空范围 = 不在任何范围内（审核范围分支：看不到任何合同）。
    """
    if not scopes:
        return False
    company_ids = _get_party_company_ids(parties_raw)
    return any(cid in scopes for cid in company_ids)


def _parties_list_in_scopes(parties: list, scopes: list[int]) -> bool:
    """已解析的参与方列表是否至少有一个公司落在范围内。"""
    if not scopes:
        return False
    for p in parties:
        if (
            isinstance(p, dict)
            and not p.get("isHost")
            and isinstance(p.get("companyId"), (int, float))
            and int(p["companyId"]) in scopes
        ):
            return True
    return False


def _needs_scope_filter(user) -> bool:
    """判断是否需要公司范围过滤（需解析 JSON parties 字段，无法下推到数据库 where）。"""
    if not user:
        return False
    can_audit = has_permission(user.role, user.permissions_list, _CONTRACT_AUDIT_PERM)
    can_execute = has_permission(user.role, user.permissions_list, "contract:execute")
    can_manage = has_permission(user.role, user.permissions_list, _CONTRACT_MANAGE_PERM)
    can_view = has_permission(user.role, user.permissions_list, _CONTRACT_VIEW_PERM)
    if can_audit and not can_execute:
        return True
    if can_view and not can_audit and not can_execute and not can_manage:
        scopes = user.contract_view_company_scopes_list
        return len(scopes) > 0
    return False


def _filter_by_scope(items: list[dict], user) -> list[dict]:
    """公司范围过滤（复用于全量/增量分支）。

    输入为已序列化的合同 dict（parties 已解析为列表）。
    """
    if not user:
        return items
    can_audit = has_permission(user.role, user.permissions_list, _CONTRACT_AUDIT_PERM)
    can_execute = has_permission(user.role, user.permissions_list, "contract:execute")
    can_manage = has_permission(user.role, user.permissions_list, _CONTRACT_MANAGE_PERM)
    can_view = has_permission(user.role, user.permissions_list, _CONTRACT_VIEW_PERM)

    # 审核范围：仅 contract:audit（无 execute）的账号按 companyScopes 限制可审核合同；
    # 空范围 = 看不到任何合同
    if can_audit and not can_execute:
        scopes = user.company_scopes_list
        return [
            c for c in items
            if _parties_list_in_scopes(c.get("parties", []), scopes)
        ]

    # 合同查看范围：仅持纯 contract:view 的账号按 contractViewCompanyScopes 限制可见合同；
    # 空范围 = 不限制（可见全部合同）
    if can_view and not can_audit and not can_execute and not can_manage:
        scopes = user.contract_view_company_scopes_list
        if not scopes:
            return items
        return [
            c for c in items
            if _parties_list_in_scopes(c.get("parties", []), scopes)
        ]

    return items


def _get_last_signatory_company_id(contract: Contract) -> int | None:
    """取最后一个「非主办方」参与方的公司 id（即会签执行方）。"""
    parties = parse_json_array(contract.parties)
    real = [
        p for p in parties
        if isinstance(p, dict) and not p.get("isHost") and isinstance(p.get("companyId"), (int, float))
    ]
    return int(real[-1]["companyId"]) if real else None


def _assert_execute_scope(user, contract: Contract) -> None:
    """执行方范围校验（会签模型核心）。

    - contract:execute / contract:manage / 超管 直接放行
    - 仅 contract:audit 公司级管理员：必须是最后一个参与方公司在其 companyScopes 内
    """
    if not user:
        return
    if has_permission(user.role, user.permissions_list, "contract:execute"):
        return
    can_audit = has_permission(user.role, user.permissions_list, _CONTRACT_AUDIT_PERM)
    if not can_audit:
        raise BusinessError("无权执行合同", code=403, status_code=403)
    last_cid = _get_last_signatory_company_id(contract)
    scopes = user.company_scopes_list
    if last_cid is None or last_cid not in scopes:
        raise BusinessError(
            "仅合同最后一方参与公司的管理员可执行", code=403, status_code=403
        )


def _assert_view_scope(user, contract: Contract) -> None:
    """合同查看范围校验：仅持纯 contract:view 的账号受 contractViewCompanyScopes 约束。"""
    if not user:
        return
    can_execute = has_permission(user.role, user.permissions_list, "contract:execute")
    can_audit = has_permission(user.role, user.permissions_list, _CONTRACT_AUDIT_PERM)
    can_manage = has_permission(user.role, user.permissions_list, _CONTRACT_MANAGE_PERM)
    if can_execute or can_audit or can_manage:
        return
    scopes = user.contract_view_company_scopes_list
    if not scopes:
        return  # 未配置范围 = 不限制
    if not _contract_in_scopes(contract.parties, scopes):
        raise BusinessError("无权查看其他公司的合同", code=403, status_code=403)


def _assert_edit_party_scope(user, company_id, role: str) -> None:
    """单公司编辑范围校验（用于分步补全编号）。"""
    if not user:
        return
    can_execute = has_permission(user.role, user.permissions_list, "contract:execute")
    can_manage = has_permission(user.role, user.permissions_list, _CONTRACT_MANAGE_PERM)
    if can_execute or can_manage:
        return
    can_audit = has_permission(user.role, user.permissions_list, _CONTRACT_AUDIT_PERM)
    if not can_audit:
        raise BusinessError("无权修改合同编号", code=403, status_code=403)
    scopes = user.company_scopes_list
    if company_id not in scopes:
        raise BusinessError(
            f"无权修改角色 {role} 所属公司的合同编号", code=403, status_code=403
        )


def _recompute_calc_fields_safe(company_id: int) -> None:
    """计算字段级联重算（计算引擎为独立模块，待接入时自动生效）。"""
    try:
        from apps.company_fields.views import _recompute_calc_fields

        _recompute_calc_fields(company_id)
    except Exception:
        pass
