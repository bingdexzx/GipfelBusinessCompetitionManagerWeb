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


# ---------- Excel 进程回收（审计 CW-22：只回收本脚本自己启动的 PID） ----------
#
# 改前 `reap(new)` 对「用例期间新出现的所有 EXCEL.EXE」执行 `taskkill /F`，会连用户自己打开、
# 正在编辑的 Excel 一起强杀（未保存数据丢失）；而 `SOAK_REPORT.md:24` 又证明外部 taskkill 与
# 该环境下的 COM 崩溃高度相关，误杀还会反过来污染后续用例结论。`excel_pids()` 当时还用**固定
# 共享**的临时文件名，并发跑两个用例会互相覆盖解析结果（现已改为每次唯一命名）。
#
# 现在：只强杀「xlwings 记录到的、由本脚本打开的」PID；同时提供
# `plan_reap(present, owned, before)` 供用例断言与日志展示 —— 用户自己的 Excel 永不在回收集合里。

def excel_pids() -> set[int]:
    """当前 EXCEL.EXE 的 PID 集合（解析 tasklist 输出；临时文件已唯一化）。"""
    fd, tmp_name = tempfile.mkstemp(prefix="dsh_tasklist_", suffix=".csv")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
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
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def plan_reap(present: set[int], owned: set[int], before: set[int]) -> dict:
    """算出该强杀哪些 Excel PID（纯函数，便于用例断言）。

    - `present`：用例结束时仍然存在的 EXCEL.EXE；
    - `owned`：本脚本打开的 Excel 的 PID（由 xledger/run_case 登记）；
    - `before`：用例开始前就已存在的 PID（用户自己的 Excel 一定在这里边）。

    返回 `{"kill": 本脚本自己且仍存活的, "foreign": 用例期间出现但不属于本脚本的}`。
    改前会对 `present - before` 全部 taskkill —— 用户的 Excel 若在此期间被打开就会被误杀。
    """
    kill = sorted(p for p in present if p in owned)
    foreign = sorted(p for p in present if p not in owned and p not in before)
    return {"kill": kill, "foreign": foreign}


def register_owned(pid) -> None:
    """登记「由本脚本启动」的 Excel PID（`xledit` 会自动登记，这里是补充入口）。"""
    try:
        xledit.owned_pids.add(int(pid))
    except (TypeError, ValueError):
        pass


def reap(new_pids: set[int]) -> None:
    """只回收「本脚本自己启动」的 Excel PID；其它进程仅记录不杀。"""
    owned = set(getattr(xledit, "owned_pids", set()))
    present = excel_pids() if new_pids else set()
    plan = plan_reap(present, owned, set())
    for pid in plan["kill"]:
        os.system(f"taskkill /F /PID {pid} > nul 2>&1")
    if plan["foreign"]:
        log(f"   (警告) 以下 Excel 进程不是本脚本启动的，**未回收**（可能是你自己的 Excel）: "
            f"{plan['foreign']}")
    if plan["kill"]:
        log(f"   (已回收本脚本启动的 Excel 进程: {plan['kill']})")


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
    # 审计 CW-22：改前这里打印的「运行后」哈希其实是循环**之前**算的（`src_sha = sha(SRC)`），
    # 脚本从未验证 target.xlsx 未被改动 —— `TEST_REPORT_v2.md:8` 声称的「运行前后哈希一致」
    # 并非由脚本保障。现在重新计算并显式断言。
    src_sha_after = sha(SRC)
    log(f"原文件 SHA256（运行前）: {src_sha}")
    log(f"原文件 SHA256（运行后）: {src_sha_after}")
    if src_sha_after != src_sha:
        log("✗ 原文件 target.xlsx 在运行期间被改动（哈希不一致）：请立即检查用例实现！")
        sys.exit(1)
    log("✓ 原文件哈希一致：目标模板未被用例改动")


if __name__ == "__main__":
    main()
