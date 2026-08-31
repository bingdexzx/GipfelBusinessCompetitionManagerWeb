"""JSON 解析工具：对应原 server/src/common/json.util.ts。"""
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
    if raw and isinstance(raw, dict) and not isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            o = json.loads(raw)
            return o if (o and isinstance(o, dict)) else {}
        except (ValueError, TypeError):
            return {}
    return {}
