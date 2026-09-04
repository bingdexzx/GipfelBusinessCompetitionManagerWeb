"""共享小工具：集中收敛各 app 重复定义的同名 helper，保证同名同实现。

本模块仅依赖 rest_framework 与 apps.common.permissions，不导入任何模型（需要的模型
在函数内延迟导入），因此可被任意 app 安全引用，无循环依赖。
"""
from __future__ import annotations

import os

from django.db import models
from rest_framework import serializers


def truthy(value) -> bool:
    """把查询串 / 表单里的「真值」形态统一判为 True。"""
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_previous_ids(raw) -> list[int] | None:
    """解析逗号分隔的 previousIds，用于增量同步 deletedIds 计算。"""
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


def effective_competition_id(request) -> int | None:
    """解析当前请求的比赛上下文。

    SUPER_ADMIN 可取 query 中的 competitionId（可空 = 跨全部比赛）；其余角色强制取
    自身 competition_id，**忽略前端传入的 competitionId**（防越权读/写其他比赛）。
    """
    raw = request.query_params.get("competitionId")
    cid = None
    if raw:
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            cid = None
    if getattr(request.user, "role", None) == "SUPER_ADMIN":
        return cid
    return getattr(request.user, "competition_id", None)


def company_list_scopes(user, view_perm: str = "company:view") -> list | None:
    """返回 company:view 作用域内可见公司 id 列表；None 表示不过滤。

    - SUPER_ADMIN：不过滤
    - 无 company:view 权限：不过滤（由权限层拦截）
    - 有 company:view 且 viewCompanyScopes 非空：仅这些公司
    - 有 company:view 且 viewCompanyScopes 为空：不过滤（可见本比赛全部公司）
    """
    from apps.common.permissions import has_permission

    if getattr(user, "role", None) == "SUPER_ADMIN":
        return None
    if not has_permission(user.role, user.permissions_list, view_perm):
        return None
    scopes = user.view_company_scopes_list
    return scopes if scopes else None


def get_company_scoped(pk, user, view_perm: str = "company:view"):
    """取公司并做「比赛域 + viewCompanyScopes」双重隔离，越权视作不存在。

    companies/views 与 company_fields/views 共用本实现。
    """
    from apps.common.exceptions import BusinessError
    from apps.companies.models import Company

    try:
        company = Company.objects.get(pk=pk)
    except Company.DoesNotExist:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(user, "role", None) != "SUPER_ADMIN":
        if company.competition_id != getattr(user, "competition_id", None):
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    scopes = company_list_scopes(user, view_perm)
    if scopes is not None:
        try:
            pk_int = int(pk)
        except (TypeError, ValueError):
            pk_int = pk
        if pk_int not in scopes:
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return company


def assert_competition_exists(cid: int) -> None:
    """校验比赛存在；不存在时抛 DRF 校验错误（供序列化器与视图共用）。"""
    from apps.competitions.models import Competition

    if not Competition.objects.filter(pk=cid).exists():
        raise serializers.ValidationError({"competitionId": f"比赛 {cid} 不存在"})


def _trusted_proxy_addrs() -> set[str]:
    """可信代理地址集合：默认仅回环（标准 nginx 反代部署形态）。

    可通过环境变量 TRUSTED_PROXIES 追加（逗号分隔精确 IP），例如
    TRUSTED_PROXIES=10.0.0.5,192.168.1.10。仅当请求的 REMOTE_ADDR 命中
    该集合时才信任 X-Real-IP，防止绕过 nginx 直连后端时伪造该头。
    """
    addrs: set[str] = {"127.0.0.1", "::1"}
    raw = os.environ.get("TRUSTED_PROXIES", "")
    if raw:
        addrs |= {a.strip() for a in raw.split(",") if a.strip()}
    return addrs


def client_ip(request) -> str:
    """取客户端 IP：仅当请求来自可信代理（默认回环，即经 nginx 反代）时才信任
    其注入的 X-Real-IP（nginx 取自 $remote_addr，不可伪造）。

    绕过 nginx 直连后端（如 --bind 0.0.0.0 内网联调）时，REMOTE_ADDR 不在
    可信集合内，直接回退 REMOTE_ADDR —— 防止伪造 X-Real-IP 使登录限速等
    按 IP 的防护失效。始终不信任 X-Forwarded-For 首段（攻击者可伪造）。
    """
    if request is None:
        return "unknown"
    remote = request.META.get("REMOTE_ADDR", "unknown")
    if remote in _trusted_proxy_addrs():
        real_ip = request.headers.get("X-Real-IP") or request.META.get("HTTP_X_REAL_IP")
        if real_ip:
            return real_ip.strip().split(",")[0].strip()
    return remote


def to_camel(name: str) -> str:
    """snake_case → camelCase。"""
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def instance_to_camel(instance, include_id: bool = True) -> dict | None:
    """把模型实例的所有具体字段序列化为 camelCase dict。

    - 外键字段输出为 <stem>Id（取 _id 列值）
    - 时间字段输出 ISO 字符串
    - include_id=False 时省略自增 id（用于复合关联表）
    """
    if instance is None:
        return None
    data: dict = {}
    for f in instance._meta.concrete_fields:
        if not include_id and f.name == "id":
            continue
        if isinstance(f, (models.ForeignKey, models.OneToOneField)):
            data[to_camel(f.name) + "Id"] = getattr(instance, f.attname)
        elif isinstance(f, (models.DateTimeField, models.DateField)):
            v = getattr(instance, f.name)
            data[to_camel(f.name)] = v.isoformat() if v else None
        else:
            data[to_camel(f.name)] = getattr(instance, f.name)
    return data
