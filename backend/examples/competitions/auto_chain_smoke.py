# -*- coding: utf-8 -*-
"""汽车产业链测试赛 · 三大合同端到端冒烟（真实引擎执行，事务整体回滚，一行都不落库）。

它把比赛里预置的三份合同实例（开采 / 购销 / 运输）逐份喂给合同引擎，打印：

- 参与方与输入项；
- 前置检查逐条结果；
- 每个被改写字段的 `before → after`（同一字段被循环累加时聚合展示）。

用法
----

    cd backend
    .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_smoke.py --competition 188

退出码：0 = 三份合同都跑通且检查全过；1 = 有合同执行异常或检查未通过。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402

from apps.companies.models import Company  # noqa: E402
from apps.contracts.engine import ContractEngine  # noqa: E402
from apps.contracts.models import Contract  # noqa: E402
from apps.maps.models import MapNode  # noqa: E402

#: 运输合同冒烟时使用的链路（相邻节点之间必须有连线，否则路程为 0）
DEFAULT_ROUTE_NODES = ("白云鄂博矿区", "上游集运站", "中部智造园")


def main() -> int:
    parser = argparse.ArgumentParser(description="汽车产业链测试赛三大合同冒烟")
    parser.add_argument("--competition", type=int,
                        default=int(os.environ.get("AUTO_CHAIN_COMPETITION_ID") or 0),
                        help="比赛 id（也可用环境变量 AUTO_CHAIN_COMPETITION_ID）")
    args = parser.parse_args()
    if not args.competition:
        parser.error("需要 --competition <比赛 id>（或用环境变量 AUTO_CHAIN_COMPETITION_ID）")

    cid = args.competition
    contracts = list(Contract.objects.filter(competition_id=cid)
                     .select_related("contract_type").order_by("contract_type__key"))
    if not contracts:
        print(f"比赛 #{cid} 没有任何预置合同（先跑 build_competition 导入建包脚本）")
        return 1

    engine = ContractEngine()
    failures: list[str] = []
    for contract in contracts:
        inputs = json.loads(contract.inputs or "{}")
        _fill_smoke_inputs(cid, contract.contract_type.key, inputs)
        engine_dict = _to_engine_dict(contract, inputs)
        print()
        print("=" * 78)
        print(f"{contract.contract_type.name}（{contract.contract_type.key}）· {contract.name} · {contract.status}")
        print(f"  参与方：{_parties_text(contract)}")
        print(f"  输入项：{json.dumps(inputs, ensure_ascii=False)}")

        try:
            with transaction.atomic():
                result = engine.execute(engine_dict, throw_on_fail=False)
                transaction.set_rollback(True)  # 冒烟不落库
        except Exception as exc:  # noqa: BLE001 - 冒烟要把异常收集起来继续跑下一份
            print(f"  ✗ 引擎执行异常：{type(exc).__name__}: {exc}")
            failures.append(contract.contract_type.key)
            continue

        checks = (result.get("result") or {}).get("checks") or []
        passed = [c for c in checks if c.get("passed")]
        print(f"  前置检查：{len(passed)}/{len(checks)} 通过")
        for c in checks:
            flag = "✓" if c.get("passed") else "✗"
            detail = c.get("errorMessage") or c.get("detail") or ""
            print(f"    {flag} {c.get('label') or c.get('kind')}：{detail}")
        if len(passed) != len(checks):
            failures.append(contract.contract_type.key)

        rows = _aggregate_log(result.get("log") or [])
        print("  字段落账（事务已回滚，仅演示）：")
        if not rows:
            print("    （无字段改动）")
        for row in rows:
            print(f"    {row['company']:<12} {row['field']:<16} {row['before']} → {row['after']}"
                  f"   [op={row['op']} ×{row['hits']}]")

    print()
    print("=" * 78)
    if failures:
        print(f"冒烟结果：✗ 未通过 —— {', '.join(sorted(set(failures)))}")
        return 1
    print(f"冒烟结果：✓ {len(contracts)} 份合同全部执行成功、前置检查全过（数据已回滚）")
    return 0


def _fill_smoke_inputs(cid: int, contract_key: str, inputs: dict) -> None:
    """补齐冒烟需要的输入：运输合同给一条真实路线与载具（路线要相邻节点连通）。"""
    if contract_key != "auto-transport":
        return
    if not inputs.get("route"):
        inputs["route"] = _route_node_ids(cid, DEFAULT_ROUTE_NODES)
    if not inputs.get("vehicles"):
        inputs["vehicles"] = {"重型卡车": 2}
    if not inputs.get("cargo_weight"):
        inputs["cargo_weight"] = 20


def _route_node_ids(cid: int, names: tuple[str, ...]) -> list[int]:
    ids = []
    for name in names:
        node_id = MapNode.objects.filter(competition_id=cid, name=name).values_list("id", flat=True).first()
        if node_id is None:
            raise SystemExit(f"比赛 #{cid} 里找不到地图节点「{name}」，无法构造运输路线")
        ids.append(node_id)
    return ids


def _to_engine_dict(contract: Contract, inputs: dict) -> dict:
    """与 `apps/contracts/views.py::_contract_to_engine_dict` 同构（这里显式重建，避免依赖私有函数）。"""
    ct = contract.contract_type
    return {
        "id": contract.id,
        "competition_id": contract.competition_id,
        "parties": contract.parties,
        "inputs": json.dumps(inputs, ensure_ascii=False),
        "executed_at": contract.executed_at,
        "created_at": contract.created_at,
        "contract_type": {
            "id": ct.id,
            "effects": ct.effects,
            "conditions": ct.conditions or "[]",
            "inputSchema": ct.input_schema or "[]",
        },
    }


def _parties_text(contract: Contract) -> str:
    names = {c.id: c.name for c in Company.objects.filter(competition_id=contract.competition_id)}
    parts = []
    for p in json.loads(contract.parties or "[]"):
        who = "主办方" if p.get("isHost") else names.get(p.get("companyId"), f"#{p.get('companyId')}")
        num = p.get("contractNumber")
        parts.append(f"{p.get('role')}={who}" + (f"（{num}）" if num else ""))
    return "、".join(parts)


def _aggregate_log(log: list) -> list[dict]:
    """把逐次落账日志按「公司 + 字段」聚合成 before → after。"""
    names = {c.id: c.name for c in Company.objects.all()}
    agg: dict[tuple, dict] = {}
    for entry in log:
        if entry.get("kind") != "FIELD":
            continue
        key = (entry.get("companyId"), entry.get("fieldKey"))
        row = agg.get(key)
        if row is None:
            agg[key] = {
                "company": names.get(entry.get("companyId"), f"#{entry.get('companyId')}"),
                "field": entry.get("fieldName") or entry.get("fieldKey"),
                "before": entry.get("before"),
                "after": entry.get("after"),
                "op": entry.get("op"),
                "hits": 1,
            }
        else:
            row["after"] = entry.get("after")
            row["hits"] += 1
    return list(agg.values())


if __name__ == "__main__":
    raise SystemExit(main())
