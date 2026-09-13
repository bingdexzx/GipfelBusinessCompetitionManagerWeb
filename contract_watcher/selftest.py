# -*- coding: utf-8 -*-
"""contract_watcher 离线自测（不依赖后端服务、不依赖 Excel）。

覆盖：
  1. 语法编译
  2. handlers.py 自动生成 / 幂等 / 改名（保留函数体）/ 注册表加载
  3. 文档字符串中的 @register 示例不会被误判为"已存在"
  4. readable.translate_contract 结构与中国化转换
  5. default_archive 同时产出原始 + 可读 JSON
  6. dispatch 路由（注册函数优先，未注册走默认存档）
用法：python selftest.py
"""
from __future__ import annotations

import json
import py_compile
import shutil
import sys
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


# 1) 编译
for f in ("contract_watcher.py", "readable.py", "handlers.py"):
    py_compile.compile(str(BASE / f), doraise=True)
check("语法编译", True)

import contract_watcher as cw  # noqa: E402
from readable import build_readable, register_translator, translate_contract  # noqa: E402

# 隔离到临时工作目录（不触碰真实 handlers/records）
TMP = BASE / "_selftest_tmp"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True)
cw.HANDLERS_FILE = TMP / "handlers.py"
cw.STATE_FILE = TMP / "state.json"
try:
    # 2) 生成/幂等
    cw.ensure_handlers_file()
    ok = cw.upsert_handler_for_key("material-procurement") is True
    ok = ok and cw.upsert_handler_for_key("material-procurement") is False
    text = cw.HANDLERS_FILE.read_text(encoding="utf-8")
    ok = ok and ("ContractType.key = material-procurement =====" in text)
    ok = ok and ("def handle_material_procurement_passed(contract: dict, ctx: dict)" in text)
    check("新 key 生成默认函数 + 幂等", ok)

    # 3) 文档字符串中的示例不误判（人为构造：文件含示例文本但无真实注册块）
    doc = TMP / "handlers_doc.py"
    doc.write_text('"""示例：@register("ghost-key") 仅出现在文档中"""\n', encoding="utf-8")
    cw.HANDLERS_FILE = doc
    made = cw.upsert_handler_for_key("ghost-key")
    check("文档字符串示例不误判（应生成新块）", made and "@register(\"ghost-key\")" in doc.read_text(encoding="utf-8"))
    cw.HANDLERS_FILE = TMP / "handlers.py"

    # 4) 改名保留函数体
    t = cw.HANDLERS_FILE.read_text(encoding="utf-8").replace(
        '    ctx["default_archive"](contract, ctx)',
        '    ctx["default_archive"](contract, ctx)\n    # USER_CUSTOM')
    cw.HANDLERS_FILE.write_text(t, encoding="utf-8")
    renamed = cw.rename_handler_key("material-procurement", "material-procurement-v2")
    t2 = cw.HANDLERS_FILE.read_text(encoding="utf-8")
    check("改名更新标注+函数名且保留函数体",
          renamed and "key = material-procurement-v2 =====" in t2
          and "def handle_material_procurement_v2_passed(" in t2 and "USER_CUSTOM" in t2)
    reg = cw.load_handlers()
    check("注册表加载", list(reg) == ["material-procurement-v2"] and callable(reg["material-procurement-v2"]))

    # 5) 翻译
    contract = {
        "id": 42, "competitionId": 1, "name": "原材料采购合同", "status": "EXECUTED",
        "executedAt": "2026-09-10T21:00:00+08:00", "signedAt": "2026-09-10T20:00:00+08:00",
        "createdAt": "2026-09-10T19:00:00+08:00",
        "contractType": {"key": "material-procurement-v2", "name": "原材料采购合同",
                         "partyRoles": [{"role": "甲方", "label": "甲方"}],
                         "inputSchema": [{"key": "amount", "label": "采购数量"}]},
        "parties": [{"role": "甲方", "companyId": 3, "companyName": "测试公司A",
                     "contractNumber": "T-001"}],
        "inputs": {"amount": 1000000},
        "executionLog": [{"kind": "FIELD", "companyId": 3, "fieldKey": "cash",
                          "fieldName": "现金", "op": "SUB", "value": 500000,
                          "before": 1000000, "after": 500000}],
        "executionResult": {"checks": [{"kind": "VALUE_COMPARE", "label": "金额下限",
                                        "passed": True, "detail": "值1 ≥ 值2：通过"}]},
    }
    rec = translate_contract(contract)
    check("翻译含四大块", all(k in rec for k in ("参与方", "填写内容", "前置检查", "落账明细")))
    check("翻译内容正确",
          rec["状态"] == "已执行" and rec["参与方"][0]["公司"] == "测试公司A"
          and rec["填写内容"][0]["值"] == "1,000,000"
          and rec["落账明细"][0]["字段名"] == "现金" and rec["落账明细"][0]["操作"] == "扣减")

    @register_translator("material-procurement-v2")
    def _custom(payload):
        r = build_readable(payload)
        r["附加"] = "自定义翻译生效"
        return r

    check("自定义翻译器生效", translate_contract(contract).get("附加") == "自定义翻译生效")

    # 6) 默认存档双文件 + 分发
    out = TMP / "records"
    f = cw.default_archive(contract, {"out_dir": str(out), "typeKey": "material-procurement-v2"})
    rf = f.with_name(f.stem + "_readable.json")
    check("默认存档产出原始+可读", f.exists() and rf.exists()
          and json.loads(f.read_text(encoding="utf-8"))["id"] == 42
          and "参与方" in json.loads(rf.read_text(encoding="utf-8")))
    hits = []
    cw.dispatch(contract, {"material-procurement-v2": lambda c, x: hits.append(c["id"])}, out, None)
    check("注册函数优先", hits == [42])
    cw.dispatch({"id": 99, "status": "EXECUTED", "contractType": {"key": "no-handler"},
                 "parties": [], "inputs": {}}, {}, out, None)
    unknown_dir = out / "no-handler"
    files = sorted(p.name for p in unknown_dir.glob("*.json"))
    check("未注册走默认存档（原始 + 可读 两个文件）",
          len(files) == 2 and any(n.endswith("_readable.json") for n in files), str(files))

    print(f"TOTAL PASS={PASS} FAIL={FAIL}")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

# 审计 CW-21：改前只打印 `TOTAL PASS/FAIL` 不设退出码 —— CI、任务计划、或"脚本跑完了没报错"
# 的人工判断都会把失败当成功。任一断言失败即返回 1。
sys.exit(1 if FAIL else 0)
