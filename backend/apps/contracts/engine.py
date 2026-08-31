"""合同引擎 DSL：对应原 NestJS contract-engine.service.ts + engine/*.ts +
common/engine-ops.ts + common/safe-expression.ts 的 Python 移植。

核心能力：
- ``eval_value_spec`` 按 spec.type 分派求值：CONST / INPUT / VAR / OP /
  FORMULA / ROUTE / FIELD / INDUSTRY_IS / ENTITY。INPUT 支持大量聚合端点
  （原料碳排放/价格、零件→原料、产品→零件、科技节点、载具/燃料/仓库/基建聚合等）。
- ``apply_op`` 列表/字典/通用运算（OP_NAMES 全集）。
- ``ContractEngine.execute`` 解析 effects，在事务内改写公司产业字段并落账
  ContractFieldEffect 不可变记录；``revert_contract`` 按事件溯源重放复原。
- ``ContractEngine.precheck`` 仅评估前置检查，不落账。

依赖的公司 / 产业字段 / 地图 / 各基础数据模型均在方法内懒加载，避免模块导入期
强依赖尚未创建的兄弟应用（apps.companies / apps.industry_types）。
"""
from __future__ import annotations

import heapq
import json
import math
from typing import Any, Iterable

from apps.common.exceptions import BusinessError
from apps.common.json_util import parse_field_config


# ==================== 常量（来自 shared/engine-dsl） ====================

OP_NAMES = [
    # 列表
    "LIST_APPEND", "LIST_CONCAT", "LIST_LEN", "LIST_CONTAINS", "LIST_INDEX_OF",
    "LIST_UNIQUE", "LIST_FLATTEN", "LIST_SUM_OF", "LIST_JOIN", "LIST_SLICE",
    "LIST_REVERSE", "LIST_SORT", "LIST_RANGE", "LIST_ADD", "LIST_SUB",
    # 字典
    "DICT_GET", "DICT_KEYS", "DICT_VALUES", "DICT_ENTRIES", "DICT_HAS_KEY",
    "DICT_MERGE", "DICT_FROM_PAIRS", "DICT_FROM_KEYS", "DICT_INVERT",
    "DICT_ADD", "DICT_SUB", "DICT_APPEND", "DICT_SUM",
    # 通用
    "LEN", "CONTAINS", "SUM_OF",
    # 算术
    "ADD", "SUB", "MUL", "DIV", "EXP", "LOG", "MIN", "MAX",
    # 比较
    "CMP_EQ", "CMP_NE", "CMP_GT", "CMP_LT", "CMP_GTE", "CMP_LTE",
]

ENTITY_MODEL_NAMES = {
    "MATERIAL": "materials.Material",
    "PART": "parts.Part",
    "PRODUCT": "products.Product",
    "TECH_NODE": "tech_tree.TechNode",
    "WAREHOUSE": "warehouses.Warehouse",
    "PRODUCTION_LINE": "production_lines.ProductionLine",
    "FUEL": "fuels.Fuel",
    "VEHICLE": "vehicles.Vehicle",
    "INFRASTRUCTURE": "infrastructures.Infrastructure",
    "MAP_NODE": "maps.MapNode",
}

COMPARE_OP_LABEL = {
    "GTE": "≥", "LTE": "≤", "GT": ">", "LT": "<", "EQ": "=",
    "CONTAINS": "包含", "HAS_KEY": "含键",
    "LEN_GTE": "长度≥", "LEN_LTE": "长度≤", "LEN_EQ": "长度=",
    "ELEMENT_EQ": "元素相等",
}

COND_KIND_LABEL = {
    "VALUE_COMPARE": "数值比较",
    "FIELD_COMPARE": "字段比较",
    "INDUSTRY_IS": "产业类型核对",
    "DICT_COMPARE": "字典比较",
    "LIST_COMPARE": "列表比较",
}

# camelCase → snake_case（用于把原 DSL 的 Prisma 字段名映射到 Django 字段名）
import re as _re

_CAMEL_RE = _re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower()


# ==================== 纯函数工具 ====================

def to_number(v: Any, fallback: float = 0) -> float:
    """任意值转数字（布尔/空串/非有限值兜底为 fallback）。"""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v if isinstance(v, (int, float)) and math.isfinite(v) else fallback
    if v is None or v == "":
        return fallback
    try:
        n = float(v)
    except (TypeError, ValueError):
        return fallback
    return n if math.isfinite(n) else fallback


def is_truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return bool(v)


def to_number_array(v: Any) -> list:
    """把输入值规范为数字数组（支持数组、JSON 字符串数组、逗号分隔字符串）。"""
    parse = lambda x: to_number(x)  # noqa: E731
    if isinstance(v, list):
        return [parse(x) for x in v if isinstance(to_number(x), (int, float)) and math.isfinite(to_number(x))]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                out = [parse(x) for x in arr]
                return [x for x in out if isinstance(x, (int, float)) and math.isfinite(x)]
        except (ValueError, TypeError):
            pass
        parts = [parse(t.strip()) for t in s.split(",")]
        return [x for x in parts if isinstance(x, (int, float)) and math.isfinite(x)]
    return []


def deep_equal(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(deep_equal(x, b[i]) for i, x in enumerate(a))
    if isinstance(a, dict) and isinstance(b, dict):
        ka, kb = list(a.keys()), list(b.keys())
        if len(ka) != len(kb):
            return False
        return all(k in b and deep_equal(a[k], b[k]) for k in a)
    if a is None or b is None:
        return a is None and b is None
    return False


def cast_scalar(type_name: str | None, val: Any) -> Any:
    t = (type_name or "STRING").upper()
    if t == "NUMBER":
        return to_number(val)
    if t == "BOOLEAN":
        return val is True or val == "true" or val == 1 or val == "1" or val == "是"
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def compare_op(actual: float, op: str, expected: float) -> bool:
    if op == "GT":
        return actual > expected
    if op == "LT":
        return actual < expected
    if op == "EQ":
        return actual == expected
    if op == "LTE":
        return actual <= expected
    return actual >= expected  # GTE / default


def cond_kind_label(kind: str) -> str:
    return COND_KIND_LABEL.get(kind, kind)


def safe_parse(raw: str | None, label: str) -> Any:
    """安全解析 JSON 字符串。空串视为 []。"""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as e:
        raise BusinessError(f"{label} 不是合法 JSON: {e}", code=400, status_code=400)


def parse_stored_field_value(raw: Any, field_type: str) -> Any:
    """解析 CompanyFieldValue.value（存储为 JSON 字符串）为运行期值。"""
    v = raw
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            v = None
        else:
            try:
                v = json.loads(s)
            except (ValueError, TypeError):
                v = raw  # 非 JSON，保留原字符串
    ft = (field_type or "STRING").upper()
    if ft == "LIST":
        return v if isinstance(v, list) else ([] if v is None else [v])
    if ft == "DICTIONARY":
        return v if isinstance(v, dict) else {}
    if ft == "BOOLEAN":
        return v is True or v == 1 or v == "true"
    if ft == "STRING":
        return "" if v is None else str(v)
    return to_number(v)


def parse_json_value(raw: Any) -> Any:
    """解析 JSON 字符串（安全，失败返回原值）。"""
    if raw is None:
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


# ==================== 字段效果执行 ====================

def apply_field_effect(
    current_raw: Any,
    field_type: str,
    config: Any,
    op: str,
    new_value: Any,
) -> dict:
    """对公司产业字段执行 ADD/SUB/SET，返回 {store, before, after}。"""
    is_list = field_type == "LIST"
    is_dict = field_type == "DICTIONARY"
    item_type = (config or {}).get("itemType") or (config or {}).get("valueType") or "STRING"

    def parse_current():
        if is_list:
            if isinstance(current_raw, list):
                return current_raw
            if isinstance(current_raw, str) and current_raw:
                try:
                    p = json.loads(current_raw)
                    return p if isinstance(p, list) else []
                except (ValueError, TypeError):
                    return []
            return []
        if is_dict:
            if isinstance(current_raw, dict):
                return current_raw
            if isinstance(current_raw, str) and current_raw:
                try:
                    p = json.loads(current_raw)
                    return p if isinstance(p, dict) else {}
                except (ValueError, TypeError):
                    return {}
            return {}
        return parse_stored_field_value(current_raw, field_type)

    before = parse_current()
    after: Any

    if is_list:
        base = before if isinstance(before, list) else []
        if isinstance(new_value, list):
            items = new_value
        elif new_value is None:
            items = []
        else:
            items = [new_value]
        if op == "SET":
            after = items
        elif op == "SUB":
            after = [i for i in base if not any(deep_equal(x, i) for x in items)]
        else:  # ADD 去重
            after = list(base) + [it for it in items if not any(deep_equal(b, it) for b in base)]
        after = [cast_scalar(item_type, it) for it in after]
    elif is_dict:
        base = before if isinstance(before, dict) else {}
        if isinstance(new_value, dict):
            obj = new_value
        elif isinstance(new_value, str) and new_value:
            obj = {new_value: True}
        else:
            obj = {}
        if op == "SET":
            after = obj
        elif op == "SUB":
            if isinstance(new_value, list):
                remove_keys = [str(k) for k in new_value]
            elif isinstance(new_value, dict):
                remove_keys = list(new_value.keys())
            else:
                remove_keys = [str(new_value)]
            after = {k: v for k, v in base.items() if k not in remove_keys}
        else:  # ADD 合并
            after = {**base, **obj}
        value_type = (config or {}).get("valueType") or "STRING"
        after = {k: cast_scalar(value_type, v) for k, v in after.items()}
    else:
        ft = (field_type or "STRING").upper()
        if ft in ("STRING", "BOOLEAN"):
            after = cast_scalar(ft, new_value)
        else:
            n_before = to_number(before)
            n_val = to_number(new_value)
            if op == "SET":
                after = n_val
            elif op == "SUB":
                after = n_before - n_val
            else:  # ADD
                after = n_before + n_val
    return {"store": json.dumps(after, ensure_ascii=False), "before": before, "after": after}


def compare_field(
    current_raw: Any,
    field_type: str,
    config: Any,
    op: str,
    expected: Any,
) -> dict:
    """对公司产业字段做前置比较，返回 {passed, actual, expected, detail}。"""
    is_list = field_type == "LIST"
    is_dict = field_type == "DICTIONARY"

    def parse_current():
        if is_list:
            if isinstance(current_raw, list):
                return current_raw
            if isinstance(current_raw, str) and current_raw:
                try:
                    p = json.loads(current_raw)
                    return p if isinstance(p, list) else []
                except (ValueError, TypeError):
                    return []
            return []
        if is_dict:
            if isinstance(current_raw, dict):
                return current_raw
            if isinstance(current_raw, str) and current_raw:
                try:
                    p = json.loads(current_raw)
                    return p if isinstance(p, dict) else {}
                except (ValueError, TypeError):
                    return {}
            return {}
        return to_number(current_raw)

    actual = parse_current()
    length = len(actual) if isinstance(actual, list) else len(actual) if isinstance(actual, dict) else 0

    if op == "CONTAINS":
        ok = (
            any(deep_equal(i, expected) for i in actual)
            if is_list
            else (expected in actual if is_dict else False)
        )
        if not is_list and is_dict:
            ok = expected in actual or any(deep_equal(v, expected) for v in actual.values())
        return {"passed": ok, "actual": actual, "expected": expected, "detail": f"字段包含 {json.dumps(expected, ensure_ascii=False)}: {'是' if ok else '否'}"}
    if op == "HAS_KEY":
        ok = is_dict and expected in actual
        return {"passed": ok, "actual": actual, "expected": expected, "detail": f"字典含键 {expected}: {'是' if ok else '否'}"}
    if op == "LEN_EQ":
        return {"passed": length == to_number(expected), "actual": length, "expected": to_number(expected), "detail": f"长度={length} == {to_number(expected)}"}
    if op == "LEN_GTE":
        return {"passed": length >= to_number(expected), "actual": length, "expected": to_number(expected), "detail": f"长度={length} >= {to_number(expected)}"}
    if op == "LEN_LTE":
        return {"passed": length <= to_number(expected), "actual": length, "expected": to_number(expected), "detail": f"长度={length} <= {to_number(expected)}"}
    if op == "EQ":
        return {"passed": deep_equal(actual, expected), "actual": actual, "expected": expected, "detail": "结构相等比较"}
    # 标量比较
    if not is_list and not is_dict and (field_type or "").upper() == "STRING":
        a, b = str(actual or ""), str(expected or "")
        ok = (a > b if op == "GT" else a < b if op == "LT" else a <= b if op == "LTE" else a >= b)
        return {"passed": ok, "actual": a, "expected": b, "detail": f'"{a}" {op} "{b}"'}
    ok = (
        length > to_number(expected) if op == "GT"
        else length < to_number(expected) if op == "LT"
        else length <= to_number(expected) if op == "LTE"
        else length >= to_number(expected)
    )
    return {"passed": ok, "actual": length, "expected": to_number(expected), "detail": f"长度{op} {to_number(expected)}"}


def combine_values(v1: Any, v2: Any, vop: str, field_type: str) -> Any:
    """组合效果的两个数值来源（value + value2）。"""
    is_list = field_type == "LIST"
    is_dict = field_type == "DICTIONARY"
    if is_list:
        a = v1 if isinstance(v1, list) else ([] if v1 is None else [v1])
        b = v2 if isinstance(v2, list) else ([] if v2 is None else [v2])
        if vop == "SUB":
            return [i for i in a if not any(deep_equal(x, i) for x in b)]
        return a + b
    if is_dict:
        a = v1 if isinstance(v1, dict) else {}
        b = v2 if isinstance(v2, dict) else {}
        if vop == "SUB":
            return {k: v for k, v in a.items() if k not in b}
        return {**a, **b}
    ft = (field_type or "STRING").upper()
    if ft == "STRING":
        return "" if v1 is None else v1
    if ft == "BOOLEAN":
        return v1 is True or v1 == "true" or v1 == 1 or v1 == "1"
    a, b = to_number(v1), to_number(v2)
    if vop == "MUL":
        return a * b
    if vop == "SUB":
        return a - b
    return a + b


# ==================== 公式安全求值器（移植 safe-expression.ts） ====================
# 自研受限递归下降解析器：仅允许数字/字符串/数组字面量、变量引用、白名单内置函数、
# EXPR_HELPERS、算术(+ - * / % ^ **)、比较、逻辑(! && ||)、一元负号、数组下标、括号。
# 明确不支持成员访问(a.b)，从语法层面堵死 constructor/Function 等逃逸路径。

class _SafeExpressionError(Exception):
    pass


def _tok_is_digit(c: str) -> bool:
    return c.isdigit()


def _tok_is_ident_start(c: str) -> bool:
    return c.isalpha() or c in "_$"


def _tok_is_ident_part(c: str) -> bool:
    return c.isalnum() or c in "_$"


class _Tokenizer:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def tokenize(self) -> list:
        out: list = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\n\r":
                self.i += 1
                continue
            if c == "(":
                out.append(("lparen", c)); self.i += 1; continue
            if c == ")":
                out.append(("rparen", c)); self.i += 1; continue
            if c == "[":
                out.append(("lbracket", c)); self.i += 1; continue
            if c == "]":
                out.append(("rbracket", c)); self.i += 1; continue
            if c == ",":
                out.append(("comma", c)); self.i += 1; continue
            if c.isdigit() or (c == "." and self.i + 1 < len(self.s) and self.s[self.i + 1].isdigit()):
                out.append(self._read_number()); continue
            if c == '"' or c == "'":
                out.append(self._read_string(c)); continue
            if _tok_is_ident_start(c):
                out.append(self._read_ident()); continue
            two = self.s[self.i:self.i + 2]
            if two in ("**", "==", "!=", "<=", ">=", "&&", "||"):
                out.append(("op", two)); self.i += 2; continue
            if c in "+-*/%^<>!":
                out.append(("op", c)); self.i += 1; continue
            raise _SafeExpressionError(f'不支持的字符: "{c}"')
        out.append(("eof", ""))
        return out

    def _read_number(self) -> tuple:
        start = self.i
        while self.i < len(self.s) and (self.s[self.i].isdigit() or self.s[self.i] == "."):
            self.i += 1
        if self.i < len(self.s) and self.s[self.i] in "eE":
            self.i += 1
            if self.i < len(self.s) and self.s[self.i] in "+-":
                self.i += 1
            while self.i < len(self.s) and self.s[self.i].isdigit():
                self.i += 1
        text = self.s[start:self.i]
        try:
            n = float(text) if ("." in text or "e" in text or "E" in text) else int(text)
        except ValueError:
            raise _SafeExpressionError(f"非法数字: {text}")
        return ("num", text)

    def _read_string(self, quote: str) -> tuple:
        self.i += 1
        buf = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\":
                self.i += 1
                e = self.s[self.i] if self.i < len(self.s) else ""
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(e, e))
                self.i += 1
                continue
            if c == quote:
                self.i += 1
                break
            buf.append(c)
            self.i += 1
        return ("str", "".join(buf))

    def _read_ident(self) -> tuple:
        start = self.i
        while self.i < len(self.s) and _tok_is_ident_part(self.s[self.i]):
            self.i += 1
        return ("ident", self.s[start:self.i])


def _f_to_num(v: Any) -> float:
    return to_number(v)


def _f_truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return len(v) > 0
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return bool(v)


def _f_as_list(x: Any) -> list:
    return x if isinstance(x, list) else ([] if x is None else [x])


def _f_add(a: Any, b: Any) -> Any:
    if isinstance(a, list) or isinstance(b, list):
        return _f_as_list(a) + _f_as_list(b)
    if isinstance(a, str) or isinstance(b, str):
        return str(a) + str(b)
    return _f_to_num(a) + _f_to_num(b)


def _f_sub(a: Any, b: Any) -> Any:
    if isinstance(a, list) or isinstance(b, list):
        lb = _f_as_list(b)
        return [x for x in _f_as_list(a) if not any(deep_equal(y, x) for y in lb)]
    return _f_to_num(a) - _f_to_num(b)


def _f_index(v: Any, idx: Any) -> Any:
    if isinstance(v, list):
        i = int(_f_to_num(idx))
        return v[i] if 0 <= i < len(v) else 0
    if isinstance(v, dict):
        return v[idx] if idx in v else 0
    return 0


_BUILTIN_CONSTS = {"pi": math.pi, "e": math.e}


def _builtin_funcs() -> dict:
    fns = {
        "abs": lambda x: abs(_f_to_num(x)),
        "sqrt": lambda x: math.sqrt(_f_to_num(x)),
        "cbrt": lambda x: math.copysign(abs(_f_to_num(x)) ** (1 / 3), _f_to_num(x)),
        "sign": lambda x: math.copysign(0.0, _f_to_num(x)) if _f_to_num(x) == 0 else (1 if _f_to_num(x) > 0 else -1),
        "floor": lambda x: math.floor(_f_to_num(x)),
        "ceil": lambda x: math.ceil(_f_to_num(x)),
        "round": lambda x: round(_f_to_num(x)),
        "trunc": lambda x: math.trunc(_f_to_num(x)),
        "pow": lambda a, b: math.pow(_f_to_num(a), _f_to_num(b)),
        "exp": lambda x: math.exp(_f_to_num(x)),
        "log": lambda x: math.log(_f_to_num(x)),
        "log2": lambda x: math.log2(_f_to_num(x)),
        "log10": lambda x: math.log10(_f_to_num(x)),
        "sin": lambda x: math.sin(_f_to_num(x)),
        "cos": lambda x: math.cos(_f_to_num(x)),
        "tan": lambda x: math.tan(_f_to_num(x)),
        "asin": lambda x: math.asin(_f_to_num(x)),
        "acos": lambda x: math.acos(_f_to_num(x)),
        "atan": lambda x: math.atan(_f_to_num(x)),
        "atan2": lambda y, x: math.atan2(_f_to_num(y), _f_to_num(x)),
        "sinh": lambda x: math.sinh(_f_to_num(x)),
        "cosh": lambda x: math.cosh(_f_to_num(x)),
        "tanh": lambda x: math.tanh(_f_to_num(x)),
        "hypot": lambda *a: math.hypot(*[_f_to_num(x) for x in a]),
        "mod": lambda a, b: (0 if _f_to_num(b) == 0 else _f_to_num(a) % _f_to_num(b)),
        "clamp": lambda x, lo, hi: min(max(_f_to_num(x), _f_to_num(lo)), _f_to_num(hi)),
        "min": lambda *a: (lambda arr: min(arr) if arr else 0)([_f_to_num(x) for x in (_a_unpack(a[0]) if len(a) == 1 and isinstance(a[0], list) else list(a))]),
        "max": lambda *a: (lambda arr: max(arr) if arr else 0)([_f_to_num(x) for x in (_a_unpack(a[0]) if len(a) == 1 and isinstance(a[0], list) else list(a))]),
        "sum": lambda *a: (lambda arr: sum(_f_to_num(x) for x in arr))(_a_unpack(a[0]) if len(a) == 1 and isinstance(a[0], list) else list(a)),
        "avg": lambda *a: (lambda arr: (sum(_f_to_num(x) for x in arr) / len(arr)) if arr else 0)(_a_unpack(a[0]) if len(a) == 1 and isinstance(a[0], list) else list(a)),
    }
    return fns


def _a_unpack(x: Any) -> list:
    return x if isinstance(x, list) else []


_BUILTIN_FUNCS = _builtin_funcs()


class _FormulaParser:
    def __init__(self, tokens: list, scope: dict):
        self.tokens = tokens
        self.pos = 0
        self.scope = scope

    def _peek(self):
        return self.tokens[self.pos]

    def _next(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def _expect(self, ttype, val=None):
        t = self._next()
        if t[0] != ttype or (val and t[1] != val):
            raise _SafeExpressionError(f'语法错误：期望 {val or ttype}，实际 "{t[1] or t[0]}"')
        return t

    def parse(self):
        v = self._parse_or()
        if self._peek()[0] != "eof":
            raise _SafeExpressionError(f'表达式存在多余内容: "{self._peek()[1]}"')
        return v

    def _parse_or(self):
        left = self._parse_and()
        while self._peek()[0] == "op" and self._peek()[1] == "||":
            self._next()
            right = self._parse_and()
            left = left if _f_truthy(left) else (right if _f_truthy(right) else right)
            # 语义贴近 JS：truthy(left) 返回 left，否则 truthy(right) 返回 right，否则 right
            left = left if _f_truthy(left) else right
        return left

    def _parse_and(self):
        left = self._parse_equality()
        while self._peek()[0] == "op" and self._peek()[1] == "&&":
            self._next()
            right = self._parse_equality()
            left = left if (_f_truthy(left) and _f_truthy(right)) else right
        return left

    def _parse_equality(self):
        left = self._parse_comparison()
        while self._peek()[0] == "op" and self._peek()[1] in ("==", "!="):
            op = self._next()[1]
            right = self._parse_comparison()
            eq = deep_equal(left, right)
            left = eq if op == "==" else (not eq)
        return left

    def _parse_comparison(self):
        left = self._parse_additive()
        while self._peek()[0] == "op" and self._peek()[1] in ("<", ">", "<=", ">="):
            op = self._next()[1]
            right = self._parse_additive()
            a, b = _f_to_num(left), _f_to_num(right)
            left = (a < b if op == "<" else a > b if op == ">" else a <= b if op == "<=" else a >= b)
        return left

    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._peek()[0] == "op" and self._peek()[1] in ("+", "-"):
            op = self._next()[1]
            right = self._parse_multiplicative()
            left = _f_add(left, right) if op == "+" else _f_sub(left, right)
        return left

    def _parse_multiplicative(self):
        left = self._parse_power()
        while self._peek()[0] == "op" and self._peek()[1] in ("*", "/", "%"):
            op = self._next()[1]
            right = self._parse_power()
            a, b = _f_to_num(left), _f_to_num(right)
            left = a * b if op == "*" else (0 if b == 0 else a / b) if op == "/" else (0 if b == 0 else a % b)
        return left

    def _parse_power(self):
        base = self._parse_unary()
        if self._peek()[0] == "op" and self._peek()[1] in ("^", "**"):
            self._next()
            exp = self._parse_power()  # 右结合
            return math.pow(_f_to_num(base), _f_to_num(exp))
        return base

    def _parse_unary(self):
        t = self._peek()
        if t[0] == "op" and t[1] in ("-", "+", "!"):
            self._next()
            v = self._parse_unary()
            if t[1] == "-":
                return -_f_to_num(v)
            if t[1] == "+":
                return _f_to_num(v)
            return not _f_truthy(v)
        return self._parse_postfix()

    def _parse_postfix(self):
        v = self._parse_primary()
        while self._peek()[0] == "lbracket":
            self._next()
            idx = self._parse_or()
            self._expect("rbracket")
            v = _f_index(v, idx)
        return v

    def _parse_primary(self):
        t = self._next()
        if t[0] == "num":
            text = t[1]
            return float(text) if ("." in text or "e" in text or "E" in text) else int(text)
        if t[0] == "str":
            return t[1]
        if t[0] == "lparen":
            v = self._parse_or()
            self._expect("rparen")
            return v
        if t[0] == "lbracket":
            arr = []
            if self._peek()[0] != "rbracket":
                arr.append(self._parse_or())
                while self._peek()[0] == "comma":
                    self._next()
                    arr.append(self._parse_or())
            self._expect("rbracket")
            return arr
        if t[0] == "ident":
            name = t[1]
            if name == "true":
                return True
            if name == "false":
                return False
            if name == "null":
                return None
            if self._peek()[0] == "lparen":
                self._next()
                args = []
                if self._peek()[0] != "rparen":
                    args.append(self._parse_or())
                    while self._peek()[0] == "comma":
                        self._next()
                        args.append(self._parse_or())
                self._expect("rparen")
                return self._call_fn(name, args)
            if name in self.scope:
                return self.scope[name]
            if name in _BUILTIN_CONSTS:
                return _BUILTIN_CONSTS[name]
            return 0  # 未定义变量回退为 0
        raise _SafeExpressionError(f'意外的记号: "{t[1] or t[0]}"')

    def _call_fn(self, name: str, args: list):
        builtin = _BUILTIN_FUNCS.get(name)
        if builtin is not None:
            return builtin(*args)
        sc = self.scope.get(name)
        if callable(sc):
            return sc(*args)
        raise _SafeExpressionError(f"未知函数: {name}")


def safe_evaluate(expr: str, scope: dict | None = None) -> Any:
    """安全求值受限数学表达式（不使用 eval）。"""
    if expr is None or expr == "":
        return 0
    tokens = _Tokenizer(expr).tokenize()
    return _FormulaParser(tokens, scope or {}).parse()


# ==================== EXPR_HELPERS（表达式作用域辅助函数） ====================

def _expr_truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return len(v) > 0
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return bool(v)


EXPR_HELPERS = {
    "IF": lambda cond, a, b: a if _expr_truthy(cond) else b,
    "AND": lambda *args: all(_expr_truthy(x) for x in args),
    "OR": lambda *args: any(_expr_truthy(x) for x in args),
    "NOT": lambda x: not _expr_truthy(x),
    "len": lambda x: (
        len(x) if isinstance(x, (list, dict, str)) else (0 if x is None else len(str(x)))
    ),
    "push": lambda arr, *items: (list(arr) + list(items)) if isinstance(arr, list) else [arr] + list(items),
    "concat": lambda a, b: (_a_unpack(a) if isinstance(a, list) else [a]) + (_a_unpack(b) if isinstance(b, list) else [b]),
    "contains": lambda c, x: (
        any(deep_equal(i, x) for i in c) if isinstance(c, list)
        else (x in c if isinstance(c, dict) and x in c else (any(deep_equal(v, x) for v in c.values()) if isinstance(c, dict) else False))
    ),
    "indexIn": lambda arr, x: (next((i for i, it in enumerate(arr) if deep_equal(it, x)), -1)) if isinstance(arr, list) else -1,
    "keys": lambda o: list(o.keys()) if isinstance(o, dict) else [],
    "values": lambda o: list(o.values()) if isinstance(o, dict) else [],
    "get": lambda o, k: (o.get(k) if isinstance(o, dict) else (None if o is None else None)),
    "has": lambda o, k: (o is not None and isinstance(o, dict) and o.get(k) is not None),
    "hasKey": lambda o, k: (o is not None and isinstance(o, dict) and k in o),
    "merge": lambda *objs: {k: v for o in objs for k, v in (o.items() if isinstance(o, dict) else {})},
    "unique": lambda arr: [v for i, v in enumerate(arr) if not any(deep_equal(x, v) for x in arr[:i])] if isinstance(arr, list) else arr,
    "flatten": _a_unpack,
    "join": lambda arr, sep=",": (sep.join(str(x) for x in arr)) if isinstance(arr, list) else str(arr),
    "sumOf": lambda arr: sum(to_number(x) for x in arr) if isinstance(arr, list) else 0,
}


# ==================== apply_op（列表/字典/通用运算） ====================

def apply_op(op: str, args: list, scope: dict | None = None) -> Any:
    a = args
    as_list = lambda x: x if isinstance(x, list) else ([] if x is None else [x])  # noqa: E731
    as_dict = lambda x: x if isinstance(x, dict) else {}  # noqa: E731
    num = to_number

    # —— 列表 ——
    if op == "LIST_APPEND":
        return as_list(a[0]) + list(a[1:])
    if op == "LIST_CONCAT":
        out = []
        for x in a:
            out.extend(as_list(x))
        return out
    if op == "LIST_LEN":
        return len(a[0]) if isinstance(a[0], (list, str)) else len(as_list(a[0]))
    if op == "LIST_CONTAINS":
        return any(deep_equal(i, a[1]) for i in as_list(a[0]))
    if op == "LIST_INDEX_OF":
        lst = as_list(a[0])
        for i, it in enumerate(lst):
            if deep_equal(it, a[1]):
                return i
        return -1
    if op == "LIST_UNIQUE":
        lst = as_list(a[0])
        out = []
        for v in lst:
            if not any(deep_equal(x, v) for x in out):
                out.append(v)
        return out
    if op == "LIST_FLATTEN":
        def _flat(x):
            if isinstance(x, list):
                out = []
                for i in x:
                    out.extend(_flat(i))
                return out
            return [x]
        return _flat(a[0]) if isinstance(a[0], list) else as_list(a[0])
    if op == "LIST_SUM_OF":
        return sum(num(x) for x in as_list(a[0]))
    if op == "LIST_JOIN":
        sep = "," if a[1] is None else str(a[1])
        return sep.join("" if x is None else str(x) for x in as_list(a[0]))
    if op == "LIST_SLICE":
        arr = as_list(a[0])
        start = 0 if a[1] is None else int(num(a[1]))
        end = len(arr) if a[2] is None else int(num(a[2]))
        return arr[start:end]
    if op == "LIST_REVERSE":
        return list(reversed(as_list(a[0])))
    if op == "LIST_SORT":
        return sorted(as_list(a[0]), key=lambda x: (num(x), str(x)))
    if op == "LIST_RANGE":
        start = num(a[0])
        stop = start if a[1] is None else num(a[1])
        step = (1 if start <= stop else -1) if a[2] is None else num(a[2])
        out = []
        if step == 0:
            return out
        i = start
        if step > 0:
            while i < stop:
                out.append(i); i += step
        else:
            while i > stop:
                out.append(i); i += step
        return out
    if op == "LIST_ADD":
        merged = as_list(a[0]) + as_list(a[1])
        out = []
        for v in merged:
            if not any(deep_equal(x, v) for x in out):
                out.append(v)
        return out
    if op == "LIST_SUB":
        la = as_list(a[0]); lb = as_list(a[1])
        return [v for v in la if not any(deep_equal(x, v) for x in lb)]

    # —— 字典 ——
    if op == "DICT_GET":
        d = as_dict(a[0]); k = a[1]
        return d[k] if k in d else a[2]
    if op == "DICT_KEYS":
        return list(as_dict(a[0]).keys())
    if op == "DICT_VALUES":
        return list(as_dict(a[0]).values())
    if op == "DICT_ENTRIES":
        return [[k, v] for k, v in as_dict(a[0]).items()]
    if op == "DICT_HAS_KEY":
        return a[1] in as_dict(a[0])
    if op == "DICT_MERGE":
        out = {}
        for x in a:
            out.update(as_dict(x))
        return out
    if op == "DICT_FROM_PAIRS":
        out = {}
        for pair in as_list(a[0]):
            if isinstance(pair, list) and len(pair) >= 2:
                out[pair[0]] = pair[1]
        return out
    if op == "DICT_FROM_KEYS":
        keys = as_list(a[0]); val = a[1]; return {k: val for k in keys}
    if op == "DICT_INVERT":
        return {str(v): k for k, v in as_dict(a[0]).items()}
    if op == "DICT_ADD":
        da = as_dict(a[0]); db = as_dict(a[1]); out = {}
        for k in da:
            out[k] = num(da[k]) + num(db[k]) if k in db else da[k]
        for k in db:
            if k not in da:
                out[k] = db[k]
        return out
    if op == "DICT_SUB":
        da = as_dict(a[0]); db = as_dict(a[1]); out = {}
        for k in da:
            out[k] = num(da[k]) - num(db[k]) if k in db else da[k]
        for k in db:
            if k not in da:
                out[k] = -num(db[k])
        return out
    if op == "DICT_APPEND":
        d = as_dict(a[0]); k = a[1]; v = a[2]
        return {**d, k: v}
    if op == "DICT_SUM":
        return sum(num(v) for v in as_dict(a[0]).values())

    # —— 通用 ——
    if op == "LEN":
        x = a[0]
        if isinstance(x, (list, str)):
            return len(x)
        if isinstance(x, dict):
            return len(x)
        return 0 if x is None else len(str(x))
    if op == "CONTAINS":
        x = a[0]
        if isinstance(x, list):
            return any(deep_equal(i, a[1]) for i in x)
        d = as_dict(x)
        return a[1] in d or any(deep_equal(v, a[1]) for v in d.values())
    if op == "SUM_OF":
        return sum(num(x) for x in as_list(a[0]))

    # —— 算术 ——
    if op == "ADD":
        return num(a[0]) + num(a[1])
    if op == "SUB":
        return num(a[0]) - num(a[1])
    if op == "MUL":
        return num(a[0]) * num(a[1])
    if op == "DIV":
        return 0 if num(a[1]) == 0 else num(a[0]) / num(a[1])
    if op == "EXP":
        return math.exp(num(a[0]))
    if op == "LOG":
        x = num(a[0]); base = num(a[1])
        return math.log(x) / math.log(base) if base > 0 else math.log(x)
    if op == "MIN":
        return min(num(a[0]), num(a[1]))
    if op == "MAX":
        return max(num(a[0]), num(a[1]))

    # —— 比较 ——
    if op == "CMP_EQ":
        return deep_equal(a[0], a[1])
    if op == "CMP_NE":
        return not deep_equal(a[0], a[1])
    if op == "CMP_GT":
        return num(a[0]) > num(a[1])
    if op == "CMP_LT":
        return num(a[0]) < num(a[1])
    if op == "CMP_GTE":
        return num(a[0]) >= num(a[1])
    if op == "CMP_LTE":
        return num(a[0]) <= num(a[1])

    raise BusinessError(f"未知运算: {op}", code=400, status_code=400)


# ==================== 求值上下文 ====================

class EvalCtx:
    """运行期求值上下文：地图路程按比赛隔离并缓存邻接表；产业字段现值按角色定位公司。"""

    def __init__(self, competition_id=None, parties=None):
        self.competition_id = competition_id
        # route 邻接表缓存：{competition_id: {node_id: [(to, d), ...]}}
        self.cache: dict = {}
        # 参与方表：{role: {role, companyId, isHost?}}
        self.parties: dict = parties or {}
        # 产业字段现值预加载缓存：{"companyId:fieldKey": entry}
        self.field_cache: dict | None = None


# ==================== 聚合计算端点 ====================
# 以下函数从 Prisma 查询改为 Django ORM 查询；字段名映射 camelCase→snake_case。

def _entries(raw: Any) -> list:
    """提取 {name: qty} 字典中数量 > 0 的 (name, qty) 对。"""
    if not isinstance(raw, dict):
        return []
    return [(str(k), v) for k, v in raw.items() if to_number(v) > 0]


def _require_competition(competition_id, label: str):
    if not competition_id:
        raise BusinessError(f"计算{label}缺少比赛上下文（competitionId）", code=400, status_code=400)


def compute_material_list_carbon(raw, competition_id):
    if not isinstance(raw, dict):
        return 0
    entries = _entries(raw)
    if not entries:
        return 0
    _require_competition(competition_id, "原料清单碳排放")
    from apps.materials.models import Material

    names = [n for n, _ in entries]
    mats = Material.objects.filter(competition_id=competition_id, name__in=names).values("name", "carbon_emission_coefficient")
    coeff = {m["name"]: to_number(m["carbon_emission_coefficient"]) for m in mats}
    return sum(coeff.get(name, 0) * to_number(q) for name, q in entries)


def compute_material_list_price(raw, competition_id, location_node_id=None):
    if not isinstance(raw, dict):
        return 0
    entries = _entries(raw)
    if not entries:
        return 0
    _require_competition(competition_id, "原料清单总价格")
    from apps.materials.models import Material

    names = [n for n, _ in entries]
    mats = Material.objects.filter(competition_id=competition_id, name__in=names).values("name", "price", "node_prices")
    by_name = {m["name"]: m for m in mats}
    # 预解析地点价表
    node_prices_map = {}
    if location_node_id is not None:
        for m in mats:
            try:
                np = json.loads(m["node_prices"]) if m["node_prices"] else {}
            except (ValueError, TypeError):
                np = {}
            if isinstance(np, dict) and str(location_node_id) in np:
                node_prices_map[m["name"]] = to_number(np[str(location_node_id)])

    total = 0
    for name, q in entries:
        m = by_name.get(name)
        if not m:
            continue
        if location_node_id is not None and name in node_prices_map:
            price = node_prices_map[name]
        else:
            price = to_number(m["price"])
        total += price * to_number(q)
    return total


def compute_total_qty(raw) -> float:
    if not isinstance(raw, dict):
        return 0
    return sum(to_number(v) for v in raw.values())


def compute_part_materials(raw, competition_id):
    if not isinstance(raw, dict):
        return {}
    entries = _entries(raw)
    if not entries:
        return {}
    _require_competition(competition_id, "零件所需原料")
    from apps.parts.models import Part, PartMaterial

    names = [n for n, _ in entries]
    parts = {p["name"]: p for p in Part.objects.filter(competition_id=competition_id, name__in=names).values("id", "name")}
    part_ids = [p["id"] for p in parts.values()]
    pms = PartMaterial.objects.filter(part_id__in=part_ids).select_related("material").values("part_id", "ratio", "material__name")
    # 按 part_id 聚合配比
    ratios_by_part: dict = {}
    for pm in pms:
        ratios_by_part.setdefault(pm["part_id"], []).append((pm["material__name"], to_number(pm["ratio"])))
    result: dict = {}
    for pname, q in entries:
        part = parts.get(pname)
        if not part:
            continue
        qty = to_number(q)
        for mname, ratio in ratios_by_part.get(part["id"], []):
            result[mname] = result.get(mname, 0) + ratio * qty
    return result


def compute_product_parts(raw, competition_id):
    if not isinstance(raw, dict):
        return {}
    entries = _entries(raw)
    if not entries:
        return {}
    _require_competition(competition_id, "产品所需零件")
    from apps.products.models import Product, ProductPart

    names = [n for n, _ in entries]
    prods = {p["name"]: p for p in Product.objects.filter(competition_id=competition_id, name__in=names).values("id", "name")}
    prod_ids = [p["id"] for p in prods.values()]
    pps = ProductPart.objects.filter(product_id__in=prod_ids).select_related("part").values("product_id", "ratio", "part__name")
    ratios_by_prod: dict = {}
    for pp in pps:
        ratios_by_prod.setdefault(pp["product_id"], []).append((pp["part__name"], to_number(pp["ratio"])))
    result: dict = {}
    for pname, q in entries:
        prod = prods.get(pname)
        if not prod:
            continue
        qty = to_number(q)
        for part_name, ratio in ratios_by_prod.get(prod["id"], []):
            result[part_name] = result.get(part_name, 0) + ratio * qty
    return result


def _compute_name_list_tech_nodes(raw, competition_id, model_cls, label):
    if not isinstance(raw, dict):
        return []
    names = [str(k) for k, v in raw.items() if to_number(v) > 0]
    if not names:
        return []
    _require_competition(competition_id, f"{label}所需科技节点")
    records = model_cls.objects.filter(competition_id=competition_id, name__in=names).values("id")
    ids = [r["id"] for r in records]
    if not ids:
        return []
    # tech_requirements related_name
    rel = model_cls.objects.filter(pk__in=ids).values("tech_requirements__tech_node__name")
    seen = set()
    out = []
    for r in rel:
        n = r["tech_requirements__tech_node__name"]
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def compute_part_tech_nodes(raw, competition_id):
    from apps.parts.models import Part
    return _compute_name_list_tech_nodes(raw, competition_id, Part, "零件")


def compute_product_tech_nodes(raw, competition_id):
    from apps.products.models import Product
    return _compute_name_list_tech_nodes(raw, competition_id, Product, "产品")


def _compute_named_field_aggregate(raw, competition_id, model_cls, field_attr, label):
    if not isinstance(raw, dict):
        return 0
    entries = _entries(raw)
    if not entries:
        return 0
    _require_competition(competition_id, label)
    names = [n for n, _ in entries]
    recs = model_cls.objects.filter(competition_id=competition_id, name__in=names).values("name", field_attr)
    val = {r["name"]: to_number(r[field_attr]) for r in recs}
    return sum(val.get(name, 0) * to_number(q) for name, q in entries)


def compute_infra_total(raw, competition_id, field):
    from apps.infrastructures.models import Infrastructure
    return _compute_named_field_aggregate(raw, competition_id, Infrastructure, _camel_to_snake(field), "基建清单聚合")


def compute_vehicle_total_price(raw, competition_id):
    from apps.vehicles.models import Vehicle
    return _compute_named_field_aggregate(raw, competition_id, Vehicle, "price", "载具清单总价格")


def compute_vehicle_total_cargo(raw, competition_id):
    from apps.vehicles.models import Vehicle
    return _compute_named_field_aggregate(raw, competition_id, Vehicle, "max_cargo", "载具清单总载货量")


def compute_vehicle_total_fuel_per_km(raw, competition_id):
    from apps.vehicles.models import Vehicle
    return _compute_named_field_aggregate(raw, competition_id, Vehicle, "fuel_consumption_per_km", "载具清单总每公里油耗")


def compute_vehicle_total_carbon(raw, competition_id):
    from apps.vehicles.models import Vehicle
    return _compute_named_field_aggregate(raw, competition_id, Vehicle, "carbon_emission", "载具清单总碳排数")


def compute_fuel_total_price(raw, competition_id):
    from apps.fuels.models import Fuel
    return _compute_named_field_aggregate(raw, competition_id, Fuel, "price_per_liter", "燃料清单总价格")


def compute_warehouse_total_storage(raw, competition_id):
    if not isinstance(raw, dict):
        return {}
    entries = _entries(raw)
    if not entries:
        return {}
    _require_competition(competition_id, "仓库清单总存储量")
    from apps.warehouses.models import Warehouse

    names = [n for n, _ in entries]
    whs = Warehouse.objects.filter(competition_id=competition_id, name__in=names).values("name", "type", "capacity")
    info = {w["name"]: (w["type"] or "UNKNOWN", to_number(w["capacity"])) for w in whs}
    by_type: dict = {}
    for name, q in entries:
        rec = info.get(name)
        if not rec:
            continue
        key = rec[0]
        by_type[key] = by_type.get(key, 0) + rec[1] * to_number(q)
    return by_type


def compute_warehouse_total_price(raw, competition_id):
    from apps.warehouses.models import Warehouse
    return _compute_named_field_aggregate(raw, competition_id, Warehouse, "price", "仓库清单总价格")


def compute_tech_prerequisites(raw, competition_id):
    name = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    if not name:
        return []
    _require_competition(competition_id, "科技树前置节点")
    from apps.tech_tree.models import TechNode

    node = TechNode.objects.filter(competition_id=competition_id, name=name).first()
    if not node:
        return []
    seen = set()
    out = []
    for p in node.prerequisites.all():
        pn = p.prerequisite.name
        if pn and pn not in seen:
            seen.add(pn)
            out.append(pn)
    return out


def compute_tech_research_cost(raw, competition_id):
    name = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    if not name:
        return 0
    _require_competition(competition_id, "科技树研发费用")
    from apps.tech_tree.models import TechNode

    node = TechNode.objects.filter(competition_id=competition_id, name=name).first()
    return to_number(node.research_cost) if node else 0


def compute_route_distance(node_ids, competition_id, ctx_cache=None):
    """地图路程：给定有序节点 id 列表，求相邻节点间最短路径距离之和。"""
    if not node_ids or len(node_ids) < 2:
        return 0
    _require_competition(competition_id, "路程距离")
    from apps.maps.models import MapEdge

    cache = ctx_cache if ctx_cache is not None else {}
    adj = cache.get(competition_id)
    if adj is None:
        adj = {}
        for e in MapEdge.objects.filter(competition_id=competition_id).values("from_node_id", "to_node_id", "distance"):
            d = to_number(e["distance"])
            adj.setdefault(e["from_node_id"], []).append((e["to_node_id"], d))
            adj.setdefault(e["to_node_id"], []).append((e["from_node_id"], d))
        cache[competition_id] = adj
    total = 0
    for i in range(len(node_ids) - 1):
        dist = _dijkstra(adj, node_ids[i], node_ids[i + 1])
        if dist == math.inf:
            raise BusinessError(f"地图路程计算失败：节点 {node_ids[i]} 与 {node_ids[i + 1]} 之间无可达路径", code=400, status_code=400)
        total += dist
    return total


def compute_route_path_types(node_ids, competition_id):
    if not node_ids:
        return []
    _require_competition(competition_id, "路程路径类型")
    from apps.maps.models import MapEdge

    edges = MapEdge.objects.filter(
        competition_id=competition_id
    ).filter(
        models_q_from_to(node_ids)
    ).select_related("path_type").values("path_type__name")
    seen = set()
    out = []
    for e in edges:
        n = e["path_type__name"]
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def models_q_from_to(node_ids):
    """构造 MapEdge 的 from_node_id__in / to_node_id__in OR 查询。"""
    from django.db.models import Q
    return Q(from_node_id__in=node_ids) | Q(to_node_id__in=node_ids)


def _dijkstra(adj: dict, start: int, goal: int) -> float:
    if start == goal:
        return 0
    dist = {start: 0}
    visited = set()
    pq = [(0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == goal:
            return d
        if u in visited:
            continue
        visited.add(u)
        for to, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(to, math.inf):
                dist[to] = nd
                heapq.heappush(pq, (nd, to))
    return math.inf


# ==================== 产业字段现值（FIELD）读取 ====================

def _load_company_models():
    """懒加载公司/产业字段模型（兄弟应用可能尚未创建）。"""
    from apps.companies.models import CompanyFieldValue  # noqa: F401
    from apps.companies.models import Company
    return Company, CompanyFieldValue


def _load_industry_models():
    from apps.industry_types.models import IndustryField  # noqa: F401
    from apps.industry_types.models import IndustryType
    return IndustryType, IndustryField


def resolve_party_location_node_id(role: str, ctx: EvalCtx):
    party = ctx.parties.get(role) if ctx else None
    if not party or party.get("isHost") or party.get("companyId") is None:
        return None
    Company, CompanyFieldValue = _load_company_models()
    IndustryField, _ = _load_industry_models()
    company_id = party["companyId"]
    company = Company.objects.filter(pk=company_id).values("industry_type_id").first()
    if not company or not company.get("industry_type_id"):
        return None
    field = IndustryField.objects.filter(
        industry_type_id=company["industry_type_id"], field_key="location"
    ).values("id").first()
    if not field:
        return None
    cfv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=field["id"]
    ).values("value").first()
    node_name = cfv["value"] if cfv else None
    if node_name:
        try:
            parsed = json.loads(node_name)
            if isinstance(parsed, str):
                node_name = parsed
        except (ValueError, TypeError):
            pass
    if not node_name:
        return None
    from apps.maps.models import MapNode
    node = MapNode.objects.filter(competition_id=ctx.competition_id, name=node_name).values("id").first()
    return node["id"] if node else None


def read_company_field_value(role: str, field_key: str, ctx: EvalCtx):
    if not field_key:
        raise BusinessError("产业字段取值缺少 fieldKey", code=400, status_code=400)
    party = ctx.parties.get(role) if ctx else None
    if not party:
        raise BusinessError(f"产业字段取值失败：合同中不存在参与方「{role}」", code=400, status_code=400)
    if party.get("isHost") or party.get("companyId") is None:
        return 0
    # 快速路径：预加载缓存命中
    if ctx.field_cache is not None:
        hit = ctx.field_cache.get(f"{party['companyId']}:{field_key}")
        if hit:
            return parse_stored_field_value(hit.get("value") or hit.get("defaultValue"), hit.get("fieldType"))
    Company, CompanyFieldValue = _load_company_models()
    IndustryField, _ = _load_industry_models()
    company_id = party["companyId"]
    company = Company.objects.filter(pk=company_id).values("id", "name", "industry_type_id").first()
    if not company:
        raise BusinessError(f"公司不存在(#{company_id})", code=400, status_code=400)
    if not company.get("industry_type_id"):
        raise BusinessError(f"公司「{company['name']}」未设置产业类型，无法读取产业字段「{field_key}」", code=400, status_code=400)
    defn = IndustryField.objects.filter(
        industry_type_id=company["industry_type_id"], field_key=field_key
    ).values("id", "field_type", "default_value", "name").first()
    if not defn:
        raise BusinessError(f"公司「{company['name']}」所属产业下不存在字段「{field_key}」", code=400, status_code=400)
    cfv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=defn["id"]
    ).values("value").first()
    return parse_stored_field_value(cfv["value"] if cfv else defn["default_value"], defn["field_type"])


# ==================== eval_value_spec（数值来源分派） ====================

def eval_value_spec(spec: Any, inputs: dict, scope: dict | None = None, ctx: EvalCtx | None = None) -> Any:
    """统一的数值来源求值。scope 缺省时回退 inputs。"""
    if not spec or not isinstance(spec, dict):
        return to_number(spec)
    stype = spec.get("type")

    if stype == "CONST":
        v = spec.get("value")
        if isinstance(v, str):
            s = v.strip()
            if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
                try:
                    v = json.loads(s)
                except (ValueError, TypeError):
                    pass
        return None if v is None else v

    if stype == "INPUT":
        raw = inputs.get(spec.get("key"))
        aggregate = spec.get("aggregate")
        if aggregate == "CARBON":
            return compute_material_list_carbon(raw, ctx.competition_id if ctx else None)
        if aggregate == "ROUTE_DISTANCE":
            return compute_route_distance(to_number_array(raw), ctx.competition_id if ctx else None, ctx.cache if ctx else None)
        if aggregate == "ROUTE_PATH_TYPES":
            return compute_route_path_types(to_number_array(raw), ctx.competition_id if ctx else None)
        if aggregate == "PART_MATERIALS":
            return compute_part_materials(raw, ctx.competition_id if ctx else None)
        if aggregate == "PRODUCT_PARTS":
            return compute_product_parts(raw, ctx.competition_id if ctx else None)
        if aggregate == "PART_TECH_NODES":
            return compute_part_tech_nodes(raw, ctx.competition_id if ctx else None)
        if aggregate == "PRODUCT_TECH_NODES":
            return compute_product_tech_nodes(raw, ctx.competition_id if ctx else None)
        if aggregate == "PRICE":
            loc_node = None
            if spec.get("party") and ctx:
                loc_node = resolve_party_location_node_id(spec["party"], ctx)
            return compute_material_list_price(raw, ctx.competition_id if ctx else None, loc_node)
        if aggregate in ("MATERIAL_TOTAL_QTY", "PART_TOTAL_QTY", "PRODUCT_TOTAL_QTY", "FUEL_TOTAL_QTY"):
            return compute_total_qty(raw)
        if aggregate == "VEHICLE_TOTAL_PRICE":
            return compute_vehicle_total_price(raw, ctx.competition_id if ctx else None)
        if aggregate == "VEHICLE_CARGO":
            return compute_vehicle_total_cargo(raw, ctx.competition_id if ctx else None)
        if aggregate == "VEHICLE_FUEL_PER_KM":
            return compute_vehicle_total_fuel_per_km(raw, ctx.competition_id if ctx else None)
        if aggregate == "VEHICLE_CARBON":
            return compute_vehicle_total_carbon(raw, ctx.competition_id if ctx else None)
        if aggregate == "FUEL_TOTAL_PRICE":
            return compute_fuel_total_price(raw, ctx.competition_id if ctx else None)
        if aggregate == "WAREHOUSE_STORAGE":
            return compute_warehouse_total_storage(raw, ctx.competition_id if ctx else None)
        if aggregate == "WAREHOUSE_TOTAL_PRICE":
            return compute_warehouse_total_price(raw, ctx.competition_id if ctx else None)
        if aggregate and aggregate.startswith("INFRA_"):
            infra_field_map = {
                "INFRA_PRICE": "price", "INFRA_FOOTPRINT": "footprint",
                "INFRA_EMPLOYMENT": "employmentRateBonus",
                "INFRA_POPULATION": "populationBonus",
                "INFRA_HIGHQUALITY": "highQualityPopulationBonus",
                "INFRA_HAPPINESS": "happinessIndexBonus",
                "INFRA_INCOME": "perCapitaIncomeBonus",
                "INFRA_CARBON": "carbonReductionBonus",
                "INFRA_ACTIVATION_PRICE": "activationPrice",
            }
            return compute_infra_total(raw, ctx.competition_id if ctx else None, infra_field_map.get(aggregate, aggregate))
        if aggregate == "TECH_PREREQUISITES":
            return compute_tech_prerequisites(raw, ctx.competition_id if ctx else None)
        if aggregate == "TECH_RESEARCH_COST":
            return compute_tech_research_cost(raw, ctx.competition_id if ctx else None)
        return spec.get("default") if raw is None else raw

    if stype == "VAR":
        name = spec.get("name")
        if scope is not None and name in scope:
            return scope[name]
        v = inputs.get(name)
        return None if v is None else v

    if stype == "OP":
        args = [eval_value_spec(a, inputs, scope, ctx) for a in (spec.get("args") or [])]
        return apply_op(spec.get("op"), args, scope)

    if stype == "FORMULA":
        sandbox = {**inputs, **EXPR_HELPERS, **(scope or {})}
        try:
            return safe_evaluate(spec.get("expr"), sandbox)
        except _SafeExpressionError as e:
            raise BusinessError(f"公式求值失败: {e}", code=400, status_code=400)

    if stype == "ROUTE":
        ids = to_number_array(inputs.get(spec.get("routeRef")))
        return compute_route_distance(ids, ctx.competition_id if ctx else None, ctx.cache if ctx else None)

    if stype == "FIELD":
        return read_company_field_value(spec.get("party"), spec.get("fieldKey"), ctx)

    if stype == "INDUSTRY_IS":
        party = ctx.parties.get(spec.get("party")) if ctx else None
        if not party or party.get("isHost") or party.get("companyId") is None:
            return False
        Company, _ = _load_company_models()
        company = Company.objects.filter(pk=party["companyId"]).values("industry_type_id").first()
        return bool(company and company.get("industry_type_id") and company["industry_type_id"] == to_number(spec.get("industryTypeId")))

    if stype == "ENTITY":
        ent_id = to_number(inputs.get(spec.get("entityRef")))
        if not ent_id:
            return 0
        model_path = ENTITY_MODEL_NAMES.get(spec.get("entityType"))
        if not model_path:
            raise BusinessError(f"未知实体类型: {spec.get('entityType')}", code=400, status_code=400)
        from django.apps import apps as django_apps
        model_cls = django_apps.get_model(model_path)
        ent = model_cls.objects.filter(pk=ent_id).first()
        if not ent:
            raise BusinessError(f"实体不存在({spec.get('entityType')}#{ent_id})", code=400, status_code=400)
        v = to_number(getattr(ent, _camel_to_snake(spec.get("attribute") or ""), 0))
        if spec.get("multiplyByInput"):
            v = v * to_number(inputs.get(spec["multiplyByInput"]))
        return v

    return 0


# ==================== ContractEngine ====================

class ContractEngine:
    """合同引擎：执行 effects 改写公司产业字段并落账审计记录；预检条件；删除复原。"""

    def execute(self, contract) -> dict:
        """执行合同：解析 effects/conditions，在事务内改写公司产业字段并写审计日志。

        ``contract`` 需含：parties(JSON str)、inputs(JSON str)、contract_type（含
        effects/conditions/input_schema，JSON str）、competition_id、id。
        返回 ``{log, result}``，result = {logs, fields, checks}。
        """
        from django.db import transaction

        effects = self._safe_parse(contract["contract_type"]["effects"], "contractType.effects")
        conditions = self._safe_parse(contract["contract_type"].get("conditions") or "[]", "contractType.conditions")
        parties = self._safe_parse(contract["parties"], "contract.parties")
        inputs = self._safe_parse_obj(contract["inputs"], "contract.inputs")
        input_schema = self._safe_parse(contract["contract_type"].get("inputSchema") or "[]", "contractType.inputSchema")

        # 清单范围校验（基建/载具）：违规直接中止事务
        infra_err = self._validate_list_filters(input_schema, inputs, "infrastructureList", "allowedInfrastructures", "基建")
        if infra_err:
            raise BusinessError(f"基建清单范围校验未通过:\n{infra_err}", code=400, status_code=400)
        veh_err = self._validate_list_filters(input_schema, inputs, "vehicleList", "allowedVehicles", "载具")
        if veh_err:
            raise BusinessError(f"载具清单范围校验未通过:\n{veh_err}", code=400, status_code=400)

        party_map = {p["role"]: p for p in parties}
        log: list = []
        effect_rows: list = []
        result = {"logs": log, "fields": {}, "checks": []}
        scope: dict = {}
        ctx = EvalCtx(competition_id=contract.get("competitionId") or contract.get("competition_id"), parties=party_map)

        self._preload_field_cache(parties, ctx)

        def resolve_value(spec, sc=None):
            return eval_value_spec(spec, inputs, sc if sc is not None else scope, ctx)

        with transaction.atomic():
            if conditions:
                result["checks"] = self._run_conditions(conditions, party_map, inputs, scope, ctx, throw_on_fail=True)

            def apply_leaf(eff, sc):
                if eff.get("kind") != "FIELD":
                    raise BusinessError(f"未知效果类型: {eff.get('kind')}", code=400, status_code=400)
                party = self._resolve_party_company(eff.get("party"), party_map)
                if not party:
                    if not eff.get("party"):
                        raise BusinessError("合同「产业字段」效果未指定参与方：请在合同类型编辑器中为该效果节点连接「参与方」节点后再保存", code=400, status_code=400)
                    p = party_map.get(eff.get("party"))
                    if p and (p.get("isHost") or p.get("companyId") is None):
                        raise BusinessError(f"参与方「{eff.get('party')}」为主办方或未分配公司，无法操作产业字段", code=400, status_code=400)
                    raise BusinessError(f"合同不包含参与方角色「{eff.get('party')}」，无法定位目标公司（请核对合同类型的参与方配置）", code=400, status_code=400)
                field = self._resolve_industry_field(party["companyId"], eff["fieldKey"], ctx)
                new_value = resolve_value(eff.get("value"), sc)
                if eff.get("value2"):
                    v2 = resolve_value(eff.get("value2"), sc)
                    new_value = combine_values(new_value, v2, eff.get("valueOp") or "ADD", field["field_type"])
                current = self._read_current_field_value(party["companyId"], field["id"])
                config = parse_field_config(field.get("config"))
                applied = apply_field_effect(current, field["field_type"], config, eff["op"], new_value)
                self._write_field_value(party["companyId"], field["id"], applied["store"])
                log.append({
                    "kind": "FIELD",
                    "companyId": party["companyId"],
                    "fieldKey": eff["fieldKey"],
                    "fieldName": field["name"],
                    "op": eff["op"],
                    "value": new_value,
                    "before": applied["before"],
                    "after": applied["after"],
                })
                result["fields"][f"{party['companyId']}:{eff['fieldKey']}"] = applied["after"]
                effect_rows.append({
                    "contract_id": contract.get("id"),
                    "company_id": party["companyId"],
                    "industry_field_id": field["id"],
                    "field_key": eff["fieldKey"],
                    "field_name": field["name"],
                    "op": eff["op"],
                    "value_raw": json.dumps(new_value, ensure_ascii=False),
                    "before_raw": json.dumps(applied["before"], ensure_ascii=False),
                    "after_raw": json.dumps(applied["after"], ensure_ascii=False),
                })

            def apply_effect(eff, sc):
                if not eff or not isinstance(eff, dict):
                    return
                kind = eff.get("kind")
                if kind == "IF":
                    cond_val = resolve_value(eff.get("cond"), sc)
                    branch = (eff.get("then") or []) if is_truthy(cond_val) else (eff.get("else") or [])
                    for sub in branch:
                        apply_effect(sub, sc)
                elif kind == "FOREACH":
                    arr = resolve_value(eff.get("items"), sc)
                    lst = arr if isinstance(arr, list) else []
                    var_name = eff.get("var") or "item"
                    for el in lst:
                        child_scope = {**sc, var_name: el}
                        for sub in (eff.get("body") or []):
                            apply_effect(sub, child_scope)
                elif kind == "ASSIGN":
                    sc[eff["name"]] = resolve_value(eff.get("value"), sc)
                else:
                    apply_leaf(eff, sc)

            for eff in effects:
                apply_effect(eff, scope)

            if effect_rows:
                self._bulk_create_effects(effect_rows)

        return {"log": log, "result": result}

    def revert_contract(self, contract) -> None:
        """复原某合同对产业字段的修改（事件溯源式重放）。

        调用方须在本合同记录被删除（级联清空 ContractFieldEffect）之前调用。
        """
        from apps.contracts.models import ContractFieldEffect
        IndustryField, _ = _load_industry_models()
        Company, CompanyFieldValue = _load_company_models()

        deleted_rows = list(ContractFieldEffect.objects.filter(contract_id=contract["id"]).values(
            "id", "company_id", "industry_field_id", "field_key", "op", "value_raw", "before_raw"
        ))
        if not deleted_rows:
            return

        # 去重受影响字段
        field_map = {}
        for r in deleted_rows:
            field_map[f"{r['company_id']}:{r['industry_field_id']}"] = (r["company_id"], r["industry_field_id"])

        affected_field_ids = list({v[1] for v in field_map.values()})
        all_fields = {f["id"]: f for f in IndustryField.objects.filter(id__in=affected_field_ids).values("id", "field_type", "config")}
        affected_pairs = list(field_map.values())

        # 其余已执行合同对该字段的增量（按 executed_at, id 顺序）
        from apps.contracts.models import Contract
        remaining = list(
            ContractFieldEffect.objects.filter(
                contract__executed_at__isnull=False
            )
        )
        # 构造 OR 查询：每对 (company_id, industry_field_id)
        from django.db.models import Q
        q = Q()
        for cid, fid in affected_pairs:
            q |= Q(company_id=cid, industry_field_id=fid)
        remaining = list(
            ContractFieldEffect.objects.filter(q).exclude(contract_id=contract["id"]).select_related("contract").order_by("contract__executed_at", "id").values(
                "id", "company_id", "industry_field_id", "op", "value_raw", "before_raw", "contract__executed_at", "contract__created_at"
            )
        )
        remaining_by_key: dict = {}
        for r in remaining:
            remaining_by_key.setdefault(f"{r['company_id']}:{r['industry_field_id']}", []).append(r)

        contract_executed_at = contract.get("executedAt") or contract.get("executed_at") or contract.get("createdAt") or contract.get("created_at")

        for cid, fid in field_map.values():
            field = all_fields.get(fid)
            if not field:
                continue
            ftype = field["field_type"]
            config = parse_field_config(field.get("config"))

            deleted_for_field = [r for r in deleted_rows if r["company_id"] == cid and r["industry_field_id"] == fid]
            rem = remaining_by_key.get(f"{cid}:{fid}", [])

            # 基线 = 全部效果（含被删合同）中最早者的 beforeRaw
            all_for_field = (
                [{"ex": _row_time(r, contract_executed_at), "row": r} for r in rem] +
                [{"ex": _to_timestamp(contract_executed_at), "row": r} for r in deleted_for_field]
            )
            all_for_field.sort(key=lambda x: (x["ex"] if x["ex"] else 0, x["row"]["id"]))
            value = parse_json_value(all_for_field[0]["row"]["before_raw"])

            # 按序重放其余已执行合同的增量
            for r in rem:
                delta = parse_json_value(r["value_raw"])
                value = apply_field_effect(json.dumps(value, ensure_ascii=False), ftype, config, r["op"], delta)["after"]

            self._write_field_value(cid, fid, json.dumps(value, ensure_ascii=False))

    def precheck(self, contract) -> list:
        """预检：仅评估前置检查并返回结果，不落账、不改写任何数据。"""
        conditions = self._safe_parse(contract["contract_type"].get("conditions") or "[]", "contractType.conditions")
        parties = self._safe_parse(contract["parties"], "contract.parties")
        inputs = self._safe_parse_obj(contract["inputs"], "contract.inputs")
        party_map = {p["role"]: p for p in parties}
        ctx = EvalCtx(competition_id=contract.get("competitionId") or contract.get("competition_id"), parties=party_map)
        input_schema = self._safe_parse(contract["contract_type"].get("inputSchema") or "[]", "contractType.inputSchema")
        checks = self._run_conditions(conditions, party_map, inputs, {}, ctx, throw_on_fail=False)
        infra_err = self._validate_list_filters(input_schema, inputs, "infrastructureList", "allowedInfrastructures", "基建")
        if infra_err:
            checks.append({"kind": "INFRA_LIST_FILTER", "party": "", "label": "基建范围校验", "passed": False, "detail": infra_err, "customError": True})
        veh_err = self._validate_list_filters(input_schema, inputs, "vehicleList", "allowedVehicles", "载具")
        if veh_err:
            checks.append({"kind": "VEHICLE_LIST_FILTER", "party": "", "label": "载具范围校验", "passed": False, "detail": veh_err, "customError": True})
        return checks

    # ---------- 前置检查 ----------

    def _run_conditions(self, conditions, party_map, inputs, scope, ctx, throw_on_fail=False) -> list:
        results: list = []

        def resolve_party_company(role):
            pp = party_map.get(role)
            if not pp or pp.get("isHost") or pp.get("companyId") is None:
                return None
            return pp

        def resolve_value(spec):
            return eval_value_spec(spec, inputs, scope, ctx)

        for c in conditions:
            label = c.get("label") or cond_kind_label(c["kind"])
            # 控制流：IF 分支未触发则跳过
            branch = c.get("branch")
            if branch and branch.get("when") in ("then", "else"):
                try:
                    cond_val = resolve_value(branch.get("cond"))
                    branch_ok = (is_truthy(cond_val) and branch["when"] == "then") or ((not is_truthy(cond_val)) and branch["when"] == "else")
                except Exception:
                    branch_ok = False
                if not branch_ok:
                    results.append({"kind": c["kind"], "party": c.get("party", ""), "label": label, "passed": True, "detail": f"已跳过：所属 IF 分支（{'真分支' if branch['when'] == 'then' else '假分支'}）未触发", "skipped": True})
                    continue

            em = (c.get("errorMessage") or "").strip()
            # VALUE_COMPARE / DICT_COMPARE / LIST_COMPARE 无参与方概念
            no_party = c["kind"] in ("VALUE_COMPARE", "DICT_COMPARE", "LIST_COMPARE")
            party = None if no_party else resolve_party_company(c.get("party") or "")
            if not no_party and not party:
                results.append({"kind": c["kind"], "party": c.get("party", ""), "label": label, "passed": False, "detail": em or "该参与方不是公司账户，无法检查", "customError": bool(em)})
                continue

            company_id = party["companyId"] if party else None
            passed = True
            detail = ""
            actual = None
            expected = None
            kind = c["kind"]

            if kind == "VALUE_COMPARE":
                v1 = resolve_value(c.get("value1"))
                v2 = resolve_value(c.get("value2"))
                op = c.get("op") or "GTE"
                if op == "CONTAINS":
                    ok = (any(deep_equal(i, v2) for i in v1) if isinstance(v1, list)
                          else (v2 in v1 if isinstance(v1, dict) and v2 in v1
                                else (any(deep_equal(x, v2) for x in v1.values()) if isinstance(v1, dict) else False)))
                elif op == "HAS_KEY":
                    ok = isinstance(v1, dict) and v2 in v1
                elif op == "EQ":
                    ok = deep_equal(v1, v2)
                else:
                    ok = compare_op(to_number(v1), op, to_number(v2))
                passed = ok
                actual = v1
                expected = v2
                op_label = COMPARE_OP_LABEL.get(op, op)
                detail = f"值1 {op_label} 值2：{'通过' if ok else '未通过'}（{json.dumps(actual, ensure_ascii=False)} {op_label} {json.dumps(expected, ensure_ascii=False)}）"

            elif kind == "DICT_COMPARE":
                v1 = resolve_value(c.get("value1"))
                v2 = resolve_value(c.get("value2"))
                op = c.get("op") or "GTE"
                actual, expected = v1, v2
                if op not in ("GTE", "GT", "EQ"):
                    passed = False
                    detail = f"DICT_COMPARE 仅支持 ≥(GTE) / >(GT) / =(EQ) 三种算子，当前算子无效：{op}"
                elif not (isinstance(v1, dict) and isinstance(v2, dict)):
                    passed = False
                    detail = f"DICT_COMPARE 要求两个操作数均为字典，实际：值1={'字典' if isinstance(v1, dict) else json.dumps(v1, ensure_ascii=False)}，值2={'字典' if isinstance(v2, dict) else json.dumps(v2, ensure_ascii=False)}"
                else:
                    keys1, keys2 = list(v1.keys()), list(v2.keys())
                    missing = [k for k in keys1 if k not in keys2]
                    if missing:
                        passed = False
                        detail = f"前提不满足：值一的键必须全部存在于值二（值二缺失键：{', '.join(missing)}）"
                    else:
                        op_label = COMPARE_OP_LABEL.get(op, op)
                        fails = []
                        for k in keys1:
                            a, b = to_number(v1[k]), to_number(v2[k])
                            if not compare_op(a, op, b):
                                fails.append(f"「{k}」：{a} {op_label} {b} 不成立")
                        passed = len(fails) == 0
                        detail = (f"字典逐项比较通过（{len(keys1)} 个共有键均满足 {op_label}）" if passed else f"字典逐项比较未通过：{'；'.join(fails)}")

            elif kind == "LIST_COMPARE":
                v1 = resolve_value(c.get("value1"))
                v2 = resolve_value(c.get("value2"))
                op = c.get("op") or "GTE"
                actual, expected = v1, v2
                if op not in ("ELEMENT_EQ", "CONTAINS", "GT", "GTE", "EQ"):
                    passed = False
                    detail = f"LIST_COMPARE 仅支持 元素相等(ELEMENT_EQ) / 被包含(CONTAINS) / >(GT) / ≥(GTE) / =(EQ) 五种算子，当前算子无效：{op}"
                elif not (isinstance(v1, list) and isinstance(v2, list)):
                    passed = False
                    detail = f"LIST_COMPARE 要求两个操作数均为列表，实际：值1={'列表' if isinstance(v1, list) else json.dumps(v1, ensure_ascii=False)}，值2={'列表' if isinstance(v2, list) else json.dumps(v2, ensure_ascii=False)}"
                else:
                    op_label = COMPARE_OP_LABEL.get(op, op)
                    a1, a2 = v1, v2

                    def set_has(bigger, smaller):
                        return all(any(deep_equal(y, x) for y in bigger) for x in smaller)

                    set_equal = set_has(a1, a2) and set_has(a2, a1)
                    if op == "ELEMENT_EQ":
                        passed = len(a1) == len(a2) and all(deep_equal(x, a2[i]) for i, x in enumerate(a1))
                        detail = (f"列表元素相等（长度 {len(a1)}，逐项一致）" if passed else f"列表元素不相等（长度 值1={len(a1)} / 值2={len(a2)}，或存在位置不一致的元素）")
                    elif op == "CONTAINS":
                        missing = [x for x in a1 if not any(deep_equal(y, x) for y in a2)]
                        passed = len(missing) == 0
                        detail = (f"值一被包含于值二（值一 {len(a1)} 个元素均能在值二中找到）" if passed else f"值一未被完全包含于值二，缺失元素：{json.dumps(missing, ensure_ascii=False)}")
                    elif op == "EQ":
                        passed = set_equal
                        detail = (f"两列表元素集合相同（{len(a1)} 个元素一致）" if passed else f"两列表元素集合不同（值1={len(a1)} 个 / 值2={len(a2)} 个，存在一方特有元素）")
                    elif op == "GTE":
                        passed = set_has(a1, a2)
                        detail = (f"值一包含值二（值二 {len(a2)} 个元素均能在值一中找到）" if passed else f"值一未包含值二，值二特有元素：{json.dumps([y for y in a2 if not any(deep_equal(x, y) for x in a1)], ensure_ascii=False)}")
                    else:  # GT
                        passed = set_has(a1, a2) and not set_equal
                        detail = (f"值一真包含值二（值二 {len(a2)} 个元素均能在值一中找到，且值一元素更多）" if passed else "值一未真包含值二（需 值二 ⊆ 值一 且 值一元素更多）")

            elif kind == "FIELD_COMPARE":
                field_key = c.get("fieldKey")
                Company, _ = _load_company_models()
                IndustryField, _ = _load_industry_models()
                company = Company.objects.filter(pk=company_id).values("industry_type_id", "name").first()
                if not company or not company.get("industry_type_id"):
                    passed = False
                    detail = f"公司未设置产业类型，无法检查字段「{field_key}」"
                else:
                    defn = IndustryField.objects.filter(industry_type_id=company["industry_type_id"], field_key=field_key).values("id", "field_type", "config", "name", "default_value").first()
                    if not defn:
                        passed = False
                        detail = f"该产业下不存在字段「{field_key}」"
                    else:
                        CompanyFieldValue = _load_company_models()[1]
                        cfv = CompanyFieldValue.objects.filter(company_id=company_id, industry_field_id=defn["id"]).values("value").first()
                        is_structured = defn["field_type"] in ("DICTIONARY", "LIST")
                        if is_structured:
                            expected = resolve_value(c.get("value"))
                            r = compare_field(cfv["value"] if cfv else None, defn["field_type"], parse_field_config(defn.get("config")), c.get("op") or "LEN_GTE", expected)
                            passed = r["passed"]
                            actual = r["actual"]
                            expected = r["expected"]
                            detail = f"{defn['name']}({field_key}) {r['detail']}"
                        else:
                            actual = to_number((cfv["value"] if cfv else None) or defn.get("default_value") or 0)
                            expected = to_number(resolve_value(c.get("value")))
                            passed = compare_op(actual, c.get("op") or "GTE", expected)
                            detail = f"{defn['name']}({field_key})={actual} {c.get('op') or 'GTE'} {expected}"

            elif kind == "INDUSTRY_IS":
                Company, _ = _load_company_models()
                IndustryField, IndustryType = _load_industry_models()
                company = Company.objects.filter(pk=company_id).values("industry_type_id").first()
                actual = "未设置"
                it = IndustryType.objects.filter(pk=to_number(c.get("industryTypeId")) or 0).values("name").first()
                expected = it["name"] if it else f"#{c.get('industryTypeId')}"
                passed = bool(company and company.get("industry_type_id") and company["industry_type_id"] == to_number(c.get("industryTypeId")))
                detail = f"产业类型={actual}，要求={expected}"

            else:
                results.append({"kind": c["kind"], "party": c.get("party", ""), "label": label, "passed": False, "detail": em or f"未知检查类型: {c['kind']}"})
                continue

            if not passed and em:
                detail = em
            results.append({"kind": c["kind"], "party": c.get("party", ""), "label": label, "passed": passed, "actual": actual, "expected": expected, "detail": detail, "customError": bool(em and detail == em)})

        if throw_on_fail and any(not r["passed"] for r in results):
            failed = "\n".join(
                f"• {r['detail']}" if r.get('customError')
                else f"• {r['label']}: {r['detail']}"
                for r in results if not r["passed"]
            )
            raise BusinessError(f"合同前置检查未通过:\n{failed}", code=400, status_code=400)
        return results

    # ---------- 字段定位 / 读写 ----------

    def _resolve_party_company(self, role, party_map):
        p = party_map.get(role)
        if not p or p.get("isHost") or p.get("companyId") is None:
            return None
        return p

    def _resolve_industry_field(self, company_id, field_key, ctx: EvalCtx):
        IndustryField, _ = _load_industry_models()
        Company, _ = _load_company_models()
        # 快速路径：field_cache 已预加载 company 信息
        if ctx.field_cache is not None:
            entry = ctx.field_cache.get(f"{company_id}:{field_key}")
            if entry is None:
                # 取该公司任意条目获取 industry_type_id
                for k, v in ctx.field_cache.items():
                    if k.startswith(f"{company_id}:") and v.get("industryTypeId"):
                        entry = v
                        break
            if entry and entry.get("industryTypeId"):
                field = IndustryField.objects.filter(industry_type_id=entry["industryTypeId"], field_key=field_key).values("id", "field_type", "config", "name", "default_value").first()
                if not field:
                    raise BusinessError(f"公司「{entry.get('companyName')}」所属产业下不存在字段「{field_key}」", code=400, status_code=400)
                return field
        company = Company.objects.filter(pk=company_id).values("name", "industry_type_id").first()
        if not company:
            raise BusinessError(f"公司不存在(#{company_id})", code=400, status_code=400)
        if not company.get("industry_type_id"):
            raise BusinessError(f"公司「{company['name']}」未设置产业类型，无法操作产业字段", code=400, status_code=400)
        field = IndustryField.objects.filter(industry_type_id=company["industry_type_id"], field_key=field_key).values("id", "field_type", "config", "name", "default_value").first()
        if not field:
            raise BusinessError(f"公司「{company['name']}」所属产业下不存在字段「{field_key}」", code=400, status_code=400)
        return field

    def _read_current_field_value(self, company_id, industry_field_id):
        CompanyFieldValue = _load_company_models()[1]
        cfv = CompanyFieldValue.objects.filter(company_id=company_id, industry_field_id=industry_field_id).values("value").first()
        return cfv["value"] if cfv else None

    def _write_field_value(self, company_id, industry_field_id, store_value):
        """直接写 CompanyFieldValue（乐观锁由调用方事务保证）。"""
        CompanyFieldValue = _load_company_models()[1]
        obj, _ = CompanyFieldValue.objects.update_or_create(
            company_id=company_id, industry_field_id=industry_field_id,
            defaults={"value": store_value},
        )
        return obj

    def _bulk_create_effects(self, rows):
        from apps.contracts.models import ContractFieldEffect
        ContractFieldEffect.objects.bulk_create([ContractFieldEffect(**r) for r in rows])

    def _preload_field_cache(self, parties, ctx: EvalCtx):
        """批量预加载参与方公司的产业字段值，避免逐条 N+1 查询。"""
        try:
            Company, CompanyFieldValue = _load_company_models()
            IndustryField, _ = _load_industry_models()
        except Exception:
            # 兄弟应用尚未创建：跳过预加载，FIELD 走原始路径报错
            return
        company_ids = [p["companyId"] for p in parties if not p.get("isHost") and p.get("companyId") is not None]
        if not company_ids:
            return
        companies = {c["id"]: c for c in Company.objects.filter(id__in=company_ids).values("id", "name", "industry_type_id")}
        type_ids = list({c["industry_type_id"] for c in companies.values() if c.get("industry_type_id")})
        fields = list(IndustryField.objects.filter(industry_type_id__in=type_ids).values("id", "field_key", "field_type", "default_value", "industry_type_id", "name")) if type_ids else []
        field_by_id = {f["id"]: f for f in fields}
        fvs = list(CompanyFieldValue.objects.filter(company_id__in=company_ids).values("company_id", "industry_field_id", "value"))
        cache: dict = {}
        for c in companies.values():
            if not c.get("industry_type_id"):
                continue
            for f in fields:
                if f["industry_type_id"] != c["industry_type_id"]:
                    continue
                cache[f"{c['id']}:{f['field_key']}"] = {
                    "value": None, "fieldType": f["field_type"], "defaultValue": f["default_value"],
                    "companyName": c["name"], "industryTypeId": c["industry_type_id"],
                }
        for fv in fvs:
            f = field_by_id.get(fv["industry_field_id"])
            if not f:
                continue
            key = f"{fv['company_id']}:{f['field_key']}"
            entry = cache.get(key)
            if entry:
                entry["value"] = fv["value"]
        ctx.field_cache = cache

    # ---------- 清单范围校验 ----------

    def _validate_list_filters(self, input_schema, inputs, filter_type, allowed_field, entity_label):
        if not isinstance(input_schema, list):
            return None
        violations = []
        for f in input_schema:
            if not f or f.get("type") != filter_type:
                continue
            allowed = f.get(allowed_field)
            if not isinstance(allowed, list) or not allowed:
                continue
            allowed_set = {str(x) for x in allowed}
            raw = (inputs or {}).get(f.get("key"))
            if not isinstance(raw, dict):
                continue
            forbidden = [name for name in raw.keys() if name not in allowed_set]
            if forbidden:
                violations.append(f"{entity_label}清单「{f.get('label') or f.get('key')}」包含未授权的{entity_label}：{'、'.join(forbidden)}（仅允许：{'、'.join(allowed)}）")
        return "\n".join(violations) if violations else None

    # ---------- JSON 解析 ----------

    def _safe_parse(self, raw, label):
        return safe_parse(raw, label)

    def _safe_parse_obj(self, raw, label):
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError) as e:
            raise BusinessError(f"{label} 不是合法 JSON: {e}", code=400, status_code=400)


def _to_timestamp(dt) -> float:
    if dt is None:
        return 0
    if isinstance(dt, str):
        return 0
    try:
        return dt.timestamp()
    except (AttributeError, ValueError, OSError):
        return 0


def _row_time(row, fallback):
    """取 remaining 行的时间戳：优先 contract.executedAt，缺省 createdAt。"""
    ex = row.get("contract__executed_at") or row.get("contract__created_at") or fallback
    return _to_timestamp(ex)
