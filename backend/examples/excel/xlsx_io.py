# -*- coding: utf-8 -*-
"""极简 XLSX / CSV 表格读写（只用标准库，不引入任何新依赖）。

为什么不用 openpyxl / pandas
----------------------------
本仓库的运行环境里没有它们，安装又会给项目加依赖；而表格建包只需要
「读出单元格文本」「写出单元格文本」两件事，因此这里用标准库直接处理：

- **读**：xlsx 就是一个 zip，里面是 XML。读 `xl/workbook.xml` 拿到工作表清单，
  读 `xl/sharedStrings.xml` 拿到共享字符串，再逐行读 `xl/worksheets/sheetN.xml`。
  只关心 `sheetData`，其它元素（dimension / cols / 样式 / 公式）一律忽略。
- **写**：生成最小可用的 xlsx（inlineStr 写文本），Excel / WPS / LibreOffice 均可打开。

同一份数据也支持「一个目录 + 每张表一个 CSV」，便于进 git、便于 diff，也便于没有 Excel 的环境。

对外接口
--------
    load_tables(path) -> {表名: [[单元格文本, ...], ...]}     # 自动识别 .xlsx / 目录
    save_tables(path, tables)                                 # 按扩展名写出
    read_xlsx(path) / write_xlsx(path, tables)
    read_csv_dir(path) / write_csv_dir(path, tables)
"""
from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_CELL_REF_RE = re.compile(r"([A-Z]+)")


# =============================================================================
# 读 xlsx
# =============================================================================


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _col_index(cell_ref: str) -> int:
    """A1 → 0，B1 → 1，AA1 → 26。"""
    letters = _CELL_REF_RE.match(cell_ref or "")
    if not letters:
        return 0
    index = 0
    for ch in letters.group(1):
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root:
        if _strip_ns(si.tag) != "si":
            continue
        # <si><t>文本</t></si> 或 <si><r><t>片段</t></r>...</si>（富文本）
        parts = [node.text or "" for node in si.iter() if _strip_ns(node.tag) == "t"]
        out.append("".join(parts))
    return out


def _sheet_files(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """返回 [(工作表名, zip 内路径)]，顺序与工作簿里一致。"""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_target = {
        rel.get("Id"): rel.get("Target")
        for rel in rels_root
        if _strip_ns(rel.tag) == "Relationship"
    }
    names = zf.namelist()
    out: list[tuple[str, str]] = []
    for node in wb.iter():
        if _strip_ns(node.tag) != "sheet":
            continue
        name = node.get("name") or f"Sheet{len(out) + 1}"
        rid = node.get(f"{{{NS_REL}}}id") or node.get("id")
        target = rel_target.get(rid) or ""
        target = target.lstrip("/")
        if target and not target.startswith("xl/"):
            target = f"xl/{target}"
        if target not in names:  # 兜底：按顺序猜
            guess = f"xl/worksheets/sheet{len(out) + 1}.xml"
            target = guess if guess in names else target
        out.append((name, target))
    return out


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    ctype = cell.get("t")
    if ctype == "inlineStr":
        return "".join(node.text or "" for node in cell.iter() if _strip_ns(node.tag) == "t")
    value_node = next((n for n in cell if _strip_ns(n.tag) == "v"), None)
    raw = "" if value_node is None or value_node.text is None else value_node.text
    if ctype == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if ctype == "b":
        return "TRUE" if raw.strip() in ("1", "true", "TRUE") else "FALSE"
    return raw


def read_xlsx(path: str | Path) -> dict[str, list[list[str]]]:
    """读 xlsx：{工作表名: [[单元格文本, ...], ...]}（空尾列已裁剪，整行空行保留）。"""
    tables: dict[str, list[list[str]]] = {}
    with zipfile.ZipFile(Path(path)) as zf:
        shared = _read_shared_strings(zf)
        for name, target in _sheet_files(zf):
            if target not in zf.namelist():
                tables[name] = []
                continue
            root = ET.fromstring(zf.read(target))
            rows: list[list[str]] = []
            for row_node in root.iter():
                if _strip_ns(row_node.tag) != "row":
                    continue
                cells: dict[int, str] = {}
                next_index = 0
                for cell in row_node:
                    if _strip_ns(cell.tag) != "c":
                        continue
                    ref = cell.get("r")
                    index = _col_index(ref) if ref else next_index
                    next_index = index + 1
                    cells[index] = _cell_text(cell, shared)
                width = max(cells) + 1 if cells else 0
                rows.append([cells.get(i, "") for i in range(width)])
            tables[name] = rows
    return tables


# =============================================================================
# 写 xlsx
# =============================================================================

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheet_overrides}
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>"""


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        # XML 1.0 不允许的控制字符（Excel 会直接报文件损坏）
        .replace("\x00", "")
    )


def _col_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _sheet_xml(rows: list[list]) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<worksheet xmlns="{NS_MAIN}"><sheetData>',
    ]
    for r, row in enumerate(rows, start=1):
        out.append(f'<row r="{r}">')
        for c, value in enumerate(row):
            if value is None or value == "":
                continue
            ref = f"{_col_letters(c)}{r}"
            if isinstance(value, bool):
                out.append(f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>')
            elif isinstance(value, (int, float)):
                out.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                text = _xml_escape(str(value))
                out.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def write_xlsx(path: str | Path, tables: dict[str, list[list]]) -> Path:
    """写 xlsx（文本按 inlineStr 写入，数字/布尔按原生类型写）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(tables.keys())
    overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(names) + 1)
    )
    sheets_xml = "\n".join(
        f'<sheet name="{_xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(names, start=1)
    )
    rels = "\n".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(names) + 1)
    )
    styles_rid = f"rId{len(names) + 1}"
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}"><sheets>{sheets_xml}</sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{NS_PKG_REL}">{rels}'
        f'<Relationship Id="{styles_rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES.format(sheet_overrides=overrides))
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/styles.xml", _STYLES)
        for i, name in enumerate(names, start=1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(tables[name] or []))
    return path


# =============================================================================
# CSV 目录（一个目录 = 一个工作簿，一张表 = 一个 .csv）
# =============================================================================


def read_csv_dir(path: str | Path) -> dict[str, list[list[str]]]:
    """读目录：每个 .csv 文件名（去掉扩展名）就是工作表名；用 utf-8-sig 兼容 Excel 导出的 BOM。"""
    path = Path(path)
    tables: dict[str, list[list[str]]] = {}
    for file in sorted(path.glob("*.csv")):
        with file.open("r", encoding="utf-8-sig", newline="") as fh:
            tables[file.stem] = [list(row) for row in csv.reader(fh)]
    return tables


def write_csv_dir(path: str | Path, tables: dict[str, list[list]]) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with (path / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerows(rows or [])
    return path


# =============================================================================
# 统一入口
# =============================================================================


def load_tables(path: str | Path) -> dict[str, list[list[str]]]:
    """按路径类型读取：`.xlsx` → xlsx；目录 → 目录下的 CSV 集合。"""
    path = Path(path)
    if path.is_dir():
        return read_csv_dir(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return read_xlsx(path)
    raise ValueError(f"不支持的表格来源：{path}（请给 .xlsx 文件或一个存放 CSV 的目录）")


def save_tables(path: str | Path, tables: dict[str, list[list]]) -> Path:
    """按扩展名写出：`.xlsx` → xlsx；目录 → CSV 集合。"""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return write_xlsx(path, tables)
    return write_csv_dir(path, tables)
