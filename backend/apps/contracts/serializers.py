"""合同序列化器：camelCase 对齐前端契约。

ContractTypeSerializer：全局模板，JSON 字段（partyRoles / inputSchema /
effects / conditions / graph）在库中存储为文本，输出时解析为对象/数组。

ContractSerializer：比赛级实例，JSON 字段（parties / inputs /
executionLog / executionResult）同样存储为文本，输出时解析。含嵌套 contractType。
"""
from __future__ import annotations

import json
from typing import Any

from rest_framework import serializers

from .models import Contract, ContractType


# ==================== JSON 工具 ====================

def _parse_json(raw: Any, fallback: Any) -> Any:
    """把 JSON 文本安全解析为对象；已是对象则原样返回。"""
    if raw is None:
        return fallback
    if isinstance(raw, (list, dict)):
        return raw
    if not isinstance(raw, str):
        return fallback
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return fallback


def _to_stored(value: Any, default: str = "[]") -> str:
    """把对象序列化为 JSON 文本存储。None → default。"""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _assert_competition_exists(cid: int) -> None:
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


# ==================== ContractType ====================

class ContractTypeSerializer(serializers.Serializer):
    """合同类型模板序列化器。

    JSON 字段用 JSONField 接收（支持对象或 JSON 字符串），存储为 JSON 文本。
    输出时 to_representation 解析回对象。
    """

    id = serializers.IntegerField(read_only=True)
    key = serializers.CharField(max_length=128, trim_whitespace=True)
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    description = serializers.CharField(allow_null=True, required=False, allow_blank=True)
    partyCount = serializers.IntegerField(default=2, required=False)
    partyRoles = serializers.JSONField(default=list, required=False)
    inputSchema = serializers.JSONField(default=list, required=False)
    effects = serializers.JSONField(default=list, required=False)
    conditions = serializers.JSONField(default=list, required=False)
    graph = serializers.JSONField(allow_null=True, required=False)
    schemaVersion = serializers.IntegerField(default=1, required=False)
    enabled = serializers.BooleanField(default=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: ContractType) -> dict:
        return {
            "id": instance.id,
            "key": instance.key,
            "name": instance.name,
            "description": instance.description,
            "partyCount": instance.party_count,
            "partyRoles": _parse_json(instance.party_roles, []),
            "inputSchema": _parse_json(instance.input_schema, []),
            "effects": _parse_json(instance.effects, []),
            "conditions": _parse_json(instance.conditions, []),
            "graph": _parse_json(instance.graph, None) if instance.graph else None,
            "schemaVersion": instance.schema_version,
            "enabled": instance.enabled,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_key(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("key 不能为空")
        return value

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("名称不能为空")
        return value

    def _party_count_from(self, party_roles: Any) -> int:
        arr = _parse_json(party_roles, [])
        return len(arr) if isinstance(arr, list) else 0

    def create(self, validated_data: dict) -> ContractType:
        key = validated_data["key"]
        if ContractType.objects.filter(key=key).exists():
            raise serializers.ValidationError(
                {"key": f"合同类型 key 已存在: {key}"}
            )
        party_roles = validated_data.get("partyRoles", [])
        graph_val = validated_data.get("graph")
        return ContractType.objects.create(
            key=key,
            name=validated_data["name"],
            description=validated_data.get("description"),
            party_count=self._party_count_from(party_roles),
            party_roles=_to_stored(party_roles),
            input_schema=_to_stored(validated_data.get("inputSchema", [])),
            effects=_to_stored(validated_data.get("effects", [])),
            conditions=_to_stored(validated_data.get("conditions", [])),
            graph=_to_stored(graph_val, default="{}") if graph_val is not None else None,
            schema_version=validated_data.get("schemaVersion", 1),
            enabled=validated_data.get("enabled", True),
        )

    def update(self, instance: ContractType, validated_data: dict) -> ContractType:
        if "name" in validated_data:
            instance.name = validated_data["name"]
        if "description" in validated_data:
            instance.description = validated_data["description"]
        if "partyRoles" in validated_data:
            instance.party_roles = _to_stored(validated_data["partyRoles"])
            instance.party_count = self._party_count_from(validated_data["partyRoles"])
        if "inputSchema" in validated_data:
            instance.input_schema = _to_stored(validated_data["inputSchema"])
        if "effects" in validated_data:
            instance.effects = _to_stored(validated_data["effects"])
        if "conditions" in validated_data:
            instance.conditions = _to_stored(validated_data["conditions"])
        if "graph" in validated_data:
            graph_val = validated_data["graph"]
            instance.graph = _to_stored(graph_val, default="{}") if graph_val is not None else None
        if "schemaVersion" in validated_data:
            instance.schema_version = validated_data["schemaVersion"]
        if "enabled" in validated_data:
            instance.enabled = validated_data["enabled"]
        instance.save()
        return instance


# ==================== Contract ====================

class ContractSerializer(serializers.Serializer):
    """合同实例序列化器。

    创建时仅接收 competitionId / contractTypeId / parties / inputs。
    输出含嵌套 contractType（ContractTypeSerializer.to_representation）。
    """

    id = serializers.IntegerField(read_only=True)
    competitionId = serializers.IntegerField()
    contractTypeId = serializers.IntegerField()
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    parties = serializers.JSONField(default=list, required=False)
    inputs = serializers.JSONField(default=dict, required=False)
    executionLog = serializers.JSONField(allow_null=True, required=False)
    executionResult = serializers.JSONField(allow_null=True, required=False)
    signedAt = serializers.DateTimeField(read_only=True)
    executedAt = serializers.DateTimeField(read_only=True)
    contractType = ContractTypeSerializer(read_only=True)
    createdAt = serializers.DateTimeField(read_only=True)
    updatedAt = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance: Contract) -> dict:
        ct_data = None
        if instance.contract_type_id is not None:
            # 避免重复查询：若已 select_related 则直接取，否则单独查询
            ct = instance.contract_type  # 触发外键缓存
            if ct is not None:
                ct_data = ContractTypeSerializer(ct).data
        return {
            "id": instance.id,
            "competitionId": instance.competition_id,
            "contractTypeId": instance.contract_type_id,
            "name": instance.name,
            "status": instance.status,
            "parties": _parse_json(instance.parties, []),
            "inputs": _parse_json(instance.inputs, {}),
            "executionLog": _parse_json(instance.execution_log, None) if instance.execution_log else None,
            "executionResult": _parse_json(instance.execution_result, None) if instance.execution_result else None,
            "signedAt": instance.signed_at,
            "executedAt": instance.executed_at,
            "contractType": ct_data,
            "createdAt": instance.created_at,
            "updatedAt": instance.updated_at,
        }

    def validate_competitionId(self, value: int) -> int:
        if not isinstance(value, int) or value <= 0:
            raise serializers.ValidationError("competitionId 必须为正整数")
        return value

    def validate_contractTypeId(self, value: int) -> int:
        if not isinstance(value, int) or value <= 0:
            raise serializers.ValidationError("contractTypeId 必须为正整数")
        if not ContractType.objects.filter(pk=value).exists():
            raise serializers.ValidationError(f"合同类型 {value} 不存在")
        return value

    def validate_parties(self, value: Any) -> Any:
        """校验参与方结构：至少一个非主办方参与方。"""
        parties = _parse_json(value, [])
        if not isinstance(parties, list):
            raise serializers.ValidationError("parties 必须为数组")
        selectable = [p for p in parties if isinstance(p, dict) and not p.get("isHost")]
        if not selectable:
            raise serializers.ValidationError("至少需要一个实际公司参与方")
        # 规范化非主办方编号：空白/空值统一置 None
        for p in selectable:
            cn = p.get("contractNumber")
            p["contractNumber"] = cn if (cn is not None and str(cn).strip()) else None
        return parties

    def create(self, validated_data: dict) -> Contract:
        cid = validated_data["competitionId"]
        _assert_competition_exists(cid)

        ct_id = validated_data["contractTypeId"]
        ct = ContractType.objects.get(pk=ct_id)

        parties = _to_stored(validated_data.get("parties", []))
        inputs = _to_stored(validated_data.get("inputs", {}), default="{}")

        return Contract.objects.create(
            competition_id=cid,
            contract_type_id=ct_id,
            name=ct.name,  # 合同名称取合同类型名称
            status="DRAFT",
            parties=parties,
            inputs=inputs,
        )
