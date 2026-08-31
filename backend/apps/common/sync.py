"""增量查询公共工具：对应原 server/src/common/sync.ts。

列表接口支持 updatedAfter=<ISO> 参数时，仅返回 updatedAt 晚于该基线的条目，
同时返回 existingIds 让前端据此 diff 出被删除的本地副本，实现增量同步。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_baseline(updated_after: str | None) -> datetime | None:
    """安全解析 ISO 时间字符串，无效则返回 None。"""
    if not updated_after:
        return None
    s = updated_after.strip()
    # 兼容带 Z 后缀的 ISO
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def apply_updated_after(base_where: dict, updated_after: str | None) -> tuple[dict, bool, datetime | None]:
    """解析 updatedAfter 并构造查询条件。

    返回 (where, incremental, baseline)：
    - 增量模式：where 合并了 updated_at__gt 过滤
    - 非增量：where == base_where
    """
    baseline = parse_baseline(updated_after)
    if not baseline:
        return base_where, False, None
    where = {**base_where, "updated_at__gt": baseline}
    return where, True, baseline


def server_now_iso() -> str:
    """当前服务器时间（ISO 字符串），作为下一次同步的基线。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_incremental_result(
    updated: list,
    all_current_ids: list,
    previous_ids: list | None = None,
    total: int | None = None,
) -> dict:
    """生成增量响应包装（列表形态）。

    - previousIds 非空：计算 deletedIds（previousIds 中不在 allCurrentIds 的）
    - 否则：返回 existingIds（向后兼容旧客户端）
    """
    server_now = server_now_iso()
    if previous_ids and len(previous_ids) > 0:
        current_set = set(all_current_ids)
        deleted_ids = [i for i in previous_ids if i not in current_set]
        return {
            "items": updated,
            "total": total if total is not None else len(updated),
            "deletedIds": deleted_ids,
            "serverTime": server_now,
            "incremental": True,
        }
    return {
        "items": updated,
        "total": total if total is not None else len(updated),
        "existingIds": all_current_ids,
        "serverTime": server_now,
        "incremental": True,
    }
