"""删除产业字段后清理悬空引用：对应原 server/src/common/field-ref-cleanup.ts。

- timerValue === "field:<deletedFieldKey>" → 置空
- calcGraph 中 type:"value" 且 data.fieldKey === deletedFieldKey 的节点 → 移除节点及相关边
- calcGraph 中 value(FORMULA) 节点的 data.expr 里以变量形式引用该字段的标识符：
  - 改名：整体替换为新字段键
  - 删除：整体替换为 0（数字占位，避免公式求值因变量未定义而报错；语义偏离由告警提示人工核对）
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("gipfel")

TIMER_REF_PREFIX = "field:"


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


def cleanup_field_references(industry_type_id: int, deleted_field_key: str) -> None:
    if not deleted_field_key:
        return
    # 延迟导入避免循环依赖
    from apps.industry_types.models import IndustryField

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
                        changed = True
                    if changed:
                        f.calc_graph = json.dumps(g, ensure_ascii=False)
            except (ValueError, TypeError):
                # 计算图 JSON 损坏：跳过，不阻断删除
                pass
        if changed:
            f.save(update_fields=["timer_value", "calc_graph"])


def rename_field_references(industry_type_id: int, old_field_key: str, new_field_key: str) -> None:
    """字段改名后同步同产业类型内的引用（对应删除时的 cleanup_field_references）。

    - 兄弟字段 timer_value === "field:<old>" → "field:<new>"
    - 兄弟字段 calcGraph 中 type:"value" 且 data.fieldKey === old → new
    - 合同类型（全局模板）的 effects 引用不做静默改写：同一合同类型可能被多个
      产业类型的公司使用，全局改写会误伤其他产业。改为告警列出受影响的合同类型，
      提示管理员人工核对。
    """
    if not old_field_key or old_field_key == new_field_key:
        return
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

    # 合同类型效果引用告警（不静默改写，见 docstring）
    try:
        from apps.contracts.models import ContractType

        affected: list[str] = []
        for ct in ContractType.objects.all().only("key", "name", "effects"):
            try:
                eff = json.loads(ct.effects) if ct.effects else []
            except (ValueError, TypeError):
                continue
            if _effects_reference_field(eff, old_field_key):
                affected.append(f"{ct.key}({ct.name})")
        if affected:
            import logging

            logging.getLogger("gipfel").warning(
                "[field-rename] 字段 %s → %s（产业 #%s）被以下合同类型的效果引用，"
                "请人工核对其 fieldKey 配置：%s",
                old_field_key, new_field_key, industry_type_id, "、".join(affected),
            )
    except Exception:  # noqa: BLE001 contracts 应用可能尚未就绪
        pass


def _effects_reference_field(effects, field_key: str) -> bool:
    """递归判断效果树中是否存在引用 field_key 的 FIELD 效果节点。"""

    def walk(node) -> bool:
        if isinstance(node, dict):
            if node.get("kind") == "FIELD" and node.get("fieldKey") == field_key:
                return True
            return any(walk(v) for v in node.values())
        if isinstance(node, list):
            return any(walk(v) for v in node)
        return False

    return walk(effects)
