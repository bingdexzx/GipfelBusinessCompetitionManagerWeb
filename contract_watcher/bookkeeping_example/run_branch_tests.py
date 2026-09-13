# -*- coding: utf-8 -*-
"""shang.py 分支实测（按用例独立运行版）。

用法：python run_branch_tests.py <case> [<case> ...]   不带参数=全部
产物：test_output/<case>.xlsx（保留）、test_output/logs/<case>.log|json（保留）
安全性：只复制原 target.xlsx 操作；每个用例结束自动回收本用例新启动的 Excel 进程。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "target.xlsx"
OUT = BASE / "test_output"
LOGS = OUT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BASE))

from shang import ASSET, BOOOKTYPE, EQUITY, LIABILITIES, things, xledit  # noqa: E402

REC: list[dict] = []
LOG_FH = None


def log(msg: str) -> None:
    print(msg, flush=True)
    if LOG_FH:
        LOG_FH.write(msg + "\n")
        LOG_FH.flush()


def rec(case: str, step: str, data=None, error: str | None = None, output: str | None = None):
    REC.append({"case": case, "step": step, "data": data, "error": error, "output": output})
    tail = (error.strip().splitlines()[-1] if error else "")
    log(f"[{'ERR ' if error else 'ok  '}] {case} :: {step}" + (f" -> {tail[:200]}" if tail else ""))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def new_case(name: str) -> Path:
    dst = OUT / f"{name}.xlsx"
    if dst.exists():
        dst.unlink()
    shutil.copy2(SRC, dst)
    return dst


# ---------- Excel 进程回收（仅回收本用例期间新出现的） ----------
def excel_pids() -> set[int]:
    tmp = Path(tempfile.gettempdir()) / "dsh_tasklist_out.txt"
    os.system(f'tasklist /FI "IMAGENAME eq EXCEL.EXE" /FO CSV > "{tmp}"')
    pids: set[int] = set()
    try:
        for line in tmp.read_text(encoding="gbk", errors="ignore").splitlines()[1:]:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(int(parts[1]))
    except FileNotFoundError:
        pass
    return pids


def reap(new_pids: set[int]) -> None:
    for pid in new_pids:
        os.system(f"taskkill /F /PID {pid} > nul 2>&1")
    if new_pids:
        log(f"   (已回收 Excel 进程: {sorted(new_pids)})")


def cell(sht, r: int, c: int):
    try:
        rng = sht[r, c]
        return {"value": rng.value, "formula": rng.formula}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def dump_rows(sht, r1: int, r2: int, c1: int, c2: int):
    out = []
    for r in range(r1, r2 + 1):
        row = {}
        for c in range(c1, c2 + 1):
            v = cell(sht, r, c)
            if v.get("value") is not None or v.get("formula"):
                row[f"r{r}c{c}"] = v
        if row:
            out.append(row)
    return out


def find_row(sht, name: str, limit: int):
    for r in range(1, limit + 1):
        v = cell(sht, r, 1)
        if v.get("value") == name:
            return r
    return None


# ==================== 用例实现 ====================

def case_05_usedrange():
    case = "05_usedrange"
    p = new_case(case)
    b = xledit(str(p), debug=False)
    try:
        info = []
        for i in range(12):
            s = b.wb.sheets[i]
            try:
                info.append({"sheet": i, "name": s.name,
                             "last_row": s.used_range.last_cell.row,
                             "last_col": s.used_range.last_cell.column})
            except Exception as e:  # noqa: BLE001
                info.append({"sheet": i, "error": f"{type(e).__name__}: {e}"})
            log(f"  sheet[{i}] {info[-1]}")
        rec(case, "12 张表 used_range", info)
    finally:
        b.save()


def case_00_probe():
    case = "00_probe"
    p = new_case(case)
    b = xledit(str(p), debug=False)
    try:
        sht = b.wb.sheets[0]
        probe = {f"{rc}": cell(sht, rc[0], rc[1]) for rc in [(0, 0), (1, 1), (2, 2), (0, 2), (2, 0)]}
        rec(case, "0 基索引探测（0 是否合法）", probe)
        rec(case, "used_range.last_cell", {"row": sht.used_range.last_cell.row})
    finally:
        b.save()


def case_01_error_path():
    try:
        xledit(str(OUT / "__not_exists__.xlsx"), debug=False)
        rec("01_error_path", "不存在的文件应报错", data="未抛出异常（非预期）")
    except Exception as e:  # noqa: BLE001
        rec("01_error_path", "不存在的文件", error=f"{type(e).__name__}: {e}")


def case_10_bank_entries():
    case = "10_bank_entries"
    p = new_case(case)
    b = xledit(str(p), debug=False)
    try:
        sht = b.wb.sheets[0]
        rec(case, "初始 last_row", sht.used_range.last_cell.row)
        for step, add, minus, num, about in [
            ("add!=0", Decimal("1000"), Decimal("0"), "C001", "合同收款"),
            ("minus!=0", Decimal("0"), Decimal("300"), "C002", "合同付款"),
            ("add=minus=0", Decimal("0"), Decimal("0"), "C003", "空值"),
        ]:
            try:
                b.add_book_entries(add, minus, num, about)
                rec(case, f"add_book_entries({step})", "ok")
            except Exception:
                rec(case, f"add_book_entries({step})", error=traceback.format_exc())
        rec(case, "调用后 last_row", sht.used_range.last_cell.row)
        rec(case, "entries_to_assets_money", getattr(b, "entries_to_assets_money", None))
        b.wb.app.calculate()
        rec(case, "第2-8行 A-G 快照", dump_rows(sht, 2, 8, 0, 7) or dump_rows(sht, 2, 8, 1, 7))
    finally:
        b.save()


def case_20_item_raw():
    _item_case("20_item_raw", things.RAWMETRIAL, 1, "测试原料A")


def case_30_item_part():
    _item_case("30_item_part", things.COMPENT, 2, "测试零件A")


def case_31_item_product():
    _item_case("31_item_product", things.PORDUCT, 3, "测试商品A")


def _item_case(case: str, thing, sheet_i: int, name: str):
    p = new_case(case)
    b = xledit(str(p), debug=False)
    try:
        sht = b.wb.sheets[sheet_i]
        rec(case, "初始 last_row", sht.used_range.last_cell.row)
        try:
            b.add_book_item(thing, name, 100, Decimal("50"), True, False)
            rec(case, "新建物料 add=True", "ok")
        except Exception:
            rec(case, "新建物料 add=True", error=traceback.format_exc())
        b.wb.app.calculate()
        last = sht.used_range.last_cell.row
        row = find_row(sht, name, last + 10)
        rec(case, "物料行定位", {"last_row": last, "name_row": row})
        if row:
            rec(case, "物料块（新建后）", dump_rows(sht, max(1, row - 2), row + 4, 1, 12))
        try:
            b.add_book_item(thing, name, 50, Decimal("60"), True, False)
            rec(case, "已有物料 add=True（插行分支）", "ok")
        except Exception:
            rec(case, "已有物料 add=True（插行分支）", error=traceback.format_exc())
        try:
            b.add_book_item(thing, name, 30, Decimal("0"), False, True)
            rec(case, "已有物料 minus=True（出库分支）", "ok")
        except Exception:
            rec(case, "已有物料 minus=True（出库分支）", error=traceback.format_exc())
        b.wb.app.calculate()
        last2 = sht.used_range.last_cell.row
        row2 = find_row(sht, name, last2 + 10)
        if row2:
            rec(case, "物料块（三次调用后）", dump_rows(sht, row2, row2 + 10, 1, 12))
    finally:
        b.save()


def case_40_assets():
    case = "40_assets"
    p = new_case(case)
    b = xledit(str(p), debug=False)
    try:
        for bt, sheet_i, name, tag in [
            (BOOOKTYPE.ASSETS, 4, ASSET.BANK_DEPOSITS, "资产-银行存款"),
            (BOOOKTYPE.LIABILITIES, 5, LIABILITIES.SHORT_TERM_LOANS, "负债-短期借款(应互换)"),
            (BOOOKTYPE.EQUITY, 6, EQUITY.PRODUCT_SALES_REVENUE, "损益-产品销售收入(应互换)"),
        ]:
            try:
                b.add_book_assets(bt, name, Decimal("500"), Decimal("0"))
                rec(case, f"{tag} add=500, minus=0", "ok")
            except Exception:
                rec(case, f"{tag} add=500, minus=0", error=traceback.format_exc())
            sht = b.wb.sheets[sheet_i]
            hits = []
            for r in range(1, 80):
                for c in range(1, 14):
                    if cell(sht, r, c).get("value") == name.value:
                        hits.append((r, c))
            rec(case, f"{tag} 科目定位", [f"r{r}c{c}" for r, c in hits[:2]])
            if hits:
                rr, cc = hits[0]
                rec(case, f"{tag} 写入块", dump_rows(sht, rr, rr + 3, max(1, cc - 1), cc + 3))
    finally:
        b.save()


def case_50_check_branches():
    case = "50_check_branches"
    p = new_case(case)
    b = xledit(str(p), debug=False)
    try:
        sht = b.wb.sheets[7]
        rec(case, "H80 原始", cell(sht, 80, 8))
        for force in (0, 1, -1):
            sht.range("H80").value = force
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    b.check()
                rec(case, f"check() H80={force}", output=buf.getvalue().strip())
            except Exception:
                rec(case, f"check() H80={force}", error=traceback.format_exc(), output=buf.getvalue())
    finally:
        b.save()


def case_60_debug_visible():
    case = "60_debug_visible"
    p = new_case(case)
    b = xledit(str(p), debug=True)
    try:
        rec(case, "debug=True 实例化", {"visible": bool(b.xlapp.visible),
                                        "ScreenUpdating": b.xlapp.api.ScreenUpdating})
    finally:
        b.save()


CASES = {
    "05_usedrange": case_05_usedrange,
    "00_probe": case_00_probe,
    "01_error_path": case_01_error_path,
    "10_bank_entries": case_10_bank_entries,
    "20_item_raw": case_20_item_raw,
    "30_item_part": case_30_item_part,
    "31_item_product": case_31_item_product,
    "40_assets": case_40_assets,
    "50_check_branches": case_50_check_branches,
    "60_debug_visible": case_60_debug_visible,
}


def main() -> None:
    global LOG_FH
    names = sys.argv[1:] or list(CASES)
    src_sha = sha(SRC)
    for name in names:
        fn = CASES.get(name)
        if fn is None:
            log(f"未知用例: {name}")
            continue
        REC.clear()
        LOG_FH = (LOGS / f"{name}.log").open("w", encoding="utf-8")
        before = excel_pids()
        t0 = time.time()
        log(f"===== CASE {name} 开始 =====")
        try:
            fn()
        except Exception:
            rec(name, "用例整体异常", error=traceback.format_exc())
        spent = time.time() - t0
        reap(excel_pids() - before)
        log(f"===== CASE {name} 结束（{spent:.1f}s，异常 {sum(1 for r in REC if r['error'])} 条）=====")
        (LOGS / f"{name}.json").write_text(
            json.dumps({"case": name, "seconds": round(spent, 1), "records": REC},
                       ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        LOG_FH.close()
        LOG_FH = None
    log(f"原文件 SHA256（运行后）: {src_sha}")


if __name__ == "__main__":
    main()
