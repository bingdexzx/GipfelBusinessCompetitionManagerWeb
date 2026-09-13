# -*- coding: utf-8 -*-
"""合同数据翻译模块：把机器形态的合同 payload 转成"可被理解"的中文结构化记录。

用法（在 handlers.py 处理函数中）：
    from readable import translate_contract

    def handle_xxx_passed(contract: dict, ctx: dict) -> None:
        rec = translate_contract(contract)          # 可读记录 dict
        ... 自行决定如何落盘 rec ...

默认存档时，监听程序会自动**同时**产出翻译版 JSON：
    records/<类型key>/contract_<id>_<时间戳>.json          （原始全量）
    records/<类型key>/contract_<id>_<时间戳>_readable.json （本模块翻译）

对外接口（供用户使用/扩展）：
    translate_contract(contract)        # 翻译一份合同 → dict（自动按类型找自定义翻译器）
    register_translator(type_key, fn)   # 装饰器/函数：为某合同类型注册自定义翻译器
    build_readable(contract)            # 默认翻译实现（也可直接调用）
    pretty_value(v)                     # 数值/列表/字典 → 适合展示的文本
    OP_LABELS / STATUS_LABELS           # 可修改的全局标签表（直接赋值覆盖即可）

自定义翻译器签名：fn(contract: dict) -> dict，返回值将整体作为该类型的可读记录；
若只想在默认结果上增删字段，可先 build_readable(contract) 再改。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

# ==================== 可自定义的全局标签表 ====================

OP_LABELS: dict[str, str] = {
    "ADD": "增加",
    "SUB": "扣减",
    "SET": "设定",
}

STATUS_LABELS: dict[str, str] = {
    "DRAFT": "草稿",
    "PENDING_EXEC": "待执行",
    "EXECUTED": "已执行",
    "TERMINATED": "已终止",
}

_TRUE_CN = "是"
_FALSE_CN = "否"
_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def pretty_value(v: Any) -> str:
    """把输入值转成适合展示的文本（大数安全：数字字符串加千分位，不做 Number 化）。

    审计 CW-15：改前 `_group_int` 会吞掉正号、对带前导零的串分组出错，且 int 加千分位、
    float 不加 —— 同一列的展示口径不一致，人工对账依据被静默改写。现在：
      - int / float 与数字字符串统一走 `_group_number`（float 先原样 str，避免 1e+21 这类
        科学计数法被错拆）；
      - 正号保留（`+1234` → `+1,234`）、前导零不再分组（`-0012345` → `-12,345`）；
      - 非有限值（nan/inf）原样输出，不做千分位。
    """
    if v is None:
        return "—"
    if isinstance(v, bool):
        return _TRUE_CN if v else _FALSE_CN
    if isinstance(v, (int, float)):
        return _group_number(str(v))
    if isinstance(v, str):
        s = v.strip()
        if _NUM_RE.match(s):
            return _group_number(s)
        return s
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _expand_scientific(text: str) -> str:
    """把 `1e+21` / `1.5E-7` 展开成普通十进制写法（失败则原样返回）。"""
    from decimal import Decimal, InvalidOperation

    try:
        return format(Decimal(text), "f")
    except (InvalidOperation, ValueError):
        return text


def _group_number(s: str) -> str:
    """给十进制数值串加千分位。

    仅当「整数部分没有前导零」时分组：`-0012345` 这种带前导零的串按原样返回
    （审计 CW-15：改前会分组出 `-0,012,345`，看起来像一个完全不同的数）。
    """
    body = _expand_scientific(s) if ("e" in s or "E" in s) else s
    neg = body.startswith("-")
    plus = body.startswith("+")
    digits = body[1:] if (neg or plus) else body
    int_part, dot, frac = digits.partition(".")
    if not int_part.isdigit() or (len(int_part) > 1 and int_part.startswith("0")):
        return s
    grouped = re.sub(r"\B(?=(\d{3})+(?!\d))", ",", int_part)
    sign = "-" if neg else ("+" if plus else "")
    return sign + grouped + (dot + frac if dot else "")


# ==================== 自定义翻译器注册表（用户接口） ====================

_CUSTOM_TRANSLATORS: dict[str, Callable[[dict], dict]] = {}


def register_translator(type_key: str):
    """注册某合同类型的专属翻译器（装饰器用法）。

    例：
        @register_translator("material-procurement")
        def translate_material(payload: dict) -> dict:
            rec = build_readable(payload)      # 先取默认结构
            rec["采购明细"] = ...               # 再按类型补充/覆盖
            return rec
    """
    def deco(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _CUSTOM_TRANSLATORS[type_key] = fn
        return fn
    return deco


def translate_contract(contract: dict) -> dict:
    """翻译一份合同 payload → 可读记录 dict。

    优先使用该合同类型注册的自定义翻译器；未注册时使用默认翻译 build_readable。
    """
    key = (contract.get("contractType") or {}).get("key") or "unknown"
    fn = _CUSTOM_TRANSLATORS.get(key)
    if fn is not None:
        return fn(contract)
    return build_readable(contract)


# ==================== 默认翻译实现 ====================

def _fmt_dt(v: Any) -> str:
    """时间展示：解析为 datetime 后换算到**本地时区**并带偏移标注（审计 CW-15）。

    改前是 `str(v)[:19].replace("T", " ")`：后端给的是 UTC（实测
    `2026-09-10T15:20:46.731818Z`），于是可读记录里的「执行时间」显示 `2026-09-10 15:20:46`，
    **比北京时间早 8 小时且没有任何时区标注**，跨天/跨财年归属会判错；也与 `default_archive`
    用的本地时间戳文件名对不上。无法解析的值保留原文并标注「无法解析」，不再截断成 19 字符。
    """
    if v is None or (isinstance(v, str) and not v.strip()):
        return "—"
    text = str(v).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return f"{text}（无法解析）"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    offset = local.strftime("%z")  # 形如 +0800
    if offset:
        offset = f"{offset[:3]}:{offset[3:]}"
    return local.strftime("%Y-%m-%d %H:%M:%S") + (f" {offset}" if offset else "")


def build_readable(contract: dict) -> dict:
    """默认翻译：使用合同 payload 内的全部材料（无需额外接口）。"""
    ct = contract.get("contractType") or {}
    type_name = ct.get("name") or contract.get("name")
    status = STATUS_LABELS.get(contract.get("status"), contract.get("status"))

    # 输入项 key → 中文名（inputSchema 自带 label）
    schema_labels = {
        (s.get("key") or ""): (s.get("label") or s.get("key"))
        for s in ct.get("inputSchema") or []
        if isinstance(s, dict)
    }
    # 角色名映射（partyRoles 自带 label）
    role_labels = {
        (r.get("role") or ""): (r.get("label") or r.get("role"))
        for r in ct.get("partyRoles") or []
        if isinstance(r, dict)
    }
    # 公司 ID → 名称（parties 自带 companyName）
    parties = contract.get("parties") or []
    company_names = {
        p.get("companyId"): p.get("companyName")
        for p in parties
        if isinstance(p, dict) and p.get("companyId") is not None
    }

    def company_of(cid: Any) -> str:
        return company_names.get(cid) or f"公司#{cid}"

    # 1) 参与方
    party_rows = []
    for p in parties:
        if not isinstance(p, dict):
            continue
        party_rows.append({
            "角色": role_labels.get(p.get("role")) or p.get("role") or "—",
            "公司": p.get("companyName") if not p.get("isHost") else "（主办方）",
            "公司ID": p.get("companyId"),
            "是否主办方": _TRUE_CN if p.get("isHost") else _FALSE_CN,
            "合同编号": p.get("contractNumber") or "—",
        })

    # 2) 填写内容
    input_rows = [
        {"输入项": schema_labels.get(k, k), "键": k, "值": pretty_value(v)}
        for k, v in (contract.get("inputs") or {}).items()
    ]

    # 3) 前置检查（EXECUTED 合同的 checks 应全部 passed）
    checks = (contract.get("executionResult") or {}).get("checks") or []
    check_rows = [
        {
            "检查项": c.get("label") or c.get("kind") or "—",
            "通过": _TRUE_CN if c.get("passed") else _FALSE_CN,
            "结果说明": c.get("detail") or "—",
        }
        for c in checks
        if isinstance(c, dict)
    ]

    # 4) 落账明细（executionLog 的 FIELD 条目；含引擎写入的字段中文名）
    log_rows = []
    for e in contract.get("executionLog") or []:
        if not isinstance(e, dict) or e.get("kind") != "FIELD":
            continue
        op = e.get("op") or ""
        before, after = e.get("before"), e.get("after")
        log_rows.append({
            "公司": company_of(e.get("companyId")),
            "公司ID": e.get("companyId"),
            "字段名": e.get("fieldName") or e.get("fieldKey") or "—",
            "字段标识": e.get("fieldKey"),
            "操作": OP_LABELS.get(op, op),
            "数值": pretty_value(e.get("value")),
            "变动前": pretty_value(before),
            "变动后": pretty_value(after),
            "说明": f"由 {pretty_value(before)} 变为 {pretty_value(after)}",
        })

    return {
        "记录类型": "合同通过记录（可读版）",
        "翻译模块版本": 1,
        "合同ID": contract.get("id"),
        "比赛ID": contract.get("competitionId"),
        "合同名称": contract.get("name") or type_name,
        "合同类型": f"{ct.get('key')}（{type_name}）" if type_name else ct.get("key"),
        "状态": status,
        "创建时间": _fmt_dt(contract.get("createdAt")),
        "签署时间": _fmt_dt(contract.get("signedAt")),
        "执行时间": _fmt_dt(contract.get("executedAt")),
        "参与方": party_rows,
        "填写内容": input_rows,
        "前置检查": check_rows,
        "落账明细": log_rows,
    }
