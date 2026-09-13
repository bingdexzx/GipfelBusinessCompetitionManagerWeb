# -*- coding: utf-8 -*-
"""CW-15 验证：`readable.py` 的时间本地化与时区标注、数字型字符串的展示不得被改写。

缺陷（改前）：
1. `_fmt_dt` 是 `str(v)[:19].replace("T", " ")` —— 后端返回 UTC（实测 `2026-09-10T15:20:46.731818Z`），
   于是可读记录里的「执行时间」显示 `2026-09-10 15:20:46`：**比北京时间早 8 小时且没有任何时区标注**，
   跨天/跨财年的归属判读会错；也无法与 `default_archive` 用的**本地**时间戳文件名对齐。
2. `pretty_value` 对命中 `_NUM_RE` 的字符串调 `_group_int`：
   - `'+1234'` → `'1,234'`（**加号被吞**，`_group_int` 只认 `-`）；
   - `'-0012345'` → `'-0,012,345'`（**前导零导致错误分组**，正确写法是 `-12,345`）；
   - int 加千分位而 float 不加（`1234567.891` 原样输出，1e+21 输出 `'1e+21'`）——同一列展示口径不一致。

改后：
1. `_fmt_dt` 用 `datetime.fromisoformat` 解析后转**本地时区**并带偏移标注
   （`2026-09-10 23:20:46 +08:00`）；无法解析时保留原始文本并标注「无法解析」，
   不再悄悄截断成 19 字符。
2. `pretty_value`：int/float 统一加千分位；正号保留、前导零不再分组；非有限值原样输出。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe tests\\fix_verify\\watcher\\test_cw15_readable_format.py
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=ResourceWarning)

REPO = Path(__file__).resolve().parents[3]
READABLE_PY = REPO / "contract_watcher" / "readable.py"

# 固定时区：断言与运行机器的本地时区无关（UTC+8 覆盖原缺陷的「差 8 小时」场景）
UTC8 = timezone(timedelta(hours=8))


class FixedLocalDatetime(datetime):
    """`datetime.astimezone()` 默认转换到**本地**时区；这里固定为 UTC+8 以便断言。

    只有 `fromisoformat()` 返回的实例需要换成本类（模块内是 `datetime.fromisoformat(...)`）。
    """

    @classmethod
    def fromisoformat(cls, text: str) -> "FixedLocalDatetime":
        base = datetime.fromisoformat(text)
        return cls(
            base.year, base.month, base.day, base.hour, base.minute,
            base.second, base.microsecond, base.tzinfo,
        )

    def astimezone(self, tz=None):  # type: ignore[override]
        return datetime.astimezone(self, UTC8 if tz is None else tz)


def load_readable():
    spec = importlib.util.spec_from_file_location("readable_under_test", READABLE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cw15TimeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_readable()
        # 把模块内的 datetime 换成「本地时区固定 UTC+8」的替身（只影响本模块，不污染其它测试）
        self.mod.datetime = FixedLocalDatetime

    def test_utc_is_converted_to_local_with_offset(self):
        """改前：`2026-09-10T15:20:46.731818Z` → `2026-09-10 15:20:46`（UTC，无标注）。"""
        got = self.mod._fmt_dt("2026-09-10T15:20:46.731818Z")
        self.assertIn("2026-09-10 23:20:46", got, f"必须换算到本地时间，实际 {got!r}")
        self.assertIn("+08:00", got, f"必须带时区标注，实际 {got!r}")
        self.assertNotIn(
            "10 15:20:46", got,
            f"不得再按 UTC 原样显示（改前为 '2026-09-10 15:20:46'），实际 {got!r}",
        )

    def test_offset_input_is_normalised(self):
        """带 +08:00 的输入本身已是本地时间，换算后不变。"""
        got = self.mod._fmt_dt("2026-09-10T23:20:46+08:00")
        self.assertIn("2026-09-10 23:20:46", got)
        self.assertIn("+08:00", got)

    def test_date_crossing_midnight_is_visible(self):
        """跨天必须体现出来：UTC 22:30 = 北京时间次日 06:30（改前显示成前一天）。"""
        got = self.mod._fmt_dt("2026-09-10T22:30:00Z")
        self.assertIn("2026-09-11 06:30:00", got, f"实际 {got!r}")

    def test_missing_value_still_dash(self):
        """回归：空值仍输出破折号。"""
        for empty in (None, ""):
            self.assertEqual(self.mod._fmt_dt(empty), "—")

    def test_unparsable_value_is_kept_and_marked(self):
        """回归（改进）：无法解析的值保留原文并标注，不再截断成 19 字符。"""
        got = self.mod._fmt_dt("2026-09-10 15:20:46.731818 旧格式")
        self.assertIn("旧格式", got, f"原始文本不得被截断，实际 {got!r}")
        self.assertIn("无法解析", got, f"必须标注无法解析，实际 {got!r}")

    def test_readable_record_executed_at_is_localised(self):
        """端到端：可读记录里的「执行时间」字段必须是本地时间。"""
        rec = self.mod.build_readable({
            "id": 1, "competitionId": 1, "name": "T", "status": "EXECUTED",
            "contractType": {"key": "k", "name": "K"},
            "executedAt": "2026-09-10T15:20:46.731818Z",
        })
        self.assertIn("23:20:46", rec["执行时间"], f"实际 {rec['执行时间']!r}")
        self.assertIn("+08:00", rec["执行时间"])


class Cw15NumberTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_readable()

    def test_plus_sign_is_preserved(self):
        """改前：'+1234' → '1,234'（加号被吞）。"""
        self.assertEqual(self.mod.pretty_value("+1234"), "+1,234")

    def test_leading_zero_is_not_regrouped(self):
        """改前：'-0012345' → '-0,012,345'（前导零导致错误分组，看起来像另一个数）。"""
        self.assertEqual(
            self.mod.pretty_value("-0012345"), "-0012345",
            "带前导零的串一律原样返回，不得分组",
        )
        # 反向取证：去掉前导零后仍要正常分组
        self.assertEqual(self.mod.pretty_value("-12345"), "-12,345")

    def test_int_and_float_use_same_grouping(self):
        """改前：int 加千分位、float 不加，同一列口径不一致。"""
        self.assertEqual(self.mod.pretty_value(1234567), "1,234,567")
        self.assertEqual(self.mod.pretty_value(1234567.891), "1,234,567.891")
        self.assertEqual(self.mod.pretty_value("1234567.891"), "1,234,567.891")

    def test_plain_numbers_unchanged(self):
        """回归：普通数值的展示不变。"""
        self.assertEqual(self.mod.pretty_value("123.45"), "123.45")
        self.assertEqual(self.mod.pretty_value(0), "0")
        self.assertEqual(self.mod.pretty_value("0"), "0")
        self.assertEqual(self.mod.pretty_value("-5.5"), "-5.5")

    def test_non_numeric_strings_are_untouched(self):
        """回归：合同编号这类非纯数字串不得被改写。"""
        for raw in ("HT-2026-001", "1,000", "50%", "100元", "", "  "):
            self.assertEqual(self.mod.pretty_value(raw), raw.strip() if raw.strip() else raw.strip())

    def test_long_digit_string_is_not_scientific(self):
        """大额数字字符串必须保持原样（不得变成科学计数法），只加千分位。"""
        self.assertEqual(
            self.mod.pretty_value("12345678901234567890"),
            "12,345,678,901,234,567,890",
        )

    def test_non_finite_floats_are_not_mangled(self):
        """回归：nan/inf 不做千分位（改前 int/float 走 str()，inf 会原样输出）。"""
        self.assertEqual(self.mod.pretty_value(float("inf")), "inf")
        self.assertEqual(self.mod.pretty_value(float("nan")), "nan")

    def test_bool_still_chinese(self):
        self.assertEqual(self.mod.pretty_value(True), "是")
        self.assertEqual(self.mod.pretty_value(False), "否")


if __name__ == "__main__":
    unittest.main(verbosity=2)
