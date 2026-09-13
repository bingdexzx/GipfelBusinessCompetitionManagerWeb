# -*- coding: utf-8 -*-
"""xlsx 离线解析工具（标准库，无需 Excel/xlwings）。

用法示例：
    python inspect_xlsx.py <xlsx> --sheets                      # 列出工作表与 dimension
    python inspect_xlsx.py <xlsx> "银行流水账" 1 12 1 8          # 打印区域（值+公式）
    python inspect_xlsx.py <xlsx> --find "短期借款"             # 全表定位某文本
"""
from __future__ import annotations

import sys
import zipfile
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def load(path: str):
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid2t = {r.get("Id"): r.get("Target") for r in rels}
    sheets = []
    for s in wb.find("m:sheets", NS):
        rid = s.get(f"{{{NS['r']}}}id")
        sheets.append((s.get("name"), rid2t.get(rid)))
    sst = []
    try:
        ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in ss.findall("m:si", NS):
            sst.append("".join(t.text or "" for t in si.iter(M + "t")))
    except KeyError:
        pass
    return z, sheets, sst


def cells_of(z, target: str, sst):
    root = ET.fromstring(z.read("xl/" + target.lstrip("/")))
    dim = root.find("m:dimension", NS)
    out = {}
    for c in root.iter(M + "c"):
        ref = c.get("r")
        t = c.get("t")
        f = c.find("m:f", NS)
        v = c.find("m:v", NS)
        val = None
        if t == "s" and v is not None:
            val = sst[int(v.text)]
        elif t == "inlineStr":
            node = c.find("m:is", NS)
            val = "".join(x.text or "" for x in node.iter(M + "t")) if node is not None else None
        elif v is not None:
            val = v.text
        out[ref] = {"v": val, "f": (f.text if f is not None else None)}
    return out, (dim.get("ref") if dim is not None else None)


def col_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def split_ref(ref: str):
    letters = "".join(ch for ch in ref if ch.isalpha())
    digits = "".join(ch for ch in ref if ch.isdigit())
    return col_num(letters), int(digits)


def main() -> None:
    path = sys.argv[1]
    z, sheets, sst = load(path)

    if "--sheets" in sys.argv:
        print(f"文件: {path}")
        for name, target in sheets:
            _, dim = cells_of(z, target, sst)
            print(f"  - {name}  dimension={dim}")
        return

    if "--find" in sys.argv:
        needle = sys.argv[sys.argv.index("--find") + 1]
        for name, target in sheets:
            cells, _ = cells_of(z, target, sst)
            hits = [ref for ref, d in cells.items() if d["v"] == needle]
            if hits:
                print(f"  「{needle}」在 [{name}] 的单元格: {hits[:8]}")
        return

    sheet_name = sys.argv[2]
    r1, r2, c1, c2 = (int(x) for x in sys.argv[3:7])
    target = [t for n, t in sheets if n == sheet_name]
    if not target:
        print("无此工作表；现有：", [n for n, _ in sheets])
        return
    cells, dim = cells_of(z, target[0], sst)
    print(f"### {path} :: {sheet_name}  dimension={dim}")
    for r in range(r1, r2 + 1):
        parts = []
        for c in range(c1, c2 + 1):
            ref = f"{col_letter(c)}{r}"
            d = cells.get(ref)
            if not d or (d["v"] is None and d["f"] is None):
                continue
            parts.append(f"{ref}=" + (f"{{{d['f']}}}" if d["f"] else repr(d["v"])))
        if parts:
            print("  " + " | ".join(parts))


if __name__ == "__main__":
    main()
