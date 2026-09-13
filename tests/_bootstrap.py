# -*- coding: utf-8 -*-
"""tests/ 下独立脚本的公共引导（审计 X-17）。

改前问题
--------
`tests/big_number_smoke.py` 与 `tests/sqlite_decimal_roundtrip.py` 都在**模块顶层**执行
`sys.path` 注入、`os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")`、
`django.setup()`，以及 `objects.create()` / `raise SystemExit()`：

* `backend.settings` 的 `DATABASES["default"]["NAME"]` 就是**真实开发库**
  `backend/db.sqlite3`（`backend/backend/settings.py:305-308`，无环境变量可覆盖）；
* `sqlite_decimal_roundtrip.py` 靠"`raise SystemExit` 落在 `transaction.atomic()` 块内"
  来回滚，只在正常走到那一行时成立；
* 被 pytest 收集时，**collection 阶段**就会导入模块并触发上面的写库，开发者毫无察觉。

现在统一走 `bootstrap()`：

* 只能由 `if __name__ == "__main__":` 显式调用 —— 单纯 import（pytest 收集）零副作用；
* `need_db=True` 时用 Django 自带的测试库机制（`create_test_db`；SQLite 下是内存库）
  跑一次迁移，**绝不触碰** `backend/db.sqlite3`，并在开跑前断言这一点；
* 脚本结束时由 `atexit` 销毁测试库。
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
REAL_DB = BACKEND / "db.sqlite3"

_created_test_db: str | None = None


def assert_not_real_db() -> None:
    """当前生效的数据库必须不是真实开发库。"""
    from django.db import connection

    name = str(connection.settings_dict.get("NAME", ""))
    if name and Path(name) == REAL_DB:
        raise RuntimeError(
            f"拒绝在真实开发库上运行：{name}（审计 X-17 要求这类脚本只能跑测试库）"
        )


def _destroy_test_db() -> None:
    global _created_test_db
    if _created_test_db is None:
        return
    from django.db import connection

    name, _created_test_db = _created_test_db, None
    try:
        connection.creation.destroy_test_db(name, verbosity=0)
    except Exception:  # noqa: BLE001 - 退出阶段尽力清理，不再抛
        pass


def bootstrap(*, need_db: bool = False, verbosity: int = 0) -> str | None:
    """初始化 Django；need_db=True 时换成一次性测试库并返回库名。

    必须在 `if __name__ == "__main__":` 里调用。
    """
    global _created_test_db

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

    import django

    django.setup()

    if not need_db:
        return None

    from django.db import connection
    from django.test.utils import setup_test_environment

    setup_test_environment()
    test_db = connection.creation.create_test_db(verbosity=verbosity, autoclobber=True)
    _created_test_db = test_db
    atexit.register(_destroy_test_db)
    assert_not_real_db()
    return test_db
