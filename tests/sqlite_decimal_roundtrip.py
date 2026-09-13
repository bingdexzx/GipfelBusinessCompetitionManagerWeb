# -*- coding: utf-8 -*-
"""SQLite 上 DecimalField 精度契约验证。

运行：backend/.venv/Scripts/python.exe tests/sqlite_decimal_roundtrip.py
（在仓库根目录执行）

审计 X-17 修复点
----------------
① 改前本文件在**模块顶层**执行 `django.setup()` 并直连真实的 `backend/db.sqlite3`
   （`backend/backend/settings.py:305-308`，无环境变量可覆盖），靠"`raise SystemExit`
   落在 `transaction.atomic()` 块内"来回滚 —— 只在正常走到那一行时成立。被 pytest
   收集时，collection 阶段就会导入模块并对真实开发库发起写事务。
   现在改为 `tests/_bootstrap.bootstrap(need_db=True)`：由 `__main__` 显式调用，
   在**一次性测试库**（`create_test_db`，SQLite 下即内存库）上跑迁移后再验证，
   `backend/db.sqlite3` 完全不被打开。

② 本文件原有的断言（"写入 12345678901234567890123.4567 应精确读回"）已随 D-01 的修复
   **过时**：`apps/common/fields.py` 的 `ExactDecimalField` 现在会在 SQLite 上直接拒绝
   超过 15 位有效数字的值。改前实跑该行会抛未捕获的 `BusinessError`、脚本以 exit 1
   加一大段 traceback 结束，根本走不到 rollback。现在按**当前契约**分两部分断言：
     A. 超精度值必须显式报错（不得静默截断）；
     B. 15 位有效数字以内的值必须精确往返。

退出码：0 = 全部通过；1 = 存在 FAIL；2 = 环境错误（拿不到测试库）。
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _bootstrap  # noqa: E402

# 15 位有效数字以内：必须精确往返
EXACT_CASES = [
    Decimal("0"),
    Decimal("12345.6789"),
    Decimal("999999999999999"),          # 15 位
    Decimal("123456789012.345"),         # 15 位（12 整数 + 3 小数）
    Decimal("-999999999999999"),
]

# 超过 15 位有效数字：SQLite 上必须被显式拒绝
TOO_PRECISE = [
    Decimal("12345678901234567890123.4567"),  # 原文件里的值，27 位
    Decimal("1234567890123456"),              # 16 位
    Decimal("999999999999999.9"),             # 16 位
]

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def main() -> int:
    if _bootstrap.bootstrap(need_db=True) is None:
        print("[环境错误] 未能创建测试库", file=sys.stderr)
        return 2

    from django.db import connection  # noqa: E402

    from apps.common.exceptions import BusinessError  # noqa: E402
    from apps.competitions.models import Competition  # noqa: E402
    from apps.fuels.models import Fuel  # noqa: E402

    active = str(connection.settings_dict["NAME"])
    print(f"活动数据库（一次性测试库）：{active}")
    check("活动数据库不是真实开发库 backend/db.sqlite3",
          not active.endswith("db.sqlite3"),
          active)

    print("== A. 超精度值必须显式报错（不得静默截断） ==")
    comp = Competition.objects.create(name="__x17_precision_probe__")
    for value in TOO_PRECISE:
        try:
            Fuel.objects.create(competition=comp, name="__x17__", price_per_liter=value)
        except BusinessError as e:
            check(f"{value} 被拒绝（BusinessError）", True, "")
            print(f"         └ {e}")
        except Exception as e:  # noqa: BLE001
            check(f"{value} 被拒绝（BusinessError）", False, f"抛的是 {type(e).__name__}: {e}")
        else:
            stored = Fuel.objects.filter(competition=comp, name="__x17__") \
                .values_list("price_per_liter", flat=True).last()
            check(f"{value} 被拒绝（BusinessError）", False, f"竟被接受，存储为 {stored!r}")
            Fuel.objects.filter(competition=comp, name="__x17__").delete()

    print("== B. 15 位有效数字以内必须精确往返 ==")
    for value in EXACT_CASES:
        fuel = Fuel.objects.create(
            competition=comp, name=f"__x17_{value}__", price_per_liter=value
        )
        fuel.refresh_from_db()
        check(f"{value} 往返精确", fuel.price_per_liter == value,
              f"读回 {fuel.price_per_liter}")

    print("== C. 库本身仍是 SQLite（本测试的前提） ==")
    check("连接 vendor == sqlite", connection.vendor == "sqlite", connection.vendor)

    print()
    print(f"结果：PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
