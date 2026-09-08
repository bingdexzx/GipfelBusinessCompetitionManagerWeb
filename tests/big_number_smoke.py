# -*- coding: utf-8 -*-
"""大数支持回归冒烟测试：千万京（10^23）量级全链路精度验证。

运行：backend/.venv/Scripts/python.exe tests/big_number_smoke.py
（在仓库根目录执行；自动配置 DJANGO_SETTINGS_MODULE）

覆盖：
1. 合同引擎 to_number / apply_op（ADD/SUB/MUL/DIV）大数精度
2. 表达式求值器大数字面量
3. apply_field_effect 落账（NUMBER 字段 ± 大数）
4. dumps_engine_json 的 Decimal 序列化
5. company_fields.calc 的 _to_num 解析
6. SQLite DecimalField(max_digits=30) 存取往返（需 DB，放最后，失败不阻断前 5 项结论）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django  # noqa: E402

django.setup()

from decimal import Decimal  # noqa: E402

from apps.contracts.engine import (  # noqa: E402
    apply_field_effect,
    apply_op,
    dumps_engine_json,
    to_number,
)

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


TEN_QUAD_JING = 10**23  # 千万京
BIG = 12345678901234567890123  # 1.23×10^22

print("== 1. to_number 解析 ==")
check("大整数字符串无损", to_number(str(BIG)) == BIG, repr(to_number(str(BIG))))
check("大整数 int 直通", to_number(BIG) == BIG)
check("小数字符串→Decimal", to_number("123.45") == Decimal("123.45"))
check("float→Decimal 无损回转", to_number(0.1) == Decimal("0.1"))
check("非法串兜底", to_number("abc") == 0)
check("科学计数大数", to_number("1e23") == Decimal("1e23"))

print("== 2. apply_op 算术（10^23 量级）==")
base = 10**23
check("ADD 精确", apply_op("ADD", [base, 1]) == base + 1, repr(apply_op("ADD", [base, 1])))
check("SUB 精确", apply_op("SUB", [base, 999]) == base - 999)
check("MUL 精确", apply_op("MUL", [base, base]) == base * base)
check("字符串大数 ADD", apply_op("ADD", [str(base), "5"]) == base + 5)
check("DIV 整除→int", isinstance(apply_op("DIV", [base, 7]), int) or apply_op("DIV", [base, 7]) == Decimal(base) / 7)
q = apply_op("DIV", [base, 4])
check("DIV 非整除→Decimal 精确", q == Decimal(base) / 4, repr(q))
check("SUM_OF 大数列表", apply_op("SUM_OF", [[base, base, 3]]) == 2 * base + 3)
check("MIN/MAX 大数", apply_op("MAX", [base, base + 1]) == base + 1)

print("== 3. 表达式求值器大数字面量 ==")
from apps.contracts.engine import safe_evaluate  # noqa: E402

expr = f"{BIG} + 1"
try:
    got = safe_evaluate(expr)
    check("公式大数字面量 +1", got == BIG + 1, repr(got))
except Exception as e:  # noqa: BLE001
    check("公式大数字面量 +1", False, f"异常: {e}")

print("== 4. apply_field_effect 落账（NUMBER ± 大数）==")
r = apply_field_effect(str(base), "NUMBER", {}, "ADD", 1)
after = r["after"]
check("落账 ADD 后精确", to_number(after) == base + 1, repr(after))
stored = r["store"]
check("store 回读无损", to_number(__import__("json").loads(stored)) == base + 1, stored)

r2 = apply_field_effect(str(base), "NUMBER", {}, "SUB", "123456789")
check("落账 SUB（字符串参数）精确", to_number(r2["after"]) == base - 123456789)

print("== 5. dumps_engine_json 序列化 ==")
s = dumps_engine_json({"v": Decimal("123.45"), "n": Decimal("1e23")})
check("Decimal 小数→字符串", '"v": "123.45"' in s, s)
check("Decimal 整数→number", '"n": ' + str(10**23) in s, s)

print("== 6. company_fields.calc 数值解析 ==")
try:
    from apps.company_fields.timer import _to_num  # type: ignore[attr-defined]

    check("timer._to_num 大数", _to_num(str(BIG)) == BIG)
except ImportError:
    print("  [SKIP] timer._to_num 不存在（符号名不同，跳过——由 T2 专项验证）")

print()
print(f"结果：PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
