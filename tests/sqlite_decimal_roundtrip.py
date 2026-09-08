# -*- coding: utf-8 -*-
"""SQLite DecimalField(max_digits=30) 大数存取往返验证（事务回滚，不残留数据）。"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402

from apps.competitions.models import Competition  # noqa: E402
from apps.fuels.models import Fuel  # noqa: E402

QUAD = Decimal("12345678901234567890123.4567")  # 1.23×10^22，28 位有效数字

with transaction.atomic():
    comp = Competition.objects.create(name="__bignum_rollback_test__")
    fuel = Fuel.objects.create(competition=comp, name="__bignum__", price_per_liter=QUAD)
    fuel.refresh_from_db()
    print("写入值：", QUAD)
    print("读回值：", fuel.price_per_liter)
    print("SQLite 存储形态：", Fuel.objects.filter(pk=fuel.pk).values_list("price_per_liter", flat=True))
    ok = fuel.price_per_liter == QUAD
    print("往返精确：", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 2)  # 事务块内 SystemExit 会触发回滚，数据不残留
