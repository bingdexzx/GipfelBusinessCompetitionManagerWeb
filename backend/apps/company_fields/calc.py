"""产业字段计算图（calcGraph）求值引擎。

对应前端 IndustryFieldGraphEditor.vue 保存的 GGraph JSON：
- 节点类型：output（结果汇点，恰一个）/ value（数值源）/ if（条件分支）/ assign（赋值）
- value 节点 data.kind：FIELD（本产业类型其它字段现值）/ CONST / FORMULA（mathjs 表达式，
  经合同引擎 safe_evaluate 沙箱求值）/ OP（列表/字典/算术/比较，经合同引擎 apply_op）/
  VAR（运行期变量，assign 产出）/ CONSUMER_DEMAND（消费者需求总数·按所在地）
- 连线：{source, target, sourceHandle, targetHandle}，入参按 handle 名取上游节点值

求值语义与合同引擎 eval_value_spec 对齐（CONST/OP/FORMULA/VAR 同构），直接复用
合同引擎的算子与沙箱。字段间依赖（计算字段引用计算字段）按拓扑序求值；
单字段失败记日志跳过，不中断其余字段。
"""
from __future__ import annotations

import json
import logging
import re

from django.db import transaction

from apps.common.exceptions import BusinessError

logger = logging.getLogger("gipfel")

# OP 参数端口顺序：镜像 frontend/src/contracts/graph-model.ts 的 OP_ARG_SPECS（45 项），
# 由脚本从 TS 源生成，保证前后端端口顺序一致。OP 节点的入参连线按此表顺序取值。
OP_ARG_SPECS: dict[str, list[str]] = {
    "LIST_APPEND": ["list", "item1", "item2"],
    "LIST_CONCAT": ["a", "b"],
    "LIST_LEN": ["list"],
    "LIST_CONTAINS": ["list", "item"],
    "LIST_INDEX_OF": ["list", "item"],
    "LIST_UNIQUE": ["list"],
    "LIST_FLATTEN": ["list"],
    "LIST_SUM_OF": ["list"],
    "LIST_JOIN": ["list", "sep"],
    "LIST_SLICE": ["list", "start", "end"],
    "LIST_REVERSE": ["list"],
    "LIST_SORT": ["list"],
    "LIST_RANGE": ["start", "stop", "step"],
    "LIST_ADD": ["a", "b"],
    "LIST_SUB": ["a", "b"],
    "DICT_GET": ["dict", "key", "default"],
    "DICT_KEYS": ["dict"],
    "DICT_VALUES": ["dict"],
    "DICT_ENTRIES": ["dict"],
    "DICT_HAS_KEY": ["dict", "key"],
    "DICT_MERGE": ["a", "b"],
    "DICT_FROM_PAIRS": ["pairs"],
    "DICT_FROM_KEYS": ["keys", "value"],
    "DICT_INVERT": ["dict"],
    "DICT_ADD": ["a", "b"],
    "DICT_SUB": ["a", "b"],
    "DICT_APPEND": ["dict", "key", "value"],
    "DICT_SUM": ["dict"],
    "LEN": ["x"],
    "CONTAINS": ["coll", "item"],
    "SUM_OF": ["list"],
    "ADD": ["left", "right"],
    "SUB": ["left", "right"],
    "MUL": ["left", "right"],
    "DIV": ["left", "right"],
    "EXP": ["operand"],
    "LOG": ["operand", "base"],
    "MIN": ["left", "right"],
    "MAX": ["left", "right"],
    "CMP_EQ": ["left", "right"],
    "CMP_NE": ["left", "right"],
    "CMP_GT": ["left", "right"],
    "CMP_LT": ["left", "right"],
    "CMP_GTE": ["left", "right"],
    "CMP_LTE": ["left", "right"],
}

# 本产业类型自动自带的「所在地」字段键（消费需求按其取公司所在区域）
LOCATION_FIELD_KEY = "location"


def _parse_graph(raw: str | None) -> dict | None:
    if not raw or not str(raw).strip():
        return None
    try:
        g = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(g, dict) or not isinstance(g.get("nodes"), list):
        return None
    return g


# 表达式保留字：mathjs 关键字 / 常量，提取公式依赖时必须排除（这些不是字段引用）。
# 注意不放入 e / pi / phi —— 若用户真定义了同名字段，应作为合法引用保留。
_FORMULA_RESERVED = {
    "true", "false", "null", "undefined", "NaN", "Infinity",
    "and", "or", "not", "xor",
    "if", "then", "else", "elseif", "end",
    "for", "while", "do", "in", "of", "let", "const", "var",
    "function", "return", "break", "continue", "new", "this",
}

# 标识符（字段键 / 运行期变量等）：字母或下划线开头，后续字母/数字/下划线
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _formula_field_refs(expr: str | None, known_keys: set[str] | None = None) -> set[str]:
    """从 FORMULA 表达式（mathjs）提取以变量形式引用的字段键。

    机制：剔除外层字符串字面量（避免引号内文本被误认），再扫描标识符；
    - 保留字（_FORMULA_RESERVED）一律排除；
    - 以「函数调用」形态出现的表达式助手（如 IF(...)、len(...)）排除，但其作为
      变量出现的同名标识符（如 a.keys）仍视为候选引用；
    - known_keys 非空时仅保留确属本产业类型已有字段的引用，过滤 assign 局部变量等干扰。
    """
    if not expr:
        return set()
    # 去掉字符串字面量（双/单/反引号），防止把引号内文本当字段键
    stripped = re.sub(r'"[^"]*"', " ", str(expr))
    stripped = re.sub(r"'[^']*'", " ", stripped)
    stripped = re.sub(r"`[^`]*`", " ", stripped)
    from apps.contracts.engine import EXPR_HELPERS  # 延迟导入避免加载期循环依赖

    helper_names = set(EXPR_HELPERS.keys())
    refs: set[str] = set()
    for m in _IDENT_RE.finditer(stripped):
        name = m.group(0)
        if name in _FORMULA_RESERVED:
            continue
        # 仅当「函数调用形态」时才把助手名排除
        after = stripped[m.end():].lstrip()
        if name in helper_names and after.startswith("("):
            continue
        if known_keys is not None and name not in known_keys:
            continue
        refs.add(name)
    return refs


def _graph_field_refs(raw: str | None, known_keys: set[str] | None = None) -> set[str]:
    """提取计算图引用的全部 FIELD 字段键（用于依赖排序 / 循环依赖检测）。

    覆盖两类引用：
    - value(FIELD) 节点：data.fieldKey 直接给出被引用字段键；
    - value(FORMULA) 节点：data.expr 中以变量形式出现的字段键（见 _formula_field_refs）。

    known_keys 非空时仅返回确属本产业类型已有字段的引用（过滤 assign 局部变量等干扰项，
    避免环检测出现假边）；为 None 时返回候选全集，由调用方自行取交集（如 _order_calc_fields）。
    """
    g = _parse_graph(raw)
    if not g:
        return set()
    keys: set[str] = set()
    for n in g.get("nodes") or []:
        if not isinstance(n, dict) or n.get("type") != "value":
            continue
        d = n.get("data") or {}
        kind = d.get("kind")
        if kind == "FIELD" and d.get("fieldKey"):
            keys.add(str(d["fieldKey"]))
        elif kind == "FORMULA" and d.get("expr"):
            keys |= _formula_field_refs(d.get("expr"), known_keys)
    return keys


def _order_calc_fields(calc_fields: list) -> list:
    """按「计算字段之间」的 FIELD 依赖拓扑排序（环则退化为原顺序并告警）。"""
    calc_keys = {f.field_key: f for f in calc_fields}
    deps: dict[str, set[str]] = {
        f.field_key: (_graph_field_refs(f.calc_graph) & set(calc_keys)) - {f.field_key}
        for f in calc_fields
    }
    ordered: list = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(key: str, field) -> None:
        if key in done:
            return
        if key in visiting:  # 环：放弃重排，按原顺序兜底
            logger.warning("[calc] 计算字段依赖成环：%s（按定义顺序兜底）", key)
            return
        visiting.add(key)
        for dep in sorted(deps.get(key, ())):
            if dep in calc_keys:
                visit(dep, calc_keys[dep])
        visiting.discard(key)
        if key not in done:
            ordered.append(field)
            done.add(key)

    for f in calc_fields:
        visit(f.field_key, f)
    return ordered


def _consumer_demand_total(company: dict, stored_location: str | None) -> float:
    """消费者需求总数（按所在地）：公司所在区域的需求量合计。"""
    from django.db.models import Sum

    from apps.consumer_demands.models import ConsumerDemand

    region = str(stored_location or "").strip()
    if not region:
        return 0
    agg = ConsumerDemand.objects.filter(
        competition_id=company["competition_id"], region=region
    ).aggregate(s=Sum("quantity"))
    return float(agg["s"] or 0)


def _eval_graph(
    field,
    values: dict[str, str],
    field_by_key: dict[str, object],
    company: dict,
) -> object:
    """求值单个计算字段图，返回原始值（未序列化）。缺 output 节点返回 None。"""
    from apps.contracts.engine import EXPR_HELPERS, apply_op, is_truthy, safe_evaluate
    from .timer import _stored_to_raw

    g = _parse_graph(field.calc_graph)
    if not g:
        return None
    nodes: dict[str, dict] = {
        n.get("id"): n
        for n in g.get("nodes") or []
        if isinstance(n, dict) and n.get("id")
    }
    if not nodes:
        return None
    incoming: dict[str, dict[str, str]] = {}
    for e in g.get("edges") or []:
        if not isinstance(e, dict):
            continue
        incoming.setdefault(e.get("target"), {})[e.get("targetHandle")] = e.get("source")

    memo: dict[str, object] = {}
    stack: set[str] = set()
    scope: dict[str, object] = {}

    def eval_node(nid: str | None) -> object:
        if not nid or nid not in nodes:
            return None
        if nid in memo:
            return memo[nid]
        if nid in stack:  # 环
            logger.warning("[calc] 计算图存在环：%s（字段 #%s）", nid, field.id)
            return None
        stack.add(nid)
        try:
            node = nodes[nid]
            t = node.get("type")
            d = node.get("data") or {}
            v: object = None
            if t == "output":
                v = eval_node(incoming.get(nid, {}).get("value"))
            elif t == "if":
                cond = eval_node(incoming.get(nid, {}).get("cond"))
                branch = "then" if is_truthy(cond) else "else"
                v = eval_node(incoming.get(nid, {}).get(branch))
            elif t == "assign":
                v = eval_node(incoming.get(nid, {}).get("value"))
                if d.get("name"):
                    scope[str(d["name"])] = v
            elif t == "value":
                kind = d.get("kind")
                if kind == "CONST":
                    v = d.get("value")
                    if isinstance(v, str):
                        s = v.strip()
                        if (s.startswith("[") and s.endswith("]")) or (
                            s.startswith("{") and s.endswith("}")
                        ):
                            try:
                                v = json.loads(s)
                            except (ValueError, TypeError):
                                pass
                elif kind == "FIELD":
                    key = d.get("fieldKey")
                    ref = field_by_key.get(key)
                    if ref is None:
                        v = None
                    else:
                        v = _stored_to_raw(ref, values.get(str(key)))
                elif kind == "OP":
                    handles = OP_ARG_SPECS.get(str(d.get("op")), [])
                    inc = incoming.get(nid, {})
                    v = apply_op(d.get("op"), [eval_node(inc.get(h)) for h in handles], scope)
                elif kind == "VAR":
                    v = scope.get(str(d.get("name") or ""))
                elif kind == "FORMULA":
                    # 沙箱变量：本产业类型全部字段现值（原始值形态）+ 运行期变量 + 数学助手
                    sandbox: dict = {}
                    for key, f in field_by_key.items():
                        sandbox[key] = _stored_to_raw(f, values.get(key))
                    sandbox.update(EXPR_HELPERS)
                    sandbox.update(scope)
                    try:
                        v = safe_evaluate(str(d.get("expr") or ""), sandbox)
                    except BusinessError:
                        raise
                elif kind == "CONSUMER_DEMAND":
                    v = _consumer_demand_total(company, values.get(LOCATION_FIELD_KEY))
            memo[nid] = v
            return v
        finally:
            stack.discard(nid)

    out = next((n for n in nodes.values() if n.get("type") == "output"), None)
    if out is None:
        return None
    return eval_node(out.get("id"))


def _write_calc_value(company_id: int, field_id: int, value: str) -> bool:
    """乐观锁写计算字段值（冲突重读重试一次；仍冲突则告警跳过，不阻断）。"""
    from apps.companies.models import CompanyFieldValue

    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=field_id
    ).first()
    if fv is None:
        CompanyFieldValue.objects.create(
            company_id=company_id, industry_field_id=field_id, value=value, version=1
        )
        return True
    updated = CompanyFieldValue.objects.filter(pk=fv.pk, version=fv.version).update(
        value=value, version=fv.version + 1
    )
    if updated:
        return True
    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=field_id
    ).first()
    if fv is None:
        return False
    updated = CompanyFieldValue.objects.filter(pk=fv.pk, version=fv.version).update(
        value=value, version=fv.version + 1
    )
    if not updated:
        logger.warning(
            "[calc] 计算字段写入乐观锁冲突重试失败 company=%s field=%s",
            company_id, field_id,
        )
    return False


def recompute_calc_fields(company_id: int) -> None:
    """级联重算某公司全部「计算字段」（按依赖拓扑序）。

    由手动编辑（company_fields views）、合同落账/复原（contracts views）、
    财年定时器（company_fields timer）在基础字段变更后调用。
    """
    from apps.companies.models import Company, CompanyFieldValue
    from apps.industry_types.models import IndustryField
    from .timer import _serialize

    company = (
        Company.objects.filter(pk=company_id)
        .values("id", "industry_type_id", "competition_id")
        .first()
    )
    if not company or not company.get("industry_type_id"):
        return

    fields = list(
        IndustryField.objects.filter(industry_type_id=company["industry_type_id"])
    )
    calc_fields = [f for f in fields if f.is_calculated and (f.calc_graph or "").strip()]
    if not calc_fields:
        return
    field_by_key = {f.field_key: f for f in fields}
    by_id = {f.id: f for f in fields}

    # 当前值快照（field_key -> 存储字符串）；后续计算字段的结果即时并入快照，
    # 保证「计算字段引用计算字段」取到的是本次重算后的新值。
    values: dict[str, str] = {}
    for fv in CompanyFieldValue.objects.filter(company_id=company_id).values(
        "industry_field_id", "value"
    ):
        f = by_id.get(fv["industry_field_id"])
        if f is not None:
            values[f.field_key] = fv["value"] if fv["value"] is not None else ""

    for f in _order_calc_fields(calc_fields):
        try:
            raw = _eval_graph(f, values, field_by_key, company)
            if raw is None:
                logger.warning(
                    "[calc] 字段 #%s(%s) 计算图无输出/求值为空，跳过", f.id, f.field_key
                )
                continue
            stored = _serialize(f.field_type, raw)
            values[f.field_key] = stored
            _write_calc_value(company_id, f.id, stored)
        except Exception as e:  # noqa: BLE001 单字段失败不中断其余字段
            logger.warning(
                "[calc] 字段 #%s(%s) 重算失败：%s", f.id, f.field_key, getattr(e, "message", e)
            )
