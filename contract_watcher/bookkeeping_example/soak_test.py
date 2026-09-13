# -*- coding: utf-8 -*-
"""浸泡/稳定性测试 v2：xledit 长时间保持打开，按模式施加负载，记录失效点。

模式（环境变量 SOAK_MODE）：
  scratch —— 仅读 A1 + 写读 AA1（不调用记账、不保存）
  entry   —— 额外每 3 轮调用 add_book_entries（触发 wb.save()）
  idle    —— 每轮只读 A1（模拟"打开后长时间空闲"）
其他：SOAK_ROUNDS（默认 25）、SOAK_SLEEP（默认 0）
产物：test_output/soak_<mode>_<stamp>.xlsx 与 logs/soak_<mode>_<stamp>.jsonl
不修改 shang.py；只操作 target.xlsx 的副本。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from shang import xledit  # noqa: E402

OUT = BASE / "test_output"
LOGS = OUT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

MODE = os.environ.get("SOAK_MODE", "scratch")
ROUNDS = int(os.environ.get("SOAK_ROUNDS", "25"))
SLEEP = float(os.environ.get("SOAK_SLEEP", "0"))
DEBUG = os.environ.get("SOAK_DEBUG", "0") == "1"
RETRY = int(os.environ.get("SOAK_RETRY", "0"))   # 每轮允许的重试次数（测试侧重试，非改 shang.py）
STAMP = time.strftime("%Y%m%d_%H%M%S")
TAG = f"{MODE}{'_debug' if DEBUG else ''}"
XLSX = OUT / f"soak_{TAG}_{STAMP}.xlsx"
JSONL = LOGS / f"soak_{TAG}_{STAMP}.jsonl"

shutil.copy2(BASE / "target.xlsx", XLSX)
fh = JSONL.open("w", encoding="utf-8")


def emit(rec: dict) -> None:
    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    fh.flush()
    print(json.dumps(rec, ensure_ascii=False, default=str), flush=True)


emit({"event": "start", "mode": MODE, "debug": DEBUG, "rounds": ROUNDS, "sleep": SLEEP, "xlsx": str(XLSX)})

t_start = time.time()
book = None
ok_rounds = 0
FAILED = False          # 审计 CW-21：出现不可恢复错误时置位，用于退出码与现场保留
latencies: list[int] = []
try:
    t0 = time.time()
    book = xledit(str(XLSX), debug=DEBUG)
    emit({"event": "opened", "open_seconds": round(time.time() - t0, 1),
          "visible": bool(book.xlapp.visible)})
    sht = book.wb.sheets[0]

    for i in range(1, ROUNDS + 1):
        attempts = 0
        while True:
            attempts += 1
            try:
                t0 = time.time()
                _ = sht[0, 0].value                          # 每轮必做：读
                if MODE == "scratch":
                    sht.range("AA1").value = f"soak-{i}"
                    _ = sht.range("AA1").value
                if MODE == "entry" and i % 3 == 0:
                    book.add_book_entries(Decimal("1"), Decimal("0"), f"S{i:03d}", "浸泡测试")
                ms = round((time.time() - t0) * 1000)
                latencies.append(ms)
                ok_rounds = i
                emit({"event": "round_ok", "i": i, "ms": ms, "attempts": attempts,
                      "elapsed_s": round(time.time() - t_start, 1)})
                break
            except Exception as e:  # noqa: BLE001
                recoverable = (attempts <= RETRY)
                emit({"event": "round_fail", "i": i, "attempts": attempts,
                      "ok_rounds": ok_rounds, "will_retry": recoverable,
                      "error": f"{type(e).__name__}: {e}",
                      "trace_tail": traceback.format_exc().strip().splitlines()[-1],
                      "elapsed_s": round(time.time() - t_start, 1)})
                if not recoverable:
                    # 审计 CW-21：改前这里用「退出码 0」表示失败 —— 浸泡出现不可恢复错误时
                    # 脚本调用方/CI/任务计划仍会把它当成功。改为非零退出码，
                    # 并保留现场（临时 xlsx 与 jsonl 日志都不删），便于事后定位失效点。
                    FAILED = True
                    raise SystemExit(1)
        time.sleep(SLEEP)
    else:
        emit({"event": "completed", "rounds": ROUNDS, "elapsed_s": round(time.time() - t_start, 1)})
finally:
    try:
        if book is not None:
            book.save()
            emit({"event": "saved_ok"})
    except Exception as e:  # noqa: BLE001
        emit({"event": "save_failed", "error": f"{type(e).__name__}: {e}"})
    if latencies:
        emit({"event": "summary", "mode": MODE, "debug": DEBUG, "ok_rounds": ok_rounds,
              "max_ms": max(latencies), "avg_ms": round(sum(latencies) / len(latencies)),
              "first_ms": latencies[0], "last_ms": latencies[-1],
              "elapsed_s": round(time.time() - t_start, 1)})
    fh.close()
