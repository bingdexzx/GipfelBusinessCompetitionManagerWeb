# -*- coding: utf-8 -*-
"""汽车产业链测试赛 · 三大合同类型：开采 / 购销 / 运输。

配套比赛建包脚本：[`examples/competitions/auto_chain_competition.py`](../competitions/auto_chain_competition.py)
（那个脚本会把本文件产出的三个合同类型连同比赛数据一起装进目标比赛）。

产业链与合同的分工
------------------

    原料开采 ──运输──▶ 零部件加工 ──运输──▶ 整车进销
       │                   │                  │
     开采合同            购销合同            购销合同
       └────────────── 运输合同（任意两方）──────────────┘

| 合同类型 | key | 参与方 | 业务 |
| --- | --- | --- | --- |
| 开采合同 | `auto-mining` | 矿区管理方（主办方）+ 开采企业 | 缴权利金与环保费 → 扣配额 → 原矿入库 → 计提碳排 |
| 购销合同 | `auto-purchase-sale` | 卖方 + 买方 | 按卖方所在地价结算货款 → 货物出库/入库（原料与零件共用同一模板） |
| 运输合同 | `auto-transport` | 委托方 + 承运方 | 按最短路径路程 × 运价计费 → 超重加价 → 路程与碳排入账 |

三个合同只读写**三大产业共用的那套字段 key**（见下面的 `F`），因此同一个模板
可以被链上任意一环的公司使用，`--trial` 对每一家公司都能跑通。

运行
----

    cd backend

    # 1) 静态体检（纯只读：不写库、不跑引擎；带上比赛 id 可校验字段是否存在）
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/auto_chain_contracts.py --competition <比赛id> --check

    # 2) 试算（真实引擎 + 真实公司，事务整体回滚）
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/auto_chain_contracts.py --competition <比赛id> --trial

    # 3) 真正导入（新增或按 key 更新；幂等）
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/auto_chain_contracts.py --competition <比赛id> --import

    # 4) 直接跑（自带体检；比赛 id 取环境变量 AUTO_CHAIN_COMPETITION_ID）
    .\\.venv\\Scripts\\python.exe examples/contracts/auto_chain_contracts.py
"""
from __future__ import annotations

import os
import sys

# 既支持 `manage.py build_contract_types` 加载，也支持直接 `python examples/contracts/auto_chain_contracts.py`
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from apps.contracts.builder import (  # noqa: E402
    ContractType,
    company_name,
    input_value,
    number,
    range_list,
    route_distance,
    snapshot,
    sum_of,
    total_price,
    total_qty,
    var,
)

#: 体检/试算用的比赛 id（直接运行时可用环境变量覆盖）
COMPETITION_ID = int(os.environ.get("AUTO_CHAIN_COMPETITION_ID") or 0)

#: 三大产业共用的产业字段 key —— 与建包脚本 `auto_chain_competition.py` 的 `COMMON_FIELDS` 一一对应。
#: 合同只引用这些 key，所以「开采 / 加工 / 进销」任一环节的公司都能签同一份合同。
F = {
    "cash": "cash",                       # NUMBER  现金
    "quota": "quota",                     # NUMBER  许可配额（开采量 / 产能 / 销量配额）
    "inventory": "inventory",             # DICT    库存台账 {物资: 数量}
    "ledger": "ledger",                   # DICT    业务台账 {业务: 次数}
    "carbon": "carbon",                   # NUMBER  碳排放
    "contract_amount": "contract_amount",  # NUMBER  累计合同额
    "transport_km": "transport_km",       # NUMBER  累计运输里程
    "last_deal": "last_deal",             # STRING  最近业务摘要
}


def build() -> list[ContractType]:
    """返回三大合同类型（命令行与直接运行都会调用它）。"""
    return [
        mining_contract(),
        purchase_sale_contract(),
        transport_contract(),
    ]


# =============================================================================
# 一、开采合同：配额 + 权利金 + 环保费 + 原矿入库
# =============================================================================


def mining_contract() -> ContractType:
    """矿区管理方（主办方）出让开采权，开采企业缴费、扣配额、入库原矿。

    难点：**把「数量」写进字典字段**
        引擎的字典效果只接受字面量键与字面量值（动态值会被引擎当成数据写坏），
        所以「入库 N 吨」用**循环 N 次、每次 +1** 表达（`range_list` + `for_each`）。
        键是字面量 `原矿`，数量由循环次数决定 —— 这是引擎既有语义下的标准写法。
    """
    ct = ContractType(
        "auto-mining",
        "开采合同",
        description="开采企业向矿区管理方缴纳权利金与环保费，扣减许可配额并把原矿入库",
    )

    authority = ct.party("authority", "矿区管理方", is_host=True)  # 主办方：不绑公司，只作为合同对手方展示
    miner = ct.party("miner", "开采企业")

    ore_type = ct.input("ore_type", "开采矿种", "string", required=True, default="锂矿石")
    quantity = ct.input("quantity", "本期开采量（吨）", "number", required=True, default="20")
    royalty_rate = ct.input("royalty_rate", "单位权利金（元/吨）", "number", required=True, default="60")
    env_fee_rate = ct.input("env_fee_rate", "单位环保费（元/吨）", "number", default="8")
    carbon_factor = ct.input("carbon_factor", "吨矿碳排系数", "number", default="0.5")

    fee = quantity * (royalty_rate + env_fee_rate)      # 权利金 + 环保费
    carbon_add = quantity * carbon_factor               # 开采环节碳排

    ct.check(quantity > 0, label="开采量校验", error="本期开采量必须大于 0")
    ct.check(miner.field(F["quota"]) >= quantity, label="配额校验", error="许可配额不足，请先申请追加配额")
    ct.check(miner.field(F["cash"]) >= fee, label="缴费校验", error="货币资金不足以缴纳权利金与环保费")

    # 资金流与配额
    ct.sub_number(miner.field(F["cash"]), fee)
    ct.sub_number(miner.field(F["quota"]), quantity)
    # 碳排与统计
    ct.add_number(miner.field(F["carbon"]), carbon_add)
    ct.add_number(miner.field(F["contract_amount"]), fee)
    ct.set_value(miner.field(F["last_deal"]), input_value(ore_type))

    # 入库：逐吨登记（字典效果的值必须是字面量，数量用循环表达）
    with ct.for_each(range_list(number("1"), quantity + number("1")), var="unit"):
        ct.add_dict(miner.field(F["inventory"]), {"原矿": 1})

    ct.add_dict(miner.field(F["ledger"]), {"开采批次": 1})
    return ct


# =============================================================================
# 二、购销合同：地点价结算 + 双向库存与台账
# =============================================================================


def purchase_sale_contract() -> ContractType:
    """卖方向买方交货、买方付款；原料与零件共用同一份模板。

    难点一：**地点价口径**
        `total_price(货物清单, at=seller)` = 「卖方所在地价 → 回退市场均价」，
        与引擎聚合同一条口径（写 `at=` 才不会静默变成均价）。

    难点二：**一份清单驱动四处落账**
        货款（双方现金）、双方累计合同额、双方台账、双方库存（出库 / 入库）。
    """
    ct = ContractType(
        "auto-purchase-sale",
        "购销合同",
        description="按卖方所在地价结算货款，货物出库 / 入库并登记双方台账",
    )

    seller = ct.party("seller", "卖方")
    buyer = ct.party("buyer", "买方")

    #: 货物清单按**卖方所在地**取价，且清单类型决定了聚合口径
    goods = ct.input("goods", "交易货物清单", "materialList", party=seller, required=True,
                     default={"锂矿石": 20})
    discount = ct.input("discount", "折让比例（0~1）", "number", default="0")

    qty = total_qty(goods)
    amount = total_price(goods, at=seller)
    payable = amount * (number("1") - discount)

    ct.check(qty > 0, label="清单校验", error="交易货物清单不能为空")
    ct.check(buyer.field(F["cash"]) >= payable, label="付款校验", error="买方货币资金不足以支付货款")

    # 资金流
    ct.sub_number(buyer.field(F["cash"]), payable)
    ct.add_number(seller.field(F["cash"]), payable)
    ct.add_number(buyer.field(F["contract_amount"]), payable)
    ct.add_number(seller.field(F["contract_amount"]), payable)
    # 双方摘要记的是对手方公司名
    ct.set_value(seller.field(F["last_deal"]), company_name(buyer))
    ct.set_value(buyer.field(F["last_deal"]), company_name(seller))

    # 库存：卖方出库、买方入库，逐件登记（字典效果的值必须是字面量）
    with ct.for_each(range_list(number("1"), qty + number("1")), var="unit"):
        ct.sub_dict(seller.field(F["inventory"]), {"货物": 1})
        ct.add_dict(buyer.field(F["inventory"]), {"货物": 1})

    ct.add_dict(seller.field(F["ledger"]), {"销售批次": 1})
    ct.add_dict(buyer.field(F["ledger"]), {"采购批次": 1})
    return ct


# =============================================================================
# 三、运输合同：最短路径计价 + 超重加价 + 里程入账
# =============================================================================


def transport_contract() -> ContractType:
    """承运方按实际路程与载具计费，超重加价，并把里程与碳排入账。

    难点一：**路程是图上的最短路径**
        `route_distance(路线)` 由引擎用 Dijkstra 求相邻节点间最短路（不是简单相加）。

    难点二：**条件改写金额**
        超重时运费 ×1.1；改写用 `assign` 存中间值，后续效果引用同一变量。

    注意：**这里刻意不写「路程必须大于 0」的前置检查**。`nodeRoute` 输入项在没有
    默认值时是空列表，把它写成阻断检查会让 `--trial`（用默认值跑真实公司）永远失败；
    路线合法性由创建合同时的节点链路校验负责（前端会校验相邻节点必须有连线）。
    """
    ct = ContractType(
        "auto-transport",
        "运输合同",
        description="按最短路径路程与载具计费，超重加价，里程与碳排计入台账",
    )

    client = ct.party("client", "委托方")
    carrier = ct.party("carrier", "承运方")

    route = ct.input("route", "运输路线", "nodeRoute", required=True)
    vehicles = ct.input("vehicles", "使用载具", "vehicleList", required=True, default={})
    cargo_weight = ct.input("cargo_weight", "货物总重（吨）", "number", default="0")
    rate_per_km = ct.input("rate_per_km", "单公里运价（元/公里）", "number", required=True, default="12")
    trips = ct.input("trips", "车次", "number", default="1")
    carbon_tax_rate = ct.input("carbon_tax_rate", "碳税税率", "number", default="0.05")

    distance = route_distance(route)
    capacity = sum_of(vehicles, "maxCargo")
    fuel_cost = sum_of(vehicles, "fuelConsumptionPerKm") * distance
    carbon_amt = sum_of(vehicles, "carbonEmission") * distance
    freight = distance * rate_per_km * trips + fuel_cost
    carbon_tax = carbon_amt * carbon_tax_rate

    ct.check(rate_per_km >= 0, label="运价校验", error="单公里运价不能为负")
    ct.check(cargo_weight >= 0, label="货重校验", error="货物总重不能为负")
    # 用原始值源比较（不要用 assign 出来的变量：前置检查在效果之前求值，那时变量还不存在）
    ct.check(client.field(F["cash"]) >= freight + carbon_tax, label="运费校验",
             error="委托方货币资金不足以支付运费与碳税")

    ct.assign("freight", freight)
    with ct.when(cargo_weight > capacity):
        # 超重加价 10%
        ct.assign("freight", var("freight") * number("1.1"))

    ct.sub_number(client.field(F["cash"]), var("freight") + carbon_tax)
    ct.add_number(carrier.field(F["cash"]), var("freight"))
    ct.add_number(carrier.field(F["contract_amount"]), var("freight"))
    ct.add_number(client.field(F["transport_km"]), distance)
    ct.add_number(carrier.field(F["transport_km"]), distance)
    ct.add_number(carrier.field(F["carbon"]), carbon_amt)
    ct.set_value(carrier.field(F["last_deal"]), company_name(client))
    ct.set_value(client.field(F["last_deal"]), company_name(carrier))

    ct.add_dict(carrier.field(F["ledger"]), {"运输批次": 1})
    ct.add_dict(client.field(F["ledger"]), {"托运批次": 1})
    return ct


# =============================================================================
# 直接运行：打印体检结论（不写库）
# =============================================================================


if __name__ == "__main__":  # pragma: no cover - 手动运行入口
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    import django

    django.setup()

    from apps.contracts.builder import check

    snap = None
    if COMPETITION_ID:
        snap = snapshot(COMPETITION_ID)
        print(f"比赛 #{COMPETITION_ID}：{len(snap.companies())} 家公司、"
              f"{len(snap.names('MATERIAL'))} 种原料、{len(snap.names('VEHICLE'))} 种载具")
    else:
        print("未设置 AUTO_CHAIN_COMPETITION_ID：只做不依赖比赛数据的结构体检"
              "（字段是否存在需要比赛 id 才能校验）")

    worst = 0
    for one in build():
        report = check(one, snap=snap)
        print()
        print(report.render())
        worst = max(worst, 0 if report.ok else 1)
    sys.exit(worst)
