# -*- coding: utf-8 -*-
"""Z-02 验证：Excel 建包的数值列必须有下界。

缺陷（改前）：`sheet_spec` 的数值 handler 完全没有下界校验，表里只要多一个负号就一路进归档：
距离 -3、每升单价 -7.6、容量/单价 -x、原料配比 -4、每公里油耗 -0.35、载货 -30、碳排系数 -0.5、
研发费用 -80000。下游按这些值算钱——运输合同 freight = distance * rate_per_km * trips + fuel_cost，
`distance=-3` 时运费为负，sub_number(委托方现金, 负运费) 等于**委托方加钱、承运方扣钱**，经济模型
直接算反；负配比会聚合出负数产量；负载货让「超重加价」永不触发。规范里 `distance` 用 `if not distance`
判空，于是 0 被拒、-3 放行，恰好把边界搞反。

改后：新增 `_check_num` / `_check_money` / `_check_map_min` 并在各数值 handler 中调用
（金额列以原文保留，只在「能解析成数字」时校验下界，不改变非数字原文）；坐标 x/y 明确允许负数。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_z02_excel_numeric_bounds -v 2
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.test import SimpleTestCase

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "excel"
if str(EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_DIR))

from sheet_spec import (  # noqa: E402
    SHEET_BY_NAME,
    SheetContext,
    SheetFormatError,
    _as_scalar,
)

try:  # 改前不存在这三个校验助手（数值列完全没有下界校验）
    from sheet_spec import _check_map_min, _check_money, _check_num  # noqa: E402
except ImportError:  # pragma: no cover - 仅在“改前”状态下走到
    _check_map_min = _check_money = _check_num = None


class _FakeBuilder:
    """只记录调用参数的假建包器（本用例只关心校验是否拦下）。"""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None

        return _rec


def ctx():
    return SheetContext(builder=_FakeBuilder())


class NumericBoundHelperTests(SimpleTestCase):
    def setUp(self):
        self.assertIsNotNone(_check_num, "改后应提供 _check_num/_check_money/_check_map_min（审计 Z-02）")

    def test_check_num_bounds(self):
        _check_num("distance", "3", 0, exclusive=True)      # 正数通过
        _check_num("distance", 3, 0, exclusive=True)
        with self.assertRaises(SheetFormatError):
            _check_num("distance", "-3", 0, exclusive=True)
        with self.assertRaises(SheetFormatError):
            _check_num("distance", "0", 0, exclusive=True)
        _check_num("max_cargo", "0", 0)                      # 允许 0
        with self.assertRaises(SheetFormatError):
            _check_num("max_cargo", "-30", 0)
        with self.assertRaises(SheetFormatError):
            _check_num("max_cargo", "abc", 0)
        with self.assertRaises(SheetFormatError):
            _check_num("max_cargo", "NaN", 0)

    def test_check_money_keeps_non_numeric_text(self):
        _check_money("price", "600000")                      # 数字文本：校验
        _check_money("price", "待定")                         # 非数字原文：不新增失败路径
        _check_money("price", "")
        with self.assertRaises(SheetFormatError):
            _check_money("price", "-260000")

    def test_check_map_min(self):
        _check_map_min("地点价", {"N1": "180", "N2": 200}, 0)
        with self.assertRaises(SheetFormatError):
            _check_map_min("地点价", {"N1": "-180"}, 0)
        with self.assertRaises(SheetFormatError):
            _check_map_min("配比", {"矿石": "-4"}, 0, exclusive=True)


class HandlerBoundTests(SimpleTestCase):
    """逐个表：负值必须被拦下，合法值仍然通过。"""

    def _handler(self, sheet: str):
        return SHEET_BY_NAME[sheet].handler

    def test_edge_distance(self):
        h = self._handler("地图连线")
        h(ctx(), {"from_node": "A", "to_node": "B", "distance": "3", "path_type": "公路"})
        with self.assertRaises(SheetFormatError):
            h(ctx(), {"from_node": "A", "to_node": "B", "distance": "-3", "path_type": "公路"})

    def test_fuel_price(self):
        h = self._handler("燃料")
        h(ctx(), {"name": "柴油", "price_per_liter": "7.6"})
        with self.assertRaises(SheetFormatError):
            h(ctx(), {"name": "柴油", "price_per_liter": "-7.6"})

    def test_material_carbon_and_node_prices(self):
        h = self._handler("原料")
        h(ctx(), {"name": "矿石", "carbon_emission_coefficient": "0.5", "node_prices": "N1:180"})
        with self.assertRaises(SheetFormatError):
            h(ctx(), {"name": "矿石", "carbon_emission_coefficient": "-0.5"})
        with self.assertRaises(SheetFormatError):
            h(ctx(), {"name": "矿石", "node_prices": "N1:-180"})

    def test_tech_research_cost(self):
        h = self._handler("科技")
        h(ctx(), {"name": "T1", "research_cost": "80000", "tier": "1"})
        with self.assertRaises(SheetFormatError):
            h(ctx(), {"name": "T1", "research_cost": "-80000"})
        with self.assertRaises(SheetFormatError):
            h(ctx(), {"name": "T1", "tier": "-1"})

    def test_vehicle_numbers(self):
        h = self._handler("载具")
        h(ctx(), {"name": "卡车", "fuel": "柴油", "fuel_consumption_per_km": "0.35",
                  "max_cargo": "30", "price": "260000", "carbon_emission": "0.9"})
        for bad in (
            {"fuel_consumption_per_km": "-0.35"},
            {"max_cargo": "-30"},
            {"price": "-260000"},
            {"carbon_emission": "-0.9"},
        ):
            payload = {"name": "卡车", "fuel": "柴油"}
            payload.update(bad)
            with self.assertRaises(SheetFormatError, msg=str(bad)):
                h(ctx(), payload)

    def test_part_and_product_ratio(self):
        for sheet, field in (("零件", "materials"), ("产品", "parts")):
            h = self._handler(sheet)
            h(ctx(), {"name": "P1", field: "矿石:2"})
            with self.assertRaises(SheetFormatError):
                h(ctx(), {"name": "P1", field: "矿石:-4"})

    def test_warehouse_line_infrastructure_demand(self):
        cases = [
            ("仓库", {"name": "W1", "type": "MATERIAL", "capacity": "-10"}),
            ("生产线", {"name": "L1", "price": "-100", "max_per_year": "-5"}),
            ("基建", {"name": "I1", "footprint": "-3", "price": "-1"}),
            ("消费者需求", {"region": "R", "product": "P", "quantity": "-10"}),
        ]
        for sheet, payload in cases:
            with self.assertRaises(SheetFormatError, msg=f"{sheet} {payload}"):
                self._handler(sheet)(ctx(), payload)

    def test_node_coordinates_may_be_negative(self):
        """坐标允许负数（显式声明，避免把节点画在原点左上方时被误拦）。"""
        h = self._handler("地图节点")
        h(ctx(), {"name": "N1", "node_type": "城市", "x": "-120", "y": "-80"})

    def test_as_scalar_unchanged(self):
        self.assertEqual(_as_scalar("7.6"), 7.6)
        self.assertEqual(_as_scalar("180"), 180)
        self.assertEqual(_as_scalar("待定"), "待定")
