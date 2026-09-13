# -*- coding: utf-8 -*-
"""R-10 验证：覆盖模式必须真的按归档更新「股票」与「资金账户」。

缺陷（改前）：这两类资源在「已存在」时永远走 `skipped` 分支，归档值被完全忽略：
  - 股票：初始价 / 总股本 / 行业 PE / 当前价 / 轮次等行情参数不会被刷新；
  - 资金账户：现金余额不会被刷新 —— 而清单里明确写「开赛前是最后一次可自由设定」。
用户在前端选「覆盖（已存在的按归档更新）」后，统计只显示 skipped（不是 problem），
rollup 里 `updated=0` 也容易被忽略，于是以为覆盖成功。

改后：覆盖模式下按归档更新上述字段并记 `updated`；追加模式行为不变。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r10_overwrite_stock_accounts -v 2
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.test import TestCase

from apps.companies.models import Company
from apps.competitions.models import Competition
from apps.industry_types.models import IndustryType
from apps.preparation import archive
from apps.regions.models import Region
from apps.stock.models import Stock, StockFundsAccount
from apps.users.models import User


class OverwriteStockAndAccountTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R10-目标比赛")
        self.admin = User(
            username="r10-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R10Pw!123")
        self.admin.save()

        self.industry = IndustryType.objects.create(code=9404, name="R10产业")
        self.region = Region.objects.create(competition=self.comp, name="R10区")
        self.company = Company.objects.create(
            competition=self.comp, name="R10公司", industry_type=self.industry, region=self.region
        )
        self.stock = Stock.objects.create(
            code="R10", name="R10股", total_shares=Decimal("1000"), init_net_profit=Decimal("100"),
            industry_pe=10, current_carbon=0, industry_avg_carbon=0, happiness=50,
            init_price=Decimal("10"), current_price=Decimal("10"), round=0,
            competition=self.comp, company=self.company,
        )
        self.account = StockFundsAccount.objects.create(
            name="R10账户", owner_type="COMPANY", company_id=self.company.id,
            cash_balance=Decimal("0"), competition=self.comp,
        )

    def _payload(self):
        return {
            "resources": {
                "companies": {"rows": [{"_id": 1, "name": "R10公司", "industryTypeCode": 9404}]},
                "stocks": {
                    "rows": [
                        {
                            "_id": 1,
                            "code": "R10",
                            "name": "R10股",
                            "companyName": "R10公司",
                            "totalShares": "2000",
                            "initNetProfit": "200",
                            "initPrice": "25",
                            "currentPrice": "25",
                            "industryPe": "12",
                            "happiness": "60",
                            "round": "0",
                        }
                    ]
                },
                "stockFundsAccounts": {
                    "rows": [
                        {
                            "_id": 1,
                            "name": "R10账户",
                            "ownerType": "COMPANY",
                            "companyName": "R10公司",
                            "cashBalance": "88888",
                        }
                    ]
                },
            }
        }

    def _import(self, mode):
        return archive.apply_import(
            self._payload(),
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode=mode,
            user=self.admin,
        )

    def test_overwrite_updates_stock_and_account(self):
        result = self._import("overwrite")
        self.stock.refresh_from_db()
        self.account.refresh_from_db()

        self.assertEqual(self.stock.total_shares, Decimal("2000"), "覆盖模式应更新总股本")
        self.assertEqual(self.stock.init_price, Decimal("25"), "覆盖模式应更新初始价")
        self.assertEqual(self.stock.current_price, Decimal("25"), "覆盖模式应更新当前价")
        self.assertEqual(self.stock.industry_pe, 12, "覆盖模式应更新行业 PE")
        self.assertEqual(self.stock.happiness, 60, "覆盖模式应更新幸福度")
        self.assertEqual(
            self.account.cash_balance, Decimal("88888"),
            "覆盖模式应更新资金账户现金余额（开赛前最后一次可自由设定的字段）",
        )

        rows = {r["resource"]: r for r in result["resources"]}
        self.assertEqual(rows.get("stocks", {}).get("updated"), 1, f"统计应记 updated：{rows.get('stocks')}")
        self.assertEqual(rows.get("stockFundsAccounts", {}).get("updated"), 1)

    def test_append_mode_keeps_existing_values(self):
        """回归：追加模式不得改动既有行情参数与余额。"""
        self._import("append")
        self.stock.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.stock.total_shares, Decimal("1000"))
        self.assertEqual(self.stock.init_price, Decimal("10"))
        self.assertEqual(self.account.cash_balance, Decimal("0"))
