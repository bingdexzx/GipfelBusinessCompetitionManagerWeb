# -*- coding: utf-8 -*-
"""DRF 序列化器字段层校验（与 `apps/common/fields.py` 的模型层守卫配套）。"""
from __future__ import annotations

import math

from rest_framework import serializers


class FiniteFloatField(serializers.FloatField):
    """拒绝 inf / nan / 溢出值（如 `"1e400"`）的 FloatField。

    背景（审计 D-08）：DRF 的 FloatField 用 `float(value)` 解析，`"inf"`/`"nan"`/
    `"1e400"` 全部能通过校验；落库后出站渲染（DRF JSONRenderer 以
    allow_nan=False 序列化）会抛 `ValueError: Out of range float values are not
    JSON compliant`，一条脏数据即可让该模块的读接口持续 500。
    这里在写入侧直接拒绝，配合 `renderers.py` 的兜底（历史脏数据 → null）双保险。
    """

    default_error_messages = {
        **serializers.FloatField.default_error_messages,
        "not_finite": "必须是有限数字（不接受 inf / nan / 溢出值）",
    }

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value is not None and not math.isfinite(value):
            self.fail("not_finite")
        return value
