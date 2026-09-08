"""大数安全的出站转换工具。

背景：系统需支持千万京（10^23）级金额。JavaScript 的 Number 是 IEEE double，
精确整数上限 2^53 ≈ 9.007×10^15——后端以 JSON number 输出更大的整数时，
前端 JSON.parse 会静默丢失精度（10^23 量级 ULP≈10^7）。

约定：响应渲染前递归扫描结构，把绝对值超过 2^53 的 int 转为字符串；
Decimal 按引擎口径转换（整数值 → int 继续判断，非整数值 → 字符串）。
小整数（id、version 等）不受影响，仍是 JSON number。

挂载点：apps/common/response.py 的统一 JSONRenderer（settings 全局生效）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

JS_MAX_SAFE_INT = 2**53


def _convert_big_numbers(obj: Any) -> Any:
    """递归转换：大 int → str；Decimal → int（整数值）或 str（小数）；容器递归。"""
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        # 大整数（如 10^23 级金额）转为字符串，防前端 double 解析丢精度
        return str(obj) if abs(obj) > JS_MAX_SAFE_INT else obj
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            return None
        if obj == obj.to_integral_value():
            return _convert_big_numbers(int(obj))
        return format(obj, "f")
    if isinstance(obj, float):
        return obj
    if isinstance(obj, list):
        return [_convert_big_numbers(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _convert_big_numbers(v) for k, v in obj.items()}
    return obj
