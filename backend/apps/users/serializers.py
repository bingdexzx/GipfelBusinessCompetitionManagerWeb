"""用户序列化器：camelCase 对齐前端契约。

permissions / companyScopes 等在 DB 以 JSON 字符串（TextField）存储，
序列化输出为数组、反序列化输入接收数组并落库为 JSON 字符串。
"""
from __future__ import annotations

import json

from rest_framework import serializers

from apps.common.permissions import is_valid_permissions
from apps.users.models import User

_ROLE_CHOICES = [c[0] for c in User.ROLE_CHOICES]

# 序列化字段名(camelCase) → 模型字段(snake_case) 中以 JSON 字符串存储的字段
_JSON_SCOPE_FIELDS = (
    ("permissions", "permissions"),
    ("companyScopes", "company_scopes"),
    ("viewCompanyScopes", "view_company_scopes"),
    ("contractViewCompanyScopes", "contract_view_company_scopes"),
    ("stockCompanyScopes", "stock_company_scopes"),
)


def dump_json_scope(value):
    """list/None → JSON 字符串；None 保留为 null（表示按角色继承）。"""
    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    # 兼容前端偶尔传入字符串
    return json.dumps(value, ensure_ascii=False)


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(max_length=128, trim_whitespace=True)
    role = serializers.ChoiceField(choices=_ROLE_CHOICES, default="PLAYER")
    displayName = serializers.CharField(
        max_length=128, allow_null=True, allow_blank=True, required=False
    )
    mustChangePassword = serializers.BooleanField(required=False, default=False)
    permissions = serializers.JSONField(allow_null=True, required=False)
    companyScopes = serializers.JSONField(allow_null=True, required=False)
    viewCompanyScopes = serializers.JSONField(allow_null=True, required=False)
    contractViewCompanyScopes = serializers.JSONField(allow_null=True, required=False)
    stockCompanyScopes = serializers.JSONField(allow_null=True, required=False)
    competitionId = serializers.IntegerField(allow_null=True, required=False)
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False
    )

    def to_representation(self, instance: User) -> dict:
        return {
            "id": instance.id,
            "username": instance.username,
            "role": instance.role,
            "displayName": instance.display_name,
            "mustChangePassword": instance.must_change_password,
            "permissions": instance.permissions_list,
            "companyScopes": instance.company_scopes_list,
            "viewCompanyScopes": instance.view_company_scopes_list,
            "contractViewCompanyScopes": instance.contract_view_company_scopes_list,
            "stockCompanyScopes": instance.stock_company_scopes_list,
            "competitionId": instance.competition_id,
        }

    # ---------- 校验 ----------
    def validate_username(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("用户名不能为空")
        # 创建场景校验唯一；更新场景由视图禁止改名（username 不参与更新）
        if self.instance is None and User.objects.filter(username=value).exists():
            raise serializers.ValidationError("用户名已存在")
        return value

    def validate_permissions(self, value):
        if value is None:
            return value
        if not is_valid_permissions(value):
            raise serializers.ValidationError("包含未知权限 key")
        return value

    def validate_password(self, value):
        if not value:
            return value
        if len(value) < 8:
            raise serializers.ValidationError("密码长度不能少于 8 位")
        return value

    def validate(self, attrs: dict) -> dict:
        # 创建时必须带密码
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "创建用户时密码必填"})
        return attrs

    # ---------- 创建/更新 ----------
    def create(self, validated_data: dict) -> User:
        password = validated_data.pop("password")
        competition_id = validated_data.get("competitionId")
        if competition_id is not None:
            self._assert_competition_exists(competition_id)
        user = User(
            username=validated_data["username"],
            role=validated_data.get("role", "PLAYER"),
            display_name=validated_data.get("displayName"),
            must_change_password=validated_data.get("mustChangePassword", False),
            competition_id=competition_id,
        )
        self._apply_json_fields(user, validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance: User, validated_data: dict) -> User:
        # 不允许修改用户名
        validated_data.pop("username", None)
        # 密码不在普通更新中处理（走 /password 专用端点）
        validated_data.pop("password", None)
        if "role" in validated_data:
            instance.role = validated_data["role"]
        if "displayName" in validated_data:
            instance.display_name = validated_data["displayName"]
        if "mustChangePassword" in validated_data:
            instance.must_change_password = validated_data["mustChangePassword"]
        if "competitionId" in validated_data:
            cid = validated_data["competitionId"]
            if cid is not None:
                self._assert_competition_exists(cid)
            instance.competition_id = cid
        self._apply_json_fields(instance, validated_data)
        instance.save()
        return instance

    # ---------- 辅助 ----------
    def _apply_json_fields(self, user: User, data: dict) -> None:
        for src, dst in _JSON_SCOPE_FIELDS:
            if src in data:
                setattr(user, dst, dump_json_scope(data[src]))

    def _assert_competition_exists(self, cid: int) -> None:
        from apps.competitions.models import Competition

        if not Competition.objects.filter(pk=cid).exists():
            raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})
