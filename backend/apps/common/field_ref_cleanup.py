"""删除产业字段后清理悬空引用：对应原 server/src/common/field-ref-cleanup.ts。

- timerValue === "field:<deletedFieldKey>" → 置空
- calcGraph 中 type:"value" 且 data.fieldKey === deletedFieldKey 的节点 → 移除节点及相关边
- calcGraph 中 value(FORMULA) 节点的 data.expr 里以变量形式引用该字段的标识符：
  - 改名：整体替换为新字段键
  - 删除：整体替换为 0（数字占位，避免公式求值因变量未定义而报错；语义偏离由告警提示人工核对）
- 合同类型（全局模板）对该字段的引用：不静默改写，返回告警文案由调用方回传前端 + 落服务端日志
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("gipfel")

TIMER_REF_PREFIX = "field:"

# 合同 JSON 里「引用产业字段键」的三种载体（语义见 apps/contracts/engine.py）：
#   1. 效果叶子   {"kind": "FIELD", "fieldKey": ...}          → 写字段（apply_leaf，engine.py:1617）
#   2. 值规格     {"type": "FIELD", "fieldKey": ...}          → 读字段（eval_value_spec，engine.py:1541）
#   3. 前置条件   {"kind": "FIELD_COMPARE", "fieldKey": ...}  → 比较字段（_run_conditions，engine.py:1898）
# 三者分属两套判别键（效果/条件用 kind，值规格用 type），只认其中一种就会漏判：
# 早期实现只匹配 kind=="FIELD"，导致「合同里读取该字段」和「条件里比较该字段」
# 这两类引用在字段改名 / 删除时完全不告警。
_FIELD_REF_CARRIERS: tuple[tuple[str, str, str], ...] = (
    ("kind", "FIELD", "效果写入"),
    ("type", "FIELD", "取值读取"),
    ("kind", "FIELD_COMPARE", "条件比较"),
)


def _rewrite_formula_expr(expr: str, old_key: str, new_token: str) -> str:
    """把表达式里独立出现的 old_key 标识符整体替换为 new_token。

    字符串字面量（双/单/反引号）内的同名文本不受影响，避免误改引号内容。
    """
    if not expr or not old_key:
        return expr
    # 先匹配字符串字面量（原样保留），再匹配词边界内的 old_key
    pattern = re.compile(
        r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`|\b'
        + re.escape(old_key)
        + r"\b"
    )

    def repl(m):  # noqa: ANN001
        s = m.group(0)
        if s[:1] in ('"', "'", "`"):
            return s  # 字符串字面量，不动
        return new_token

    return pattern.sub(repl, expr)


def _rewrite_formula_refs(graph: dict, old_key: str, new_token: str) -> bool:
    """遍历计算图所有 value(FORMULA) 节点，改写 data.expr 中对 old_key 的变量引用。

    new_token 为改名时的新字段键，或删除时的 0 / null 占位。返回是否发生过改写。
    """
    if not old_key:
        return False
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list):
        return False
    hit = False
    for n in nodes:
        if (
            isinstance(n, dict)
            and n.get("type") == "value"
            and (n.get("data") or {}).get("kind") == "FORMULA"
        ):
            data = n.get("data") or {}
            expr = data.get("expr")
            if not expr:
                continue
            new_expr = _rewrite_formula_expr(str(expr), old_key, new_token)
            if new_expr != str(expr):
                data["expr"] = new_expr
                hit = True
    return hit


def cleanup_field_references(industry_type_id: int, deleted_field_key: str) -> list[str]:
    """字段删除后清理同产业类型内的悬空引用，并报告无法自动清理的外部引用。

    返回需要提示管理员的告警文案列表（无告警时为空列表）。
    """
    if not deleted_field_key:
        return []
    # 延迟导入避免循环依赖
    from apps.industry_types.models import IndustryField

    warnings: list[str] = []

    siblings = IndustryField.objects.exclude(field_key=deleted_field_key).filter(
        industry_type_id=industry_type_id
    )
    for f in siblings:
        changed = False
        if f.timer_value == f"{TIMER_REF_PREFIX}{deleted_field_key}":
            f.timer_value = ""
            changed = True
        if f.calc_graph:
            try:
                g = json.loads(f.calc_graph)
                nodes = g.get("nodes") if isinstance(g, dict) else None
                if isinstance(nodes, list):
                    removed = {
                        n.get("id")
                        for n in nodes
                        if isinstance(n, dict)
                        and n.get("type") == "value"
                        and (n.get("data") or {}).get("fieldKey") == deleted_field_key
                    }
                    if removed:
                        g["nodes"] = [n for n in nodes if n.get("id") not in removed]
                        if isinstance(g.get("edges"), list):
                            g["edges"] = [
                                e
                                for e in g["edges"]
                                if e.get("source") not in removed
                                and e.get("target") not in removed
                            ]
                        changed = True
                    # FORMULA 表达式里以变量形式引用被删字段 → 替换为 0 占位，
                    # 避免该公式后续求值因未定义变量而报错；语义变化由告警提示人工核对
                    if _rewrite_formula_refs(g, deleted_field_key, "0"):
                        logger.warning(
                            "[field-cleanup] 字段 %s 被删除，已将引用它的公式"
                            "（产业 #%s 字段 %s）中的变量替换为 0，请人工核对公式语义",
                            deleted_field_key, industry_type_id, f.field_key,
                        )
                        warnings.append(
                            f"字段「{f.name}（{f.field_key}）」的公式里以变量形式引用了被删字段"
                            f"「{deleted_field_key}」，已自动替换为 0，请核对公式语义是否仍然正确"
                        )
                        changed = True
                    if changed:
                        f.calc_graph = json.dumps(g, ensure_ascii=False)
            except (ValueError, TypeError):
                # 计算图 JSON 损坏：跳过，不阻断删除
                pass
        if changed:
            f.save(update_fields=["timer_value", "calc_graph"])

    # 合同类型引用告警：合同类型是全局模板，无法安全地静默改写（同名 fieldKey 在别的
    # 产业下可能仍存在），而删除后这些合同一执行就会报「该产业下不存在字段」。
    # 之前只有改名路径有这层告警、删除路径完全没有，属于不对称的盲区。
    affected = _affected_contract_types(deleted_field_key)
    if affected:
        warnings.append(
            f"字段「{deleted_field_key}」已删除，但以下合同类型仍引用它，"
            f"执行这些合同时会报「该产业下不存在字段」，请到「合同类型」里修改配置："
            f"{'、'.join(affected)}"
        )
        logger.warning(
            "[field-cleanup] 字段 %s（产业 #%s）已删除，但仍被以下合同类型引用：%s",
            deleted_field_key, industry_type_id, "、".join(affected),
        )
    return warnings


def rename_field_references(
    industry_type_id: int, old_field_key: str, new_field_key: str
) -> list[str]:
    """字段改名后同步同产业类型内的引用（对应删除时的 cleanup_field_references）。

    - 兄弟字段 timer_value === "field:<old>" → "field:<new>"
    - 兄弟字段 calcGraph 中 type:"value" 且 data.fieldKey === old → new
    - 兄弟字段 calcGraph 中 value(FORMULA) 的 expr 里的变量引用 old → new
    - 合同类型（全局模板）的引用不做静默改写：同一合同类型可能被多个产业类型的
      公司使用，全局改写会误伤其他产业。改为返回告警文案（同时落服务端日志），
      由调用方回传前端，让管理员当场看到而不是只躺在日志里。

    返回需要提示管理员的告警文案列表（无告警时为空列表）。
    """
    if not old_field_key or old_field_key == new_field_key:
        return []
    # 延迟导入避免循环依赖
    from apps.industry_types.models import IndustryField

    siblings = IndustryField.objects.exclude(field_key=new_field_key).filter(
        industry_type_id=industry_type_id
    )
    for f in siblings:
        changed = False
        if f.timer_value == f"{TIMER_REF_PREFIX}{old_field_key}":
            f.timer_value = f"{TIMER_REF_PREFIX}{new_field_key}"
            changed = True
        if f.calc_graph:
            try:
                g = json.loads(f.calc_graph)
                nodes = g.get("nodes") if isinstance(g, dict) else None
                if isinstance(nodes, list):
                    hit = False
                    for n in nodes:
                        if (
                            isinstance(n, dict)
                            and n.get("type") == "value"
                            and (n.get("data") or {}).get("fieldKey") == old_field_key
                        ):
                            n["data"]["fieldKey"] = new_field_key
                            hit = True
                    # FORMULA 表达式里以变量形式引用旧字段键 → 整体替换为新字段键
                    if _rewrite_formula_refs(g, old_field_key, new_field_key):
                        hit = True
                    if hit:
                        f.calc_graph = json.dumps(g, ensure_ascii=False)
                        changed = True
            except (ValueError, TypeError):
                # 计算图 JSON 损坏：跳过，不阻断改名
                pass
        if changed:
            f.save(update_fields=["timer_value", "calc_graph"])

    # 合同类型引用告警（不静默改写，见 docstring）：效果写入 / 取值读取 / 条件比较三类都要报
    warnings: list[str] = []
    affected = _affected_contract_types(old_field_key)
    if affected:
        msg = (
            f"字段键「{old_field_key}」已改为「{new_field_key}」，"
            f"但以下合同类型仍按旧键引用它，需手工到「合同类型」里改配置，"
            f"否则这些合同执行时会报「该产业下不存在字段」：{'、'.join(affected)}"
        )
        warnings.append(msg)
        logger.warning(
            "[field-rename] 字段 %s → %s（产业 #%s）被以下合同类型引用，请人工核对 fieldKey 配置：%s",
            old_field_key, new_field_key, industry_type_id, "、".join(affected),
        )
    return warnings


def _collect_field_ref_kinds(tree, field_key: str) -> set[str]:
    """递归收集 tree（合同 effects / conditions 树）中对 field_key 的引用载体类型。

    返回中文标签集合（如 {"效果写入", "条件比较"}），空集表示未引用。
    判定覆盖 ``_FIELD_REF_CARRIERS`` 的三种载体；命中 fieldKey 但载体未知时
    归入「其他引用」，宁可多报也不漏报（将来新增节点类型也不会静默漏判）。
    注意必须全量遍历（不能像布尔判断那样短路），否则同一字段的多种引用只会报出第一种。
    """
    found: set[str] = set()
    if not field_key:
        return found

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("fieldKey") == field_key:
                for attr, val, label in _FIELD_REF_CARRIERS:
                    if node.get(attr) == val:
                        found.add(label)
                        break
                else:
                    found.add("其他引用")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(tree)
    return found


def _affected_contract_types(field_key: str) -> list[str]:
    """扫描全部合同类型的 effects + conditions，返回引用 field_key 的合同类型描述。

    合同类型是全局模板、可能被多个产业类型的公司复用，因此这里只做「报告」不做改写：
    同名 fieldKey 在别的产业下可能仍然存在，静默改写会误伤其他产业。
    返回形如 ``["buy_material(采购原料)[效果写入/条件比较]"]``。
    """
    if not field_key:
        return []
    try:
        from apps.contracts.models import ContractType
    except Exception:  # noqa: BLE001 contracts 应用可能尚未就绪
        return []

    affected: list[str] = []
    try:
        rows = ContractType.objects.all().only("key", "name", "effects", "conditions")
        for ct in rows:
            kinds: set[str] = set()
            for raw in (ct.effects, ct.conditions):
                if not raw:
                    continue
                try:
                    tree = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                kinds |= _collect_field_ref_kinds(tree, field_key)
            if kinds:
                affected.append(f"{ct.key}({ct.name})[{'/'.join(sorted(kinds))}]")
    except Exception:  # noqa: BLE001 扫描失败不应阻断字段的改名 / 删除主流程
        logger.exception("[field-ref] 扫描合同类型引用失败（字段 %s）", field_key)
        return []
    return affected
