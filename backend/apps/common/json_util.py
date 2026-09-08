"""JSON 解析 / 安全序列化工具。"""
from __future__ import annotations

import json
from typing import Any


def parse_json_array(raw: Any) -> list:
    """把可能已是数组、JSON 字符串、或 null 的输入安全解析为数组。"""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except (ValueError, TypeError):
            return []
    return []


def parse_field_config(raw: Any) -> dict:
    """解析产业字段的 config 配置，统一返回 dict。失败返回 {}。"""
    if raw and isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            o = json.loads(raw)
            return o if (o and isinstance(o, dict)) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def dumps_json_safe(obj: Any, **kwargs: Any) -> str:
    """大数安全的 json.dumps：Decimal / 超过 2^53 的 int 先按出站口径递归转换
    （整数值 Decimal → int、小数 Decimal → 字符串、大 int → 字符串），再序列化。

    用于把含 Decimal 的引擎产物（合同执行日志 / 结果等）落库为 JSON 字符串——
    直接 json.dumps 会抛 "Object of type Decimal is not JSON serializable"。
    转换口径与 apps/common/renderers.py 的响应渲染保持一致。
    """
    from .renderers import _convert_big_numbers

    return json.dumps(_convert_big_numbers(obj), **kwargs)
