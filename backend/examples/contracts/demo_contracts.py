# -*- coding: utf-8 -*-
"""合同类型代码化示例：用简单代码描述合同类型，替代可视化拖拽。

本脚本演示本库的**全部能力**，可以直接运行：

    cd backend
    .\\.venv\\Scripts\\python.exe examples/contracts/demo_contracts.py        # 自带体检
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/demo_contracts.py --competition 4 --check
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/demo_contracts.py --competition 4 --trial
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/demo_contracts.py --competition 4 --dry-run
    .\\.venv\\Scripts\\python.exe manage.py build_contract_types examples/contracts/demo_contracts.py --competition 4 --import

它会读取指定比赛的真实数据（原料名、地图节点名、产业字段），因此**体检结论是真实的**：
名字对不上、字段不存在、清单与聚合口径错配都会在体检里报出来。

把 COMPETITION_ID 换成你自己的比赛 id，或按需修改下面的字段名。
"""
from __future__ import annotations

import os
import sys

# 让脚本既能被 `manage.py build_contract_types` 加载，也能直接 `python examples/contracts/demo_contracts.py` 运行
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from apps.contracts.builder import (  # noqa: E402
    ContractType,
    number,
    snapshot,
    sum_of,
    total_price,
)

#: 换成你自己的比赛 id
COMPETITION_ID = 4

#: 示例用的产业字段 key —— 与你的「产业类型管理」里的配置对应
FIELD = {
    "cash": "cash",                  # 数值：货币资金
    "liability": "fuzhai",           # 数值：负债
    "interest": "lixi",              # 数值：利息
    "cost": "caigouchengben",        # 数值：采购成本
    "fleet_value": "cheliangjiazhi",  # 数值：车队价值
    "fleet_cargo": "zaihuoliang",    # 数值：载货量
    "carbon": "jianshaoliang",       # 数值：减碳量
    "stock": "cangku",               # 字典：库存（{名称: 数量}）
    "usage": "shiyongjilu",          # 字典：使用记录
}


def build() -> list[ContractType]:
    """返回全部合同类型。命令行与直接运行都会调用它。"""
    snap = snapshot(COMPETITION_ID)
    return [
        _steel_sale(snap),
        _bank_loan(snap),
        _logistics(snap),
    ]


def _has(snap, field_key: str) -> bool:
    """库里是否已存在该产业字段。

    **这是推荐写法**：合同类型通常在开赛前就写好，而产业字段可能还没建；
    用 `_has()` 判断后再产出效果，可以让同一个脚本在不同比赛/不同阶段都能通过体检，
    而不是先报一堆「字段不存在」。等字段建好后，自动就会生效。
    """
    return field_key in snap.all_industry_field_keys()


# ==================== 一、销售合同（最常用形态） ====================


def _steel_sale(snap) -> ContractType:
    """买方付钱、卖方交货。

    演示要点：

    - **具名效果**：`ct.sub_number` / `ct.add_number` / `ct.add_dict`
      替代「`op=ADD` 的含义取决于目标字段的运行时类型」；
    - **检查直接写比较**：`ct.check(buyer.field("cash") >= amount)`；
    - **清单取价一条口径**：`total_price(清单, at=卖方)`（地点价 → 回退市场均价，
      与引擎聚合一致，不再有第二条取价路径）。
    """
    ct = ContractType("steel-sale", "钢材销售合同", description="买方以货币资金支付货款")

    seller = ct.party("seller", "卖方")
    buyer = ct.party("buyer", "买方")

    amount = ct.input("amount", "成交金额", "number", required=True, default="100000")
    plate = ct.input("plate", "采购清单", "materialList", party=seller, required=True)

    # 前置检查：钱要够（字段已建时才产出，避免字段还没建就报体检）
    if _has(snap, FIELD["cash"]):
        ct.check(buyer.field(FIELD["cash"]) >= amount, error="买方货币资金不足，无法支付货款")
        # 落账：一手交钱一手交货
        ct.sub_number(buyer.field(FIELD["cash"]), amount)
        ct.add_number(seller.field(FIELD["cash"]), amount)

    # 库存是字典字段 → 必须用字典效果（数值效果在字典字段上语义不同）
    if _has(snap, FIELD["stock"]):
        ct.add_dict(seller.field(FIELD["stock"]), {"钢材": 1})
    # 采购成本按卖方所在地取价（聚合口径：地点价 → 无则市场均价）
    if _has(snap, FIELD["cost"]):
        ct.add_number(seller.field(FIELD["cost"]), total_price(plate, at=seller))

    return ct


# ==================== 二、贷款合同（条件分支 + 输入项显隐） ====================


def _bank_loan(snap) -> ContractType:
    """银行贷款：按产业类型差异化利率。

    演示要点：

    - `with ct.when(...) / with ct.otherwise():` 产出**一条** IF（then/else 两个分支），
      而不是两条并列效果；
    - 输入项条件显隐：`when=` 让「每期还款额」只在期数 > 1 时出现。
    """
    ct = ContractType("bank-loan", "银行贷款合同", description="按产业类型差异化利率")

    bank = ct.party("bank", "银行", is_host=True)  # 主办方：不需要选公司
    borrower = ct.party("borrower", "借款方")

    principal = ct.input("principal", "贷款本金", "number", required=True, default="500000")
    months = ct.input("months", "期数", "number", required=True, default="12")
    per_period = ct.input("per_period", "每期还款额", "number", when=months > 1)
    penalty = ct.input("penalty", "违约金", "number")

    ct.check(principal > 0, error="贷款本金必须大于 0")

    # 到账
    if _has(snap, FIELD["cash"]):
        ct.add_number(borrower.field(FIELD["cash"]), principal)
    if _has(snap, FIELD["liability"]):
        ct.add_number(borrower.field(FIELD["liability"]), principal)

    # 差异化利率：同一份模板被不同产业的公司使用时走不同分支
    if _has(snap, FIELD["interest"]):
        with ct.when(borrower.is_industry(1)):
            ct.add_number(borrower.field(FIELD["interest"]), principal * number("0.045"))
        with ct.otherwise():
            ct.add_number(borrower.field(FIELD["interest"]), principal * number("0.060"))

    return ct


# ==================== 三、物流合同（清单聚合 + 循环） ====================


def _logistics(snap) -> ContractType:
    """运输合同：按载具清单算总价与总载重。

    演示要点：

    - **聚合函数化**：`sum_of(清单, "price")` / `sum_of(清单, "maxCargo")`
      替代 `VEHICLE_TOTAL_PRICE` / `VEHICLE_CARGO` 这些端口名——
      属性名与「数据管理」界面里的字段名一致；
    - `for_each` 遍历清单：清单是 `{名称: 数量}` 字典，循环变量拿到**名称**，
      数量用 `ct.item("清单key")` 取；
    - 基建减碳合计同样是 `sum_of(清单, "carbonReductionBonus")`。
    """
    ct = ContractType("logistics", "物流运输合同", description="按载具与基建计价")

    carrier = ct.party("carrier", "承运方")
    client = ct.party("client", "委托方")

    vehicles = ct.input("vehicles", "载具清单", "vehicleList", required=True)
    infras = ct.input("infra", "基建清单", "infrastructureList")
    price = ct.input("price", "运费总额", "number", required=True, default="8000")

    ct.check(price >= 0, error="运费不能为负")

    # 付款
    if _has(snap, FIELD["cash"]):
        ct.sub_number(client.field(FIELD["cash"]), price)
        ct.add_number(carrier.field(FIELD["cash"]), price)

    # 车队价值 / 总载重（同一函数、不同属性，替代 VEHICLE_TOTAL_PRICE / VEHICLE_CARGO 两个端口名）
    if _has(snap, FIELD["fleet_value"]):
        ct.add_number(carrier.field(FIELD["fleet_value"]), sum_of(vehicles, "price"))
    if _has(snap, FIELD["fleet_cargo"]):
        ct.add_number(carrier.field(FIELD["fleet_cargo"]), sum_of(vehicles, "maxCargo"))
    # 基建减碳加成合计
    if _has(snap, FIELD["carbon"]):
        ct.add_number(client.field(FIELD["carbon"]), sum_of(infras, "carbonReductionBonus"))

    # 逐台登记使用次数：循环变量是载具名，直接当字典键用
    if _has(snap, FIELD["usage"]):
        with ct.for_each(vehicles, var="name"):
            ct.add_dict(carrier.field(FIELD["usage"]), {"运输次数": 1})

    return ct


# ==================== 直接运行：打印体检结论 ====================


if __name__ == "__main__":  # pragma: no cover - 手动运行入口
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    import django

    django.setup()

    from apps.contracts.builder import check

    snap = snapshot(COMPETITION_ID)
    print(f"比赛 #{COMPETITION_ID}：{len(snap.companies())} 家公司、"
          f"{len(snap.names('MATERIAL'))} 种原料、{len(snap.names('VEHICLE'))} 种载具")
    worst = 0
    for ct in build():
        report = check(ct, snap=snap)
        print()
        print(report.render())
        worst = max(worst, 1 if not report.ok else 0)
    sys.exit(worst)
