"""财年定时器：对应原 NestJS CompanyFieldsService.applyFiscalYearTimer。

财年开始(FY_START)/结束(FY_END)时，把本比赛中所有「启用了该触发时机」的产业字段
自动写为其配置设定值（按字段类型序列化），覆盖该产业类型下的全部公司；随后调用
计算字段级联重算（待 calcGraph 引擎接入）并广播 company-field:changed 让同比赛前端刷新。

实现要点（与 NestJS 一致）：
- 跨产业类型：先捞出 timer_enabled && timer_trigger==trigger 的 IndustryField，按 industry_type_id 分组；
  再取该比赛下对应产业类型的公司批量写入，避免 N+1。
- 写入值经 _serialize 序列化（与手动编辑一致）；DICTIONARY/LIST 的 timer_value 为 JSON 文本。
- 每件公司基于「触发前」字段快照计算定时器目标值，避免字段间相互引用导致的顺序依赖。
- 单字段异常不中断整体（记录日志后跳过）。
"""
from __future__ import annotations

import json
import logging

from django.db import transaction

from apps.companies.models import Company, CompanyFieldValue
from apps.industry_types.models import IndustryField

from .views import _recompute_calc_fields, _write_field_value

logger = logging.getLogger("gipfel")

# 财年定时器设定值引用本产业字段的前缀（如 "field:location"）。
TIMER_REF_PREFIX = "field:"

# number / bool / string 文本值 → 序列化存储字符串（与手动编辑写入口径一致）。
# DICTIONARY/LIST 已是 JSON 文本，原样落库。
def _serialize(field_type: str, raw: object) -> str:
    if raw is None:
        return ""
    if field_type in ("DICTIONARY", "LIST"):
        return json.dumps(raw, ensure_ascii=False)
    if field_type == "BOOLEAN":
        return "true" if raw else "false"
    if field_type == "NUMBER":
        return str(raw)
    return str(raw)


def _timer_raw_value(field: IndustryField) -> object:
    """timer_value 字面量 → 序列化前的原始值（按字段类型还原）。"""
    v = field.timer_value
    ft = field.field_type
    if ft == "NUMBER":
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0
    if ft == "BOOLEAN":
        return str(v).strip().lower() == "true"
    if ft == "STRING":
        return "" if v is None else str(v)
    if ft in ("DICTIONARY", "LIST"):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return [] if ft == "LIST" else {}
    return v


def _stored_to_raw(field: IndustryField, value: str | None) -> object:
    """已存储字段值字符串 → 原始值（反向于 _serialize），用于 field:<key> 引用源读取。"""
    if value is None:
        return 0 if field.field_type == "NUMBER" else "" if field.field_type == "STRING" else False
    ft = field.field_type
    if ft == "NUMBER":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0
    if ft == "BOOLEAN":
        return str(value).strip().lower() == "true"
    if ft == "STRING":
        return value
    if ft in ("DICTIONARY", "LIST"):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return [] if ft == "LIST" else {}
    return value


def _resolve_timer_value(
    field: IndustryField,
    by_key: dict[str, tuple[IndustryField, str]],
) -> object | None:
    """解析定时器写入值：字面量直接还原；引用 field:<key> 取被引用字段当前值。

    引用源缺失时返回 None（调用方 warn 跳过，不中断整体定时器）。
    """
    tv = field.timer_value
    if isinstance(tv, str) and tv.startswith(TIMER_REF_PREFIX):
        ref_key = tv[len(TIMER_REF_PREFIX):]
        ref = by_key.get(ref_key)
        if ref is None:
            return None
        ref_field, ref_value = ref
        return _stored_to_raw(ref_field, ref_value)
    return _timer_raw_value(field)


def apply_fiscal_year_timer(competition_id: int, trigger: str) -> None:
    """财年定时器触发入口（对齐 NestJS applyFiscalYearTimer）。

    :param competition_id: 比赛 id（定时器按比赛收敛，只作用于该比赛下的公司）
    :param trigger: "FY_START" / "FY_END"
    """
    timer_fields = list(
        IndustryField.objects.filter(timer_enabled=True, timer_trigger=trigger)
    )
    if not timer_fields:
        return

    # 按 industry_type_id 分组，便于按产业类型批量取公司
    by_type: dict[int, list[IndustryField]] = {}
    for f in timer_fields:
        by_type.setdefault(f.industry_type_id, []).append(f)

    for industry_type_id, fields in by_type.items():
        companies = list(
            Company.objects.filter(
                competition_id=competition_id, industry_type_id=industry_type_id
            )
        )
        for c in companies:
            try:
                _apply_timer_to_company(c, fields)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "财年定时器：公司 #%s 处理失败：%s", c.id, getattr(e, "message", e)
                )


def _apply_timer_to_company(company: Company, fields: list[IndustryField]) -> None:
    # 取该公司全部字段当前值，构建 fieldKey -> (field, value) 快照（基于触发前状态）
    all_vals = CompanyFieldValue.objects.filter(company=company).select_related(
        "industry_field"
    )
    by_key: dict[str, tuple[IndustryField, str]] = {}
    for v in all_vals:
        f = v.industry_field
        if f is not None:
            by_key[f.field_key] = (f, v.value)

    pending: list[tuple[int, str]] = []
    for f in fields:
        try:
            resolved = _resolve_timer_value(f, by_key)
            if resolved is None:
                logger.warning(
                    "财年定时器：公司 #%s 字段 #%s(%s) 引用了不存在的字段，跳过",
                    company.id,
                    f.id,
                    f.field_key,
                )
                continue
            pending.append((f.id, _serialize(f.field_type, resolved)))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "财年定时器：公司 #%s 字段 #%s(%s) 写入失败：%s",
                company.id,
                f.id,
                f.field_key,
                getattr(e, "message", e),
            )

    if pending:
        with transaction.atomic():
            for industry_field_id, value in pending:
                _write_field_value(company.id, industry_field_id, value, version=None)

    # 基础字段写完后级联重算下游计算字段（calcGraph 引擎接入后真正生效）
    _recompute_calc_fields(company.id)
