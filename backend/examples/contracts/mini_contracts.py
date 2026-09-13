# -*- coding: utf-8 -*-
"""最小合同类型示例：一份「简易购销合同」（教程用）。

配套 [`docs/比赛Excel建包教程.md`](../../../docs/比赛Excel建包教程.md) 的最小框架示例：
表格里的「合同类型」表只写本脚本的路径与类型标识，四份 JSON 全部由这里产出。

合同类型**一律用代码创建**（「合同类型代码化」建库，见
[`docs/CONTRACT_TYPE_BY_CODE.md`](../../../docs/CONTRACT_TYPE_BY_CODE.md)）：
具名效果（`sub_number` / `add_number`）自带字段类型契约，检查直接写比较表达式，
比手写 JSON 更难写错；而且脚本可以直接跑体检与试算。

用法
----

    cd backend

    # 静态体检（纯只读）
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/mini_contracts.py --competition <比赛id> --check

    # 试算（对每家真实公司各跑一遍，事务回滚）
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/mini_contracts.py --competition <比赛id> --trial

    # 导入（新增或按 key 更新）
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/mini_contracts.py --competition <比赛id> --import
"""
from __future__ import annotations

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from apps.contracts.builder import ContractType  # noqa: E402


def build() -> list[ContractType]:
    """返回全部合同类型（命令行与直接运行都会调用它）。"""
    return [simple_sale()]


def simple_sale() -> ContractType:
    """买方付钱、卖方收钱；买方现金不足则拒绝执行。

    演示要点：具名效果（`ct.sub_number` / `ct.add_number`）与「检查直接写比较表达式」——
    这两处正是手写 JSON 最容易写错的地方（写错时引擎会静默按 0 计算或检查恒不通过）。
    """
    ct = ContractType("mini-sale", "简易购销合同", description="买方付钱给卖方，现金不足则拒绝")

    seller = ct.party("seller", "卖方")
    buyer = ct.party("buyer", "买方")

    amount = ct.input("amount", "成交金额", "number", required=True, default="1000")

    ct.check(amount > 0, label="金额校验", error="成交金额必须大于 0")
    ct.check(buyer.field("cash") >= amount, label="付款校验", error="买方现金不足以支付货款")

    ct.sub_number(buyer.field("cash"), amount)
    ct.add_number(seller.field("cash"), amount)
    return ct


if __name__ == "__main__":  # pragma: no cover - 手动运行入口
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    import django

    django.setup()

    from apps.contracts.builder import check

    worst = 0
    for one in build():
        report = check(one)
        print()
        print(report.render())
        worst = max(worst, 0 if report.ok else 1)
    sys.exit(worst)
