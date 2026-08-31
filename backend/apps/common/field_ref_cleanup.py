"""删除产业字段后清理悬空引用：对应原 server/src/common/field-ref-cleanup.ts。

- timerValue === "field:<deletedFieldKey>" → 置空
- calcGraph 中 type:"value" 且 data.fieldKey === deletedFieldKey 的节点 → 移除节点及相关边
"""
from __future__ import annotations

import json

TIMER_REF_PREFIX = "field:"


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
                        f.calc_graph = json.dumps(g, ensure_ascii=False)
                        changed = True
            except (ValueError, TypeError):
                # 计算图 JSON 损坏：跳过，不阻断删除
                pass
        if changed:
            f.save(update_fields=["timer_value", "calc_graph"])
