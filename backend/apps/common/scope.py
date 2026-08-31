"""作用域校验：对应原 server/src/common/scope.ts。

仅在请求方提供 competitionId 且数据本身绑定了 competitionId 时校验，两者必须一致。
"""
from __future__ import annotations

from .exceptions import BusinessError


def assert_same_competition(entity_competition_id, requested_competition_id) -> None:
    if (
        requested_competition_id is not None
        and entity_competition_id is not None
        and entity_competition_id != requested_competition_id
    ):
        raise BusinessError("该数据不属于当前比赛，无法删除（可能属于其它比赛）", code=400, status_code=400)
