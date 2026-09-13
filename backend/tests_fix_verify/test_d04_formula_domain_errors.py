# -*- coding: utf-8 -*-
"""D-04 验证：公式/算子的数学域错误必须变成业务错误；未定义变量不得静默取 0。

缺陷（改前，实测）：
- 公式内置函数走原生 math：`log(0)`/`sqrt(-1)`/`asin(2)` → ValueError、
  `pow(10,1000)` → OverflowError；`eval_value_spec` 的 FORMULA 分支只捕获
  `_SafeExpressionError`，这些异常直接冒到接口层 → 500（非统一错误信封）。
- 算子路径：`apply_op("LOG",[10,1])` → ZeroDivisionError（math.log(1)=0 作分母）、
  `apply_op("EXP",[1000])` → OverflowError。
- 公式里的未定义标识符 `return 0`：拼错变量名静默按 0 参与金额计算，
  配合 op=SET 会把字段直接写成 0，而合同照常置为「已执行」。

改后（契约）：
- `safe_evaluate`（内部助手）统一抛 `_SafeExpressionError`，不再泄漏 math 原生异常；
- 值源入口 `eval_value_spec` 的 FORMULA 分支把它转成 `BusinessError`（HTTP 400）；
- 算子路径 `apply_op` 直接抛 `BusinessError`（400）。
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.common.exceptions import BusinessError
from apps.contracts import engine as E


class FormulaDomainErrorTests(TestCase):
    def _formula(self, expr: str):
        """走真实值源入口（引擎消费公式的地方）。"""
        return E.eval_value_spec({"type": "FORMULA", "expr": expr}, {}, {}, None)

    # ---------- 缺陷场景：域错误不得以原生异常冒出 ----------
    def test_log_zero_is_business_error(self):
        with self.assertRaises(BusinessError) as ctx:
            self._formula("log(0)")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("公式求值失败", str(ctx.exception))

    def test_sqrt_negative_is_business_error(self):
        with self.assertRaises(BusinessError):
            self._formula("sqrt(0-1)")

    def test_asin_out_of_range_is_business_error(self):
        with self.assertRaises(BusinessError):
            self._formula("asin(2)")

    def test_pow_overflow_is_business_error(self):
        with self.assertRaises(BusinessError):
            self._formula("pow(10,1000)")

    def test_wrong_arity_is_business_error(self):
        """参数个数/类型不符同样是用户公式错误，不得 500。"""
        with self.assertRaises(BusinessError):
            self._formula("round(1, 2)")

    def test_safe_evaluate_no_longer_leaks_native_math_errors(self):
        """内部助手统一抛 _SafeExpressionError（不再泄漏 ValueError/OverflowError）。"""
        for expr in ("log(0)", "sqrt(0-1)", "asin(2)", "pow(10,1000)"):
            with self.subTest(expr=expr):
                with self.assertRaises(E._SafeExpressionError):
                    E.safe_evaluate(expr)

    def test_undefined_variable_is_business_error(self):
        """改前：`unknownvar+1` 静默返回 1；改后：400 且提示未定义。"""
        with self.assertRaises(BusinessError) as ctx:
            self._formula("unknownvar+1")
        self.assertIn("未定义变量", str(ctx.exception))

    def test_undefined_variable_in_calc_style_expression(self):
        with self.assertRaises(BusinessError):
            E.eval_value_spec({"type": "FORMULA", "expr": "typo_cash * 2"}, {"cash": 1}, {}, None)

    # ---------- 缺陷场景：算子路径 ----------
    def test_apply_op_log_base_one_is_business_error(self):
        with self.assertRaises(BusinessError) as ctx:
            E.apply_op("LOG", [10, 1])
        self.assertEqual(ctx.exception.status_code, 400)

    def test_apply_op_log_zero_is_business_error(self):
        with self.assertRaises(BusinessError):
            E.apply_op("LOG", [0, 10])

    def test_apply_op_log_negative_is_business_error(self):
        with self.assertRaises(BusinessError):
            E.apply_op("LOG", [-5, 10])

    def test_apply_op_exp_overflow_is_business_error(self):
        with self.assertRaises(BusinessError):
            E.apply_op("EXP", [1000])

    # ---------- 功能不变 ----------
    def test_normal_formulas_unchanged(self):
        self.assertEqual(E.safe_evaluate("1+1"), 2)
        self.assertEqual(E.safe_evaluate("=1+2"), 3)          # Excel 风格前导等号
        self.assertEqual(E.safe_evaluate(""), 0)
        self.assertEqual(E.safe_evaluate("   "), 0)
        self.assertEqual(E.safe_evaluate("a * b", {"a": 3, "b": 4}), 12)
        self.assertEqual(E.safe_evaluate("min(a,b)", {"a": 3, "b": 5}), 3)
        self.assertEqual(E.safe_evaluate("max(1,2,3)"), 3)
        self.assertEqual(E.safe_evaluate("round(a)", {"a": Decimal("1.4")}), 1)
        self.assertAlmostEqual(float(E.safe_evaluate("log(100)")), 4.605170185988092, places=9)

    def test_normal_ops_unchanged(self):
        self.assertEqual(E.apply_op("DIV", [1, 0]), 0)        # 既有约定：除零返回 0
        self.assertEqual(E.apply_op("DIV", [6, 3]), 2)
        self.assertAlmostEqual(float(E.apply_op("LOG", [100, 10])), 2.0, places=9)
        self.assertAlmostEqual(float(E.apply_op("EXP", [0])), 1.0, places=9)
        self.assertEqual(E.apply_op("ADD", [Decimal("0.1"), Decimal("0.2")]), Decimal("0.3"))

    def test_formula_value_spec_still_works(self):
        out = E.eval_value_spec({"type": "FORMULA", "expr": "cash * rate"}, {"cash": 1000, "rate": Decimal("0.05")}, {}, None)
        self.assertEqual(out, 50)
