"""分页工具：对应原 server/src/common/pagination.ts 的 parsePagination()。

约束：pageSize 上限 200（硬约束，防止 DoS 全表扫描）。
"""
from __future__ import annotations

from typing import Any

MAX_PAGE_SIZE = 200
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50


def parse_pagination(query_params: Any) -> tuple[int, int, int]:
    """从 DRF request.query_params 或 dict 解析分页参数。

    返回 (page, pageSize, skip)。
    - 非法值回退默认
    - pageSize 上限 MAX_PAGE_SIZE（硬约束）
    """
    try:
        page = int(query_params.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        page_size = int(query_params.get("pageSize", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE

    if page < 1:
        page = DEFAULT_PAGE
    if page_size < 1:
        page_size = DEFAULT_PAGE_SIZE
    if page_size > MAX_PAGE_SIZE:
        page_size = MAX_PAGE_SIZE

    skip = (page - 1) * page_size
    return page, page_size, skip


def paginated_response(items: list, total: int, page: int, page_size: int) -> dict:
    """构造分页响应：{ items, total, page, pageSize }。"""
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
    }
