"""权限目录与 RBAC：对应原 server/src/permissions/catalog.ts。

31 个权限 key，18 个域，动作等级蕴含：
    manage ⊇ execute ⊇ audit ⊇ edit ⊇ view
（合同域自定义：manage ⊇ execute ⊇ audit ⊇ view）
"""
from __future__ import annotations

from typing import Iterable

# ==================== 动作等级表 ====================
DEFAULT_ACTION_RANKS = {
    "view": 10,
    "edit": 20,
    "manage": 30,
    "execute": 40,
    "audit": 50,
}

# 合同域自定义等级（D1 确认：manage ⊇ execute ⊇ audit ⊇ view）
CONTRACT_ACTION_RANKS = {
    "view": 10,
    "audit": 20,
    "execute": 30,
    "manage": 40,
}


# ==================== 目录定义 ====================
PERMISSION_CATALOG = [
    {
        "key": "competition",
        "label": "比赛管理",
        "group": "比赛",
        "actions": [{"key": "competition:manage", "action": "manage", "label": "管理（增删改）"}],
    },
    {
        "key": "data:material",
        "label": "原料管理",
        "group": "数据",
        "actions": [
            {"key": "data:material:view", "action": "view", "label": "查看"},
            {"key": "data:material:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:part",
        "label": "零件管理",
        "group": "数据",
        "actions": [
            {"key": "data:part:view", "action": "view", "label": "查看"},
            {"key": "data:part:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:product",
        "label": "产品管理",
        "group": "数据",
        "actions": [
            {"key": "data:product:view", "action": "view", "label": "查看"},
            {"key": "data:product:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:map",
        "label": "地图管理",
        "group": "数据",
        "actions": [
            {"key": "data:map:view", "action": "view", "label": "查看"},
            {"key": "data:map:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:infrastructure",
        "label": "基建管理",
        "group": "数据",
        "actions": [
            {"key": "data:infrastructure:view", "action": "view", "label": "查看"},
            {"key": "data:infrastructure:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:tech",
        "label": "科技树管理",
        "group": "数据",
        "actions": [
            {"key": "data:tech:view", "action": "view", "label": "查看"},
            {"key": "data:tech:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:fuel",
        "label": "燃料管理",
        "group": "数据",
        "actions": [
            {"key": "data:fuel:view", "action": "view", "label": "查看"},
            {"key": "data:fuel:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:vehicle",
        "label": "载具管理",
        "group": "数据",
        "actions": [
            {"key": "data:vehicle:view", "action": "view", "label": "查看"},
            {"key": "data:vehicle:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:warehouse",
        "label": "仓库管理",
        "group": "数据",
        "actions": [
            {"key": "data:warehouse:view", "action": "view", "label": "查看"},
            {"key": "data:warehouse:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:productionLine",
        "label": "生产线管理",
        "group": "数据",
        "actions": [
            {"key": "data:productionLine:view", "action": "view", "label": "查看"},
            {"key": "data:productionLine:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "data:region",
        "label": "区域管理",
        "group": "区域",
        "actions": [
            {"key": "data:region:view", "action": "view", "label": "查看"},
            {"key": "data:region:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "consumer-demand",
        "label": "消费者需求",
        "group": "区域",
        "actions": [
            {"key": "consumer-demand:view", "action": "view", "label": "查看"},
            {"key": "consumer-demand:edit", "action": "edit", "label": "编辑（增删改）"},
        ],
    },
    {
        "key": "contractType",
        "label": "合同类型管理",
        "group": "合同",
        "actions": [
            {"key": "contractType:view", "action": "view", "label": "查看"},
            {"key": "contractType:manage", "action": "manage", "label": "管理（增删改）"},
        ],
    },
    {
        "key": "contract",
        "label": "合同管理",
        "group": "合同",
        "actionRank": CONTRACT_ACTION_RANKS,
        "actions": [
            {"key": "contract:view", "action": "view", "label": "查看"},
            {"key": "contract:audit", "action": "audit", "label": "审核（公司范围，仅限范围内公司合同）"},
            {"key": "contract:execute", "action": "execute", "label": "执行（比赛级，不限公司）"},
            {"key": "contract:manage", "action": "manage", "label": "管理（新建/删除）"},
        ],
    },
    {
        "key": "industryType",
        "label": "产业类型管理",
        "group": "产业",
        "actions": [
            {"key": "industryType:view", "action": "view", "label": "查看"},
            {"key": "industryType:manage", "action": "manage", "label": "管理（增删改）"},
        ],
    },
    {
        "key": "company",
        "label": "公司管理",
        "group": "产业",
        "actions": [
            {"key": "company:view", "action": "view", "label": "查看（读取公司产业字段）"},
            {"key": "company:manage", "action": "manage", "label": "管理（增删改公司）"},
        ],
    },
    {
        "key": "account",
        "label": "账户管理",
        "group": "系统",
        "actions": [{"key": "account:manage", "action": "manage", "label": "管理（增删改账号与权限）"}],
    },
    {
        "key": "message",
        "label": "消息中心",
        "group": "消息",
        "actions": [
            {"key": "message:view", "action": "view", "label": "查看（收件箱 / 已发布 / 接收弹窗）"},
            {"key": "message:manage", "action": "manage", "label": "管理（发布 / 删除消息）"},
        ],
    },
    {
        "key": "stock",
        "label": "股票系统",
        "group": "股票",
        "actions": [
            {"key": "stock:view", "action": "view", "label": "查看行情（行情界面 / 选购 / 买卖）"},
            {"key": "stock:edit", "action": "edit", "label": "低级管理（管所选公司 + 自己的资金账户）"},
            {"key": "stock:manage", "action": "manage", "label": "高级管理（看全部 / 增删股票 / 推进轮次）"},
        ],
    },
]

ALL_PERMISSION_KEYS = [a["key"] for d in PERMISSION_CATALOG for a in d["actions"]]

PERMISSION_LABELS = {
    a["key"]: f"{d['label']} · {a['label']}"
    for d in PERMISSION_CATALOG
    for a in d["actions"]
}

# UI 分组
PERMISSION_GROUPS = []
_group_map = {}
for d in PERMISSION_CATALOG:
    _group_map.setdefault(d["group"], []).append(d)
for g, domains in _group_map.items():
    PERMISSION_GROUPS.append({"group": g, "domains": domains})

# 已废止但视为合法的 key（兼容旧数据）
DEPRECATED_PERMISSION_KEYS = [
    "settings:view",
    "settings:manage",
    "dashboard:view",
]


def is_valid_permissions(perms) -> bool:
    if not isinstance(perms, list):
        return False
    return all(
        isinstance(p, str)
        and (p in ALL_PERMISSION_KEYS or p in DEPRECATED_PERMISSION_KEYS)
        for p in perms
    )


def _domain_action_rank(domain: str) -> dict:
    for d in PERMISSION_CATALOG:
        if d["key"] == domain:
            return d.get("actionRank", DEFAULT_ACTION_RANKS)
    return DEFAULT_ACTION_RANKS


def _domain_of(key: str) -> str:
    """从权限 key 提取域前缀。

    合同/比赛等单段域 key 形如 'contract:view' → 域 'contract'；
    数据域 key 形如 'data:material:view' → 域 'data:material'。
    """
    parts = key.split(":")
    return ":".join(parts[:-1])


def _action_of(key: str) -> str:
    return key.split(":")[-1]


def has_permission(
    role: str | None,
    permissions: Iterable[str] | None,
    required: str | list[str],
) -> bool:
    """判断是否满足所需权限。

    - SUPER_ADMIN 隐式拥有全部权限
    - 其余角色：required 中每一项都要被满足（AND 语义）
    - 动作蕴含：用户持有该域任一动作 actionZ 且 rank(Z) ≥ rank(X) 即满足 domain:actionX
    """
    if role == "SUPER_ADMIN":
        return True
    req_list = required if isinstance(required, list) else [required]
    if not req_list:
        return True
    perms = list(permissions or [])
    for req_key in req_list:
        domain = _domain_of(req_key)
        req_action = _action_of(req_key)
        req_rank = _domain_action_rank(domain).get(req_action, 0)
        # 用户持有该域任一动作且等级 ≥ 所需即满足
        satisfied = False
        for p in perms:
            if _domain_of(p) != domain:
                continue
            user_action = _action_of(p)
            user_rank = _domain_action_rank(domain).get(user_action, 0)
            if user_rank >= req_rank:
                satisfied = True
                break
        if not satisfied:
            return False
    return True


# ==================== 角色模板与授予上限 ====================
# 对应原 server/src/permissions/role-templates.ts。
# 后端权威定义角色默认权限集合与「授予上限」，用于账号权限授予校验。

# 基础视图权限（17 个）
BASE_VIEW_PERMISSIONS = [
    "data:material:view",
    "data:part:view",
    "data:product:view",
    "data:map:view",
    "data:infrastructure:view",
    "data:tech:view",
    "data:fuel:view",
    "data:vehicle:view",
    "data:warehouse:view",
    "data:productionLine:view",
    "data:region:view",
    "industryType:view",
    "contractType:view",
    "company:view",
    "contract:view",
    "message:view",
    "stock:view",
]

# 超管专属权限：任何非超管角色禁止持有
SUPER_ADMIN_ONLY_PERMISSIONS = [
    "competition:manage",
    "account:manage",
    "stock:manage",
]

# COMPETITION_ADMIN 可选扩展集（默认不开放，超管可按需放开）
_COMPETITION_ADMIN_EXTRAS = [
    "message:manage",
    "contractType:manage",
    "industryType:manage",
    "company:manage",
    "data:region:edit",
]

ROLE_TEMPLATES = {
    "SUPER_ADMIN": {
        "defaultPermissions": [],  # 隐式全放行
        "grantCeiling": [],  # 任意（不受限）
        "grantExtras": [],
        "isSuperAdmin": True,
    },
    "COMPETITION_ADMIN": {
        "defaultPermissions": BASE_VIEW_PERMISSIONS + [
            "contract:manage",
            "contract:audit",
            "contract:execute",
            "stock:edit",
        ],
        "grantCeiling": BASE_VIEW_PERMISSIONS + [
            "contract:manage",
            "contract:audit",
            "contract:execute",
            "stock:edit",
        ],
        "grantExtras": _COMPETITION_ADMIN_EXTRAS,
        "isSuperAdmin": False,
    },
    "PLAYER": {
        "defaultPermissions": BASE_VIEW_PERMISSIONS,
        "grantCeiling": BASE_VIEW_PERMISSIONS,
        "grantExtras": [],
        "isSuperAdmin": False,
    },
}


def assert_grant_allowed(actor_role, target_role, permissions):
    """校验权限授予是否在上限范围内。对应原 assertGrantAllowed。

    返回 (allowed: bool, violations: list[str])。
    """
    # 非超管不能写权限
    if actor_role != "SUPER_ADMIN":
        return False, ["仅超管可修改权限"]

    # 超管角色只能设为空数组（不落库）
    if target_role == "SUPER_ADMIN":
        if len(permissions) > 0:
            return False, ["超管权限不落库，必须为空数组"]
        return True, []

    template = ROLE_TEMPLATES.get(target_role)
    if not template:
        return False, [f"未知角色: {target_role}"]

    # 检查是否在授予上限范围内（扩展集不在默认上限内）
    ceiling = set(template["grantCeiling"])
    extras = template["grantExtras"]
    violations = []
    for perm in permissions:
        # 超管专属权限检查
        if perm in SUPER_ADMIN_ONLY_PERMISSIONS:
            violations.append(f"{perm} 为超管专属权限，不可授予 {target_role}")
            continue
        if perm not in ceiling:
            if perm in extras:
                violations.append(f"{perm} 在扩展集中，需超管显式放开")
            else:
                violations.append(f"{perm} 超出 {target_role} 的授予上限")
    return len(violations) == 0, violations
