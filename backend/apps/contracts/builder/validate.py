"""静态体检：把「运行期才会暴露的静默错误」提前到构建期。

为什么需要它
------------
引擎在数据解析不到时**一律静默降级**（这是刻意的业务规则，不是 bug）：

| 缺什么 | 引擎行为 | 代码位置 |
| --- | --- | --- |
| 聚合清单里的名字不存在 | 该项按 **0** 计入 | `engine.py:1365` |
| 原料在该地点没有报价 | 回退**市场均价** | `engine.py:1248` |
| 指定了参与方但公司没填 `location` | `location_node_id=None` → 回退均价 | `engine.py:1654` |
| 公司产业下没有该字段 | **抛错**（这条会报） | `engine.py:2264` |
| 公式引用不存在的输入项 | 取到 `None` → 参与运算按 0 | `engine.py:1780` |

于是「合同配置错了」的典型表现不是报错，而是**数字不对**。本模块把这些检查
全部提前，且**完全不碰引擎、不写数据库**。

四类检查
--------
- **E 引用可达**：效果/检查/值源引用到的输入项、参与方、变量是否已声明；
- **T 类型匹配**：具名效果 × 字段类型、清单类型 × 聚合口径；
- **S 静默回退**：会触发引擎「静默降级」的配置（地点价、缺 location、缺默认值）；
- **I 语法可执行**：公式表达式里的 `inputs[...]` / `scope[...]` 是否指向真实存在的键。

严重级别
--------
- `error`  ：必然出错（引擎会拒绝或结果必错）——**必须在导入前修掉**；
- `warning`：会静默降级成另一个口径（结果可能不符合预期）；
- `info`   ：提示，供人工确认。
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Iterable, Iterator, Sequence

from .effects import EFFECT_KINDS, KINDS_BY_FIELD_TYPE
from .errors import BuildError
from .values import ENTITY_ATTRIBUTES, ENTITY_TYPE_LABEL, INPUT_TYPES, LIST_INPUT_ENTITY, LIST_INPUT_TYPES

ERROR = "error"
WARNING = "warning"
INFO = "info"

_LEVEL_LABEL = {ERROR: "阻断", WARNING: "提醒", INFO: "提示"}


@dataclasses.dataclass
class Finding:
    """一条体检结论。"""

    level: str
    code: str
    message: str
    where: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def format(self) -> str:
        head = f"[{_LEVEL_LABEL.get(self.level, self.level)}]"
        spot = f"{self.where}：" if self.where else ""
        tail = f"\n        ↳ {self.hint}" if self.hint else ""
        return f"{head} {spot}{self.message}{tail}"


@dataclasses.dataclass
class Report:
    """一份合同类型的体检报告。"""

    key: str
    name: str
    findings: list[Finding] = dataclasses.field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARNING]

    @property
    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.level == INFO]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, code: str, message: str, *, where: str = "", hint: str = "") -> None:
        self.findings.append(Finding(level, code, message, where, hint))

    def extend(self, others: Iterable[Finding]) -> None:
        self.findings.extend(others)

    def summary(self) -> str:
        if not self.findings:
            return "无问题"
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} 处阻断")
        if self.warnings:
            parts.append(f"{len(self.warnings)} 处提醒")
        if self.infos:
            parts.append(f"{len(self.infos)} 处提示")
        return "、".join(parts)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary(),
            "errorCount": len(self.errors),
            "warningCount": len(self.warnings),
            "infoCount": len(self.infos),
            "findings": [f.to_dict() for f in self.findings],
        }

    def render(self) -> str:
        lines = [f"{self.name}（{self.key}）  状态：{self.summary()}"]
        for f in self.findings:
            lines.append("  " + f.format())
        return "\n".join(lines)


# ==================== 字段类型索引 ====================

# 引擎的字段类型枚举
FIELD_TYPES = ("STRING", "NUMBER", "BOOLEAN", "DICTIONARY", "LIST")

# 聚合端点 → 允许的输入项类型（None 表示不限制）。
# 这是「清单类型 × 聚合口径」的唯一真源；映射错配在引擎里会静默算出 0。
AGGREGATE_INPUT_TYPES: dict[str, tuple[str, ...] | None] = {
    "CARBON": ("materialList",),
    "PRICE": ("materialList",),
    "ROUTE_DISTANCE": ("nodeRoute",),
    "ROUTE_PATH_TYPES": ("nodeRoute",),
    "ROUTE_START_NODE_NAME": ("nodeRoute",),
    "ROUTE_END_NODE_NAME": ("nodeRoute",),
    "PART_MATERIALS": ("partList",),
    "PART_MATERIAL_TOTAL_QTY": ("partList",),
    "PART_TECH_NODES": ("partList", "techNode"),
    "PRODUCT_PARTS": ("productList",),
    "PRODUCT_PARTS_TOTAL_QTY": ("productList",),
    "PRODUCT_TECH_NODES": ("productList",),
    "MATERIAL_TOTAL_QTY": ("materialList", "partList", "productList", "fuelList"),
    "PART_TOTAL_QTY": ("materialList", "partList", "productList", "fuelList"),
    "PRODUCT_TOTAL_QTY": ("materialList", "partList", "productList", "fuelList"),
    "FUEL_TOTAL_QTY": ("fuelList",),
    "FUEL_TOTAL_PRICE": ("fuelList",),
    "VEHICLE_TOTAL_PRICE": ("vehicleList",),
    "VEHICLE_CARGO": ("vehicleList",),
    "VEHICLE_FUEL_PER_KM": ("vehicleList",),
    "VEHICLE_CARBON": ("vehicleList",),
    "WAREHOUSE_STORAGE": ("warehouseList",),
    "WAREHOUSE_TOTAL_PRICE": ("warehouseList",),
    "TECH_PREREQUISITES": ("techNode", "partList", "productList"),
    "TECH_RESEARCH_COST": ("techNode",),
    "INFRA_PRICE": ("infrastructureList",),
    "INFRA_FOOTPRINT": ("infrastructureList",),
    "INFRA_EMPLOYMENT": ("infrastructureList",),
    "INFRA_POPULATION": ("infrastructureList",),
    "INFRA_HIGHQUALITY": ("infrastructureList",),
    "INFRA_HAPPINESS": ("infrastructureList",),
    "INFRA_INCOME": ("infrastructureList",),
    "INFRA_CARBON": ("infrastructureList",),
    "INFRA_ACTIVATION_PRICE": ("infrastructureList",),
}

# 公式里对输入项/变量的引用。
# 引擎的 FORMULA 沙箱是 `{**inputs, **EXPR_HELPERS, **scope}`（engine.py:1788）——
# 输入项与循环变量都是**顶层名字**，没有 inputs / scope 这两个字典对象。
# 因此：
#   ✓ mats[row]         ✓ get(mats, row)      ✗ inputs['mats']  ✗ scope['row']
# 下面的正则抓「像 inputs[...] / scope[...] 的写法」，作为常见误用给出精确提示。
_INPUT_REF_RE = re.compile(r"inputs\s*\[")
_SCOPE_REF_RE = re.compile(r"scope\s*\[")
# 顶层裸标识符（用于校验输入项/变量是否真实存在）
_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
#: 合法标识符：公式与 keys(...) 都要求输入项 key 能直接当名字写
_VALID_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _formula_name_pool() -> frozenset[str]:
    """公式里可以出现的「非输入项名字」集合。

    从引擎**动态派生**（`EXPR_HELPERS` + `safe_evaluate` 的内置函数与常量），
    不在本库硬编码——否则引擎加了函数、本库就会误报「未知名字」。
    取不到时退化成一份最小集合，保证校验不会因此崩掉。
    """
    names: set[str] = {
        # Python 字面量与语法关键字
        "True", "False", "None", "and", "or", "not", "in", "if", "else",
    }
    try:
        from apps.contracts.engine import EXPR_HELPERS, _BUILTIN_CONSTS, _BUILTIN_FUNCS

        names.update(str(k) for k in EXPR_HELPERS)
        names.update(str(k) for k in _BUILTIN_FUNCS)
        names.update(str(k) for k in _BUILTIN_CONSTS)
    except Exception:  # noqa: BLE001 - 引擎不可用时退化为最小集合
        names.update(
            {"IF", "AND", "OR", "NOT", "len", "get", "keys", "values", "has",
             "hasKey", "merge", "unique", "flatten", "join", "sumOf", "contains",
             "push", "concat", "indexIn"}
        )
    return frozenset(names)
#: 公式里可以出现的非输入项名字（从引擎动态派生，见 _formula_name_pool）。
#: **必须惰性求值**：脚本可能在 `django.setup()` 之前就 `import apps.contracts.builder`
#: （示例脚本为了能被 `manage.py` 与 `python xxx.py` 两种方式运行，必须提前 import），
#: 那时 `apps.contracts.engine` 还不可导入，模块级求值会退化成最小集合，
#: 导致 `exp` 这类数学函数被误判为「未知名字」。
_FORMULA_NAME_POOL_CACHE: frozenset[str] | None = None


def _formula_name_pool_cached() -> frozenset[str]:
    global _FORMULA_NAME_POOL_CACHE
    if _FORMULA_NAME_POOL_CACHE is None:
        _FORMULA_NAME_POOL_CACHE = _formula_name_pool()
    return _FORMULA_NAME_POOL_CACHE

#: 引擎 `eval_value_spec` 认识的全部值源类型
_VALUE_SPEC_TYPES: frozenset[str] = frozenset(
    {
        "CONST",
        "INPUT",
        "VAR",
        "OP",
        "FORMULA",
        "ROUTE",
        "FIELD",
        "INDUSTRY_IS",
        "PARTY_COMPANY_NAME",
        "ENTITY",
    }
)


# ==================== 入口 ====================


def validate_payload(
    payload: dict,
    *,
    key: str = "",
    name: str = "",
    declared_field_types: dict[str, dict[str, str]] | None = None,
    all_field_keys: set[str] | None = None,
    industry_names: dict[Any, str] | None = None,
    strict_effect_types: bool = False,
) -> Report:
    """对编译产物做全套静态检查。

    参数：

    - `payload`：`ContractType.build()` 的产物（四个数组）；
    - `declared_field_types`：`{产业类型 id: {fieldKey: fieldType}}`。
      传了才能校验「字段是否存在于参与方所属产业」与「效果 × 字段类型」。
    - `all_field_keys`：库中**所有**产业字段 key 的并集。用来发现「这个字段任何产业
      都没有」——比逐个产业比对更早、更准地暴露拼写错误。
    - `strict_effect_types`：是否按「各产业类型的字段类型**必须逐一对齐**」来判定。
      由于合同模板是全局的、会被多个产业类型复用，默认只做
      「NUMBER 字段与数值效果、LIST 字段与列表效果」这类**明确矛盾**的判定。
    """
    report = Report(key=key, name=name)
    parties = _party_map(payload, report)
    var_scope = _declared_vars(payload)

    inputs = {i.get("key"): i for i in payload.get("inputSchema") or [] if isinstance(i, dict)}
    _check_inputs(payload, inputs, report)
    _check_conditions(payload, parties, inputs, var_scope, report)
    _check_effects(payload, parties, inputs, var_scope, report, root=True)
    _check_values(payload, inputs, var_scope, parties, report)
    _check_fields_against_industry(
        payload,
        parties,
        declared_field_types or {},
        report,
        strict=strict_effect_types,
        industry_names=industry_names,
    )
    if all_field_keys is not None:
        _check_fields_exist_anywhere(payload, all_field_keys, report)
    return report


def _check_fields_exist_anywhere(payload: dict, all_field_keys: set[str], report: Report) -> None:
    """效果/检查引用到的字段 key，是否至少存在于某一个产业类型下。

    这类问题比「某产业缺字段」更严重：任何公司执行到这条效果都会报
    「所属产业下不存在字段」，通常是 key 拼错或字段还没建。
    """
    used: dict[str, list[str]] = {}

    def note(field_key: str, where: str) -> None:
        if not field_key:
            return
        used.setdefault(field_key, [])
        if where not in used[field_key]:
            used[field_key].append(where)

    def walk(effects: Sequence[Any], where: str) -> None:
        for i, eff in enumerate(effects or []):
            if not isinstance(eff, dict):
                continue
            spot = f"{where}[{i}]"
            kind = eff.get("kind")
            if kind == "FIELD":
                note(str(eff.get("fieldKey") or ""), spot)
            elif kind == "IF":
                walk(eff.get("then") or [], f"{spot}.then")
                walk(eff.get("else") or [], f"{spot}.else")
            elif kind == "FOREACH":
                walk(eff.get("body") or [], f"{spot}.body")

    walk(payload.get("effects") or [], "效果")
    for i, cond in enumerate(payload.get("conditions") or []):
        if isinstance(cond, dict) and cond.get("kind") == "FIELD_COMPARE":
            note(str(cond.get("fieldKey") or ""), f"检查[{i}]")

    missing = sorted(k for k in used if k and k not in all_field_keys)
    if not missing:
        return
    report.add(
        ERROR,
        "field.not_anywhere",
        f"这些字段在库中任何产业类型下都不存在：{'、'.join(missing)}",
        where="类型检查",
        hint=(
            "出现位置："
            + "；".join(f"{k} → {'、'.join(used[k][:3])}" for k in missing[:4])
            + "。拼写错误或字段尚未创建；"
            "任何公司执行到这条效果都会报「所属产业下不存在字段」"
        ),
    )


# ==================== 各检查项 ====================


def _party_map(payload: dict, report: Report) -> dict[str, dict]:
    roles: dict[str, dict] = {}
    for i, p in enumerate(payload.get("partyRoles") or []):
        if not isinstance(p, dict):
            report.add(ERROR, "party.shape", f"partyRoles[{i}] 不是对象", where="参与方")
            continue
        role = p.get("role")
        if not role:
            report.add(ERROR, "party.role", f"partyRoles[{i}] 缺少 role", where="参与方")
            continue
        if role in roles:
            report.add(ERROR, "party.dup", f"参与方角色「{role}」重复", where="参与方")
        roles[str(role)] = p
    if not roles:
        report.add(ERROR, "party.empty", "没有任何参与方角色", where="参与方")
    if roles and not [p for p in roles.values() if not p.get("isHost")]:
        report.add(
            ERROR,
            "party.all_host",
            "所有参与方都是主办方，效果无法落到任何公司",
            where="参与方",
            hint="至少保留一个非主办方角色",
        )
    return roles


def _declared_vars(payload: dict) -> set[str]:
    """收集所有可用的变量名。

    三类都算：

    - `FOREACH` 的循环变量；
    - 顶层 `ASSIGN` 的变量 —— 引擎在 `execute` 里只有一个作用域 `scope`，
      `ASSIGN` 直接写 `scope[name]`，因此**顶层的 assign 变量对后续所有效果可见**；
    - **输入项 key** —— 引擎的 `VAR` 求值顺序是「先查 scope，再查 inputs」
      （`engine.py:1776`），所以 `{"type":"VAR","name":"tech"}` 也能读到输入项 `tech`
      的运行期值。本库的 `input_value()` 正是利用这一点，
      因此输入项 key 必须被认作合法的 VAR 目标。
    """
    out: set[str] = set()

    def walk(effects: Sequence[Any]) -> None:
        for eff in effects or []:
            if not isinstance(eff, dict):
                continue
            kind = eff.get("kind")
            if kind == "FOREACH":
                if eff.get("var"):
                    out.add(str(eff["var"]))
                walk(eff.get("body") or [])
            elif kind == "IF":
                walk(eff.get("then") or [])
                walk(eff.get("else") or [])
            elif kind == "ASSIGN" and eff.get("name"):
                out.add(str(eff["name"]))

    walk(payload.get("effects") or [])
    for item in payload.get("inputSchema") or []:
        if isinstance(item, dict) and item.get("key"):
            out.add(str(item["key"]))
    return out


def _check_inputs(payload: dict, inputs: dict, report: Report) -> None:
    if not inputs:
        report.add(
            INFO,
            "input.none",
            "该合同类型没有任何输入项（效果只能用常量与字段现值）",
            where="输入项",
        )
    for key, item in inputs.items():
        itype = item.get("type")
        if itype not in INPUT_TYPES:
            report.add(ERROR, "input.type", f"输入项「{key}」的类型非法：{itype!r}", where="输入项")
            continue
        if itype == "ENTITY" and not item.get("entityType"):
            report.add(
                ERROR,
                "input.entity_type",
                f"输入项「{key}」是 ENTITY 类型却没有 entityType",
                where="输入项",
            )
        if itype in ("infrastructureList", "vehicleList"):
            field = "allowedInfrastructures" if itype == "infrastructureList" else "allowedVehicles"
            names = item.get(field)
            if names is not None and not isinstance(names, list):
                report.add(ERROR, "input.allowed", f"输入项「{key}」的 {field} 必须是数组", where="输入项")
        if item.get("party") and itype not in LIST_INPUT_TYPES:
            report.add(
                WARNING,
                "input.party_not_list",
                f"输入项「{key}」绑定了参与方，但类型 {itype} 不是清单类（引擎只对清单用这个字段）",
                where="输入项",
            )
        if itype == "nodeRoute":
            report.add(
                INFO,
                "input.route",
                f"输入项「{key}」是节点列表：创建合同时会校验相邻节点之间必须有连线",
                where="输入项",
            )
        # 清单类/需要参与公式的输入项，key 必须是合法标识符：
        # 引擎的 FORMULA 沙箱与 keys(...) 都要求它能直接当名字写（中文 key 会静默取 0）
        if not _VALID_IDENT_RE.match(str(key)) and itype not in ("",):
            report.add(
                WARNING,
                "input.key_not_identifier",
                f"输入项 key「{key}」不是合法标识符（只能字母/数字/下划线，且不以数字开头）",
                where="输入项",
                hint=(
                    "循环遍历（for_each）与公式引用它时会取不到值；"
                    "建议改用英文/拼音 key，显示名放到 label 里"
                ),
            )


def _check_conditions(
    payload: dict,
    parties: dict[str, dict],
    inputs: dict,
    var_scope: set[str],
    report: Report,
) -> None:
    for i, cond in enumerate(payload.get("conditions") or []):
        spot = f"检查[{i}]"
        if not isinstance(cond, dict):
            report.add(ERROR, "cond.shape", f"{spot} 不是对象", where="检查")
            continue
        kind = cond.get("kind")
        label = cond.get("label") or ""
        if label:
            spot = f"检查[{i}]「{label}」"
        if kind == "INDUSTRY_IS":
            _check_party(cond.get("party"), parties, report, spot)
            if cond.get("industryTypeId") in (None, ""):
                report.add(ERROR, "cond.industry", f"{spot} 缺少 industryTypeId", where="检查")
        elif kind in ("FIELD_COMPARE", "VALUE_COMPARE", "DICT_COMPARE", "LIST_COMPARE"):
            _check_party(cond.get("party"), parties, report, spot, required=(kind == "FIELD_COMPARE"))
            if kind == "FIELD_COMPARE" and not str(cond.get("fieldKey") or "").strip():
                report.add(ERROR, "cond.field", f"{spot} 缺少 fieldKey", where="检查")
            op = str(cond.get("op") or "")
            if not op:
                report.add(ERROR, "cond.op", f"{spot} 缺少比较运算符 op", where="检查")
            for slot in ("value", "value1", "value2"):
                if slot in cond:
                    _walk_value(
                        cond[slot], inputs, var_scope, parties, report, f"{spot}.{slot}", context="cond"
                    )
        else:
            report.add(
                ERROR,
                "cond.kind",
                f"{spot} 的检查类型未知：{kind!r}",
                where="检查",
                hint="可用：FIELD_COMPARE / VALUE_COMPARE / INDUSTRY_IS / DICT_COMPARE / LIST_COMPARE",
            )
        # 分支条件（挂在 IF 分支下的检查）
        br = cond.get("branch")
        if isinstance(br, dict) and br.get("cond") is not None:
            _walk_value(
                br["cond"], inputs, var_scope, parties, report, f"{spot}.branch.cond", context="cond"
            )


def _check_effects(
    payload: dict,
    parties: dict[str, dict],
    inputs: dict,
    var_scope: set[str],
    report: Report,
    *,
    root: bool,
) -> None:
    _walk_effects(payload.get("effects") or [], parties, inputs, var_scope, report, "效果")


def _walk_effects(
    effects: Sequence[Any],
    parties: dict[str, dict],
    inputs: dict,
    var_scope: set[str],
    report: Report,
    where: str,
) -> None:
    for i, eff in enumerate(effects):
        spot = f"{where}[{i}]"
        if not isinstance(eff, dict):
            report.add(ERROR, "effect.shape", f"{spot} 不是对象", where=where)
            continue
        kind = eff.get("kind")
        if kind == "FIELD":
            _check_leaf_effect(eff, parties, inputs, var_scope, report, spot)
        elif kind == "IF":
            cond = eff.get("cond")
            if not isinstance(cond, dict):
                report.add(ERROR, "effect.if_cond", f"{spot} 的条件分支缺少 cond", where=where)
            else:
                _walk_value(cond, inputs, var_scope, parties, report, f"{spot}.cond", context="cond")
            for branch in ("then", "else"):
                body = eff.get(branch)
                if body is None:
                    continue
                if not isinstance(body, list):
                    report.add(ERROR, "effect.if_branch", f"{spot}.{branch} 必须是数组", where=where)
                    continue
                if not body:
                    report.add(
                        INFO,
                        "effect.if_empty",
                        f"{spot} 的「{'真' if branch == 'then' else '假'}分支」是空的",
                        where=where,
                    )
                _walk_effects(body, parties, inputs, var_scope, report, f"{spot}.{branch}")
        elif kind == "FOREACH":
            items = eff.get("items")
            if not isinstance(items, dict):
                report.add(ERROR, "effect.foreach_items", f"{spot} 的循环缺少 items", where=where)
            else:
                _walk_value(items, inputs, var_scope, parties, report, f"{spot}.items", context="value")
            if not eff.get("var"):
                report.add(ERROR, "effect.foreach_var", f"{spot} 的循环缺少变量名 var", where=where)
            body = eff.get("body")
            if not isinstance(body, list):
                report.add(ERROR, "effect.foreach_body", f"{spot}.body 必须是数组", where=where)
            else:
                if not body:
                    report.add(INFO, "effect.foreach_empty", f"{spot} 的循环体是空的", where=where)
                # 循环体内的 ASSIGN 变量加入作用域（供内层值源引用）
                inner_scope = set(var_scope)
                if eff.get("var"):
                    inner_scope.add(str(eff["var"]))
                for sub in body:
                    if isinstance(sub, dict) and sub.get("kind") == "ASSIGN" and sub.get("name"):
                        inner_scope.add(str(sub["name"]))
                _walk_effects(body, parties, inputs, inner_scope, report, f"{spot}.body")
        elif kind == "ASSIGN":
            if not eff.get("name"):
                report.add(ERROR, "effect.assign_name", f"{spot} 的赋值缺少变量名", where=where)
            if "value" not in eff:
                report.add(ERROR, "effect.assign_value", f"{spot} 的赋值缺少 value", where=where)
            else:
                _walk_value(eff["value"], inputs, var_scope, parties, report, f"{spot}.value", context="value")
        else:
            report.add(
                ERROR,
                "effect.kind",
                f"{spot} 的效果类型未知：{kind!r}",
                where=where,
                hint="可用：FIELD / IF / FOREACH / ASSIGN",
            )


def _check_leaf_effect(
    eff: dict,
    parties: dict[str, dict],
    inputs: dict,
    var_scope: set[str],
    report: Report,
    spot: str,
) -> None:
    role = eff.get("party")
    _check_party(role, parties, report, spot, required=True)
    field_key = str(eff.get("fieldKey") or "").strip()
    if not field_key:
        report.add(
            ERROR,
            "effect.field_key",
            f"{spot} 未指定 fieldKey",
            where="效果",
            hint="引擎会因找不到字段而直接报错",
        )
    party = parties.get(str(role)) if role else None
    if party and party.get("isHost"):
        report.add(
            ERROR,
            "effect.host_party",
            f"{spot} 的目标是主办方「{role}」",
            where="效果",
            hint="主办方不绑定公司，引擎会拒绝执行（主办方只能作为条件之外的展示方）",
        )
    op = str(eff.get("op") or "").upper()
    if op not in ("ADD", "SUB", "SET"):
        report.add(ERROR, "effect.op", f"{spot} 的 op 非法：{op!r}", where="效果")
    if "value" not in eff:
        report.add(
            ERROR,
            "effect.value",
            f"{spot} 缺少 value",
            where="效果",
            hint="引擎会把缺失的 value 当 0 处理（静默错误）",
        )
    else:
        _walk_value(eff["value"], inputs, var_scope, parties, report, f"{spot}.value", context="value")
    for slot in ("value2", "valueOp"):
        if eff.get(slot) is not None:
            report.add(
                WARNING,
                "effect.legacy_combine",
                f"{spot} 使用了引擎的 valueOp/value2 组合写法",
                where="效果",
                hint="本库的具名效果会把它折叠成单个值源的运算，语义更明确；建议改用 a + b 表达式",
            )
            break
    if eff.get("value2") is not None:
        _walk_value(eff["value2"], inputs, var_scope, parties, report, f"{spot}.value2", context="value")
    # 值源型的值（INPUT/OP/VAR/FORMULA/ENTITY/...）是合法的：引擎会先求值再写入。
    # 只有「既不是值源、也不是字面量」的形状才是错的（本库不会产出，手写 JSON 可能）。
    if isinstance(eff.get("value"), dict):
        spec = eff["value"]
        vtype = spec.get("type")
        if vtype is None:
            # 没有 type 的字典 = 字面量字典（本库的 add_dict/sub_dict/set_dict 产物）
            inner = spec
            bad = [k for k, v in inner.items() if isinstance(v, dict) and "type" in v]
            if bad:
                report.add(
                    ERROR,
                    "effect.dict_spec_leak",
                    f"{spot} 的字典效果值里混入了值源对象：{'、'.join(bad)}",
                    where="效果",
                    hint="引擎会把值源对象当普通数据写入；请改用常量字典",
                )
        elif vtype == "CONST":
            inner = spec.get("value")
            if isinstance(inner, dict) and any(
                isinstance(v, dict) and "type" in v for v in inner.values()
            ):
                report.add(
                    ERROR,
                    "effect.dict_spec_leak",
                    f"{spot} 的字典效果值里混入了值源对象",
                    where="效果",
                    hint="引擎会把值源对象当普通数据写入；请改用常量字典",
                )
        elif vtype not in _VALUE_SPEC_TYPES:
            report.add(
                ERROR,
                "effect.value_shape",
                f"{spot} 的值形状非法（type={vtype!r}）",
                where="效果",
                hint=f"可用值源：{'、'.join(sorted(_VALUE_SPEC_TYPES))}，或常量字面量",
            )


def _check_party(role: Any, parties: dict[str, dict], report: Report, spot: str, *, required: bool = False) -> None:
    if role in (None, ""):
        if required:
            report.add(
                ERROR,
                "effect.party_missing",
                f"{spot} 未指定参与方",
                where="效果",
                hint="引擎会因无法定位目标公司而拒绝执行",
            )
        return
    if str(role) not in parties:
        report.add(
            ERROR,
            "party.unknown",
            f"{spot} 引用了未定义的参与方「{role}」",
            where="效果",
            hint=f"已定义：{'、'.join(parties) or '（无）'}",
        )


def _walk_value(
    spec: Any,
    inputs: dict,
    var_scope: set[str],
    parties: dict[str, dict],
    report: Report,
    spot: str,
    *,
    context: str,
) -> None:
    """递归检查一个值源。"""
    if spec is None:
        return
    if not isinstance(spec, dict):
        # 字面量（数字/字符串/数组）是合法的 value（引擎按常量处理）
        return
    t = spec.get("type")
    # IF 的 cond 是「值源」；而条件对象本身（含 kind）也可能被传进来，这里做一次分流，
    # 避免把 {"kind": "INDUSTRY_IS", ...} 当成未知值源误报。
    cond_kind = spec.get("kind")
    if t is None and cond_kind in ("INDUSTRY_IS", "FIELD_COMPARE", "VALUE_COMPARE", "DICT_COMPARE", "LIST_COMPARE"):
        for slot in ("value", "value1", "value2"):
            if slot in spec:
                _walk_value(spec[slot], inputs, var_scope, parties, report, f"{spot}.{slot}", context=context)
        return
    if t == "INPUT":
        key = str(spec.get("key") or "")
        if not key:
            report.add(ERROR, "value.input_key", f"{spot} 的输入项引用缺少 key", where="值源")
            return
        item = inputs.get(key)
        if item is None:
            report.add(
                ERROR,
                "value.input_unknown",
                f"{spot} 引用了不存在的输入项「{key}」",
                where="值源",
                hint=f"已定义：{'、'.join(inputs) or '（无）'}；引擎取不到会按空值参与运算（等价于 0）",
            )
            return
        aggregate = spec.get("aggregate")
        if aggregate:
            allowed = AGGREGATE_INPUT_TYPES.get(str(aggregate))
            itype = str(item.get("type") or "")
            if allowed is None and str(aggregate) not in AGGREGATE_INPUT_TYPES:
                report.add(
                    ERROR,
                    "value.aggregate_unknown",
                    f"{spot} 使用了未知聚合口径 {aggregate}",
                    where="值源",
                )
            elif allowed is not None and itype and itype not in allowed:
                report.add(
                    ERROR,
                    "value.aggregate_mismatch",
                    f"{spot}：聚合「{aggregate}」需要 "
                    f"{'、'.join(LIST_INPUT_ENTITY.get(x, x) for x in allowed)} 输入项，"
                    f"但「{key}」的类型是 {itype}",
                    where="值源",
                    hint="清单类型与聚合口径错配时，引擎会静默算出 0",
                )
            if str(aggregate) == "PRICE" and not spec.get("party"):
                report.add(
                    INFO,
                    "value.price_avg",
                    f"{spot} 的原料总价使用市场均价口径（未指定参与方）",
                    where="值源",
                    hint="要按公司所在地取价请用 total_price(清单, at=参与方)",
                )
        if item.get("branch") and context == "value":
            pass  # 条件显隐只影响表单，不影响取值
    elif t == "OP":
        for j, arg in enumerate(spec.get("args") or []):
            _walk_value(arg, inputs, var_scope, parties, report, f"{spot}.args[{j}]", context=context)
    elif t == "FORMULA":
        expr = str(spec.get("expr") or "")
        if _INPUT_REF_RE.search(expr):
            report.add(
                ERROR,
                "value.formula_inputs_object",
                f"{spot} 的公式用了 `inputs[...]`，但引擎沙箱里没有 `inputs` 这个对象",
                where="值源",
                hint=(
                    f"表达式：{expr}；引擎把输入项铺成顶层名字，请直接写 `输入项key[...]` "
                    "或 `get(输入项key, 键)`"
                ),
            )
        if _SCOPE_REF_RE.search(expr):
            report.add(
                ERROR,
                "value.formula_scope_object",
                f"{spot} 的公式用了 `scope[...]`，但引擎沙箱里没有 `scope` 这个对象",
                where="值源",
                hint=f"表达式：{expr}；循环变量是顶层名字，请直接写 `变量名`",
            )
        for name in _formula_names(expr):
            if name in inputs or name in var_scope or name in _formula_name_pool_cached():
                continue
            report.add(
                ERROR,
                "value.formula_name",
                f"{spot} 的公式引用了未知名字「{name}」",
                where="值源",
                hint=(
                    f"表达式：{expr}；可用："
                    + "、".join(sorted(list(inputs) + sorted(var_scope)))
                    + "（以及内置助手 IF/AND/OR/NOT/len/get/keys/… 与数学函数 "
                    "abs/sqrt/exp/log/pow/min/max/sum/avg/round/floor/ceil…，注意都是**小写**）"
                ),
            )
    elif t == "VAR":
        name = str(spec.get("name") or "")
        if name not in var_scope:
            report.add(
                ERROR,
                "value.var_scope",
                f"{spot} 引用了作用域外的变量「{name}」",
                where="值源",
                hint="变量必须在 for_each(..., var=...) 的循环体内使用",
            )
    elif t == "FIELD":
        if not str(spec.get("fieldKey") or "").strip():
            report.add(ERROR, "value.field_key", f"{spot} 的字段引用缺少 fieldKey", where="值源")
        role = str(spec.get("party") or "").strip()
        if not role:
            report.add(ERROR, "value.field_party", f"{spot} 的字段引用缺少参与方", where="值源")
        elif role not in parties:
            report.add(
                ERROR,
                "value.field_party_unknown",
                f"{spot} 的字段引用指向未定义的参与方「{role}」",
                where="值源",
                hint=f"已定义：{'、'.join(parties) or '（无）'}",
            )
    elif t == "ENTITY":
        et = str(spec.get("entityType") or "")
        attr = str(spec.get("attribute") or "")
        if et not in ENTITY_ATTRIBUTES:
            report.add(ERROR, "value.entity_type", f"{spot} 的实体类型未知：{et!r}", where="值源")
        elif attr not in ENTITY_ATTRIBUTES[et]:
            report.add(
                ERROR,
                "value.entity_attr",
                f"{spot}：{ENTITY_TYPE_LABEL.get(et, et)} 没有属性「{attr}」",
                where="值源",
                hint=f"可用：{'、'.join(ENTITY_ATTRIBUTES[et])}",
            )
        if not str(spec.get("entityRef") or "").strip():
            report.add(
                ERROR,
                "value.entity_ref",
                f"{spot} 的实体引用缺少 entityRef",
                where="值源",
                hint="引擎需要输入项 key 才能取到实体主键",
            )
    elif t == "ROUTE":
        ref = str(spec.get("routeRef") or "")
        if ref not in inputs:
            report.add(
                ERROR,
                "value.route_ref",
                f"{spot} 的路程引用了不存在的输入项「{ref}」",
                where="值源",
            )
    elif t in ("CONST", "INDUSTRY_IS", "PARTY_COMPANY_NAME"):
        return
    else:
        report.add(ERROR, "value.type", f"{spot} 的值源类型未知：{t!r}", where="值源")


def _check_values(
    payload: dict,
    inputs: dict,
    var_scope: set[str],
    parties: dict[str, dict],
    report: Report,
) -> None:
    """输入项的 branch 条件也引用了值源，这里单独扫一遍。"""
    for i, item in enumerate(payload.get("inputSchema") or []):
        if not isinstance(item, dict):
            continue
        br = item.get("branch")
        if isinstance(br, dict) and br.get("cond") is not None:
            _walk_value(
                br["cond"],
                inputs,
                var_scope,
                parties,
                report,
                f"输入项[{i}]「{item.get('key')}」的条件",
                context="cond",
            )


def _check_fields_against_industry(
    payload: dict,
    parties: dict[str, dict],
    declared: dict[Any, dict[str, str]],
    report: Report,
    *,
    strict: bool,
    industry_names: dict[Any, str] | None = None,
) -> None:
    """校验效果引用的字段是否存在于参与方所属产业，以及效果与字段类型是否匹配。"""
    if not declared:
        report.add(
            INFO,
            "industry.not_provided",
            "未提供产业字段信息，跳过「字段是否存在」与「效果 × 字段类型」检查",
            where="类型检查",
            hint="用 check() 传 competition 参数即可自动读取，或 CLI 加 --competition",
        )
        return

    # 参与方 → 产业类型 id
    party_industry: dict[str, int | None] = {}
    for role, p in parties.items():
        if p.get("isHost"):
            continue
        tid = p.get("industryTypeId")
        party_industry[role] = int(tid) if tid not in (None, "") else None
    industry_type_name = {int(k): str(v) for k, v in (industry_names or {}).items()}

    # 收集 (role, fieldKey) → 用到的效果名
    usage: dict[tuple[str, str], list[str]] = {}

    def walk(effects: Sequence[Any]) -> None:
        for eff in effects or []:
            if not isinstance(eff, dict):
                continue
            if eff.get("kind") == "FIELD" and eff.get("party") and eff.get("fieldKey"):
                usage.setdefault((str(eff["party"]), str(eff["fieldKey"])), []).append(str(eff.get("op")))
            elif eff.get("kind") == "IF":
                walk(eff.get("then") or [])
                walk(eff.get("else") or [])
            elif eff.get("kind") == "FOREACH":
                walk(eff.get("body") or [])

    walk(payload.get("effects") or [])

    for (role, field_key), ops in sorted(usage.items()):
        tid = party_industry.get(role)
        if tid is None:
            report.add(
                INFO,
                "industry.party_unbound",
                f"参与方「{role}」未限定产业类型，其字段「{field_key}」无法预先校验",
                where="类型检查",
                hint="需要精确校验时给 party(..., industry_type_id=N)，或在 partyRoles 里补 industryTypeId",
            )
            continue
        fields = declared.get(tid)
        if fields is None:
            report.add(
                INFO,
                "industry.unknown",
                f"产业类型 #{tid} 的字段清单不可得，跳过「{field_key}」的检查",
                where="类型检查",
            )
            continue
        actual = fields.get(field_key)
        if actual is None:
            report.add(
                ERROR,
                "field.missing",
                f"参与方「{role}」所属产业类型「{industry_type_name}」下没有字段「{field_key}」",
                where="类型检查",
                hint=f"该产业可用字段：{'、'.join(sorted(fields)) or '（无）'}；"
                "引擎执行时会直接报「所属产业下不存在字段」",
            )
            continue
        # 效果 × 字段类型
        for op in ops:
            kinds = _kinds_for_op(op)
            if not kinds:
                continue
            need = {EFFECT_KINDS[k][0] for k in kinds}
            if "ANY" in need or actual.upper() in need:
                continue
            if strict or _definitely_wrong(op, actual):
                report.add(
                    ERROR,
                    "effect.type_mismatch",
                    f"参与方「{role}」的字段「{field_key}」实际类型是 {actual}，"
                    f"但使用了 op={op}（{'/'.join(sorted(need))} 字段语义）",
                    where="类型检查",
                    hint=f"{actual} 字段可用：{'、'.join(KINDS_BY_FIELD_TYPE.get(actual.upper(), ()))}",
                )


def _kinds_for_op(op: str) -> tuple[str, ...]:
    """引擎 op → 可能对应的具名效果。"""
    mapping = {
        "ADD": ("add_number", "append_items", "add_dict"),
        "SUB": ("sub_number", "remove_items", "sub_dict", "remove_keys"),
        "SET": ("set_number", "set_items", "set_dict", "set_value"),
    }
    return mapping.get(str(op or "").upper(), ())


def _definitely_wrong(op: str, field_type: str) -> bool:
    """判断「op × 字段类型」是否是明确矛盾（用于非严格模式的默认判定）。

    只有明确矛盾才报：
    - 数值字段用了会把数据写成结构的 op（字典/列表语义）；
    - 列表/字典字段用了纯数值 op。
    同名 op 在不同类型上语义不同，这是引擎既有设计，本库不做「猜测式」升级。
    """
    ft = str(field_type or "").upper()
    o = str(op or "").upper()
    if ft == "NUMBER":
        return o not in ("ADD", "SUB", "SET")  # 数值字段三种 op 都有意义
    if ft == "LIST":
        return False  # ADD/SUB/SET 都有明确列表语义
    if ft == "DICTIONARY":
        return False
    if ft in ("STRING", "BOOLEAN"):
        return o in ("ADD", "SUB")  # 文本/布尔只有 SET 有意义
    return False


# ==================== 公式引用抽取 ====================


def _formula_names(expr: str) -> list[str]:
    """抽取公式里出现的裸标识符（排除字符串字面量与属性名）。

    用于校验「引用了不存在的输入项/变量」——引擎在沙箱里取不到名字时返回 None，
    参与运算等价于 0，是典型的静默错误。
    """
    if not expr:
        return []
    # 去掉字符串字面量，避免把 'mats' 里的内容当标识符
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", " ", expr)
    names: list[str] = []
    for m in _IDENT_RE.finditer(stripped):
        name = m.group(1)
        # 跳过属性访问 obj.name 里的 name
        before = stripped[: m.start()].rstrip()
        if before.endswith("."):
            continue
        # 跳过函数调用的关键字参数写法（谨慎：这里只看普通标识符）
        if name not in names:
            names.append(name)
    return names
