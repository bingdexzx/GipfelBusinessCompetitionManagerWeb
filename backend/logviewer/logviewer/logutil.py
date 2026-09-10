"""日志文件读取工具：列出文件、解析行、过滤、tail。

主服务日志格式（backend/backend/settings.py verbose formatter）：
    [{asctime}] {levelname} {name} [{operator}] [{client_ip}] [{device}] {message}
其中 operator 为发起请求的用户（JWT 用户名），无请求上下文时为 '-'。
client_ip 为客户端 IP 地址，无请求上下文时为 '-'。
device 为设备信息精简标识（如 Chrome/Win10/11），无请求上下文时为 '-'。
例：
    [2026-08-31 18:04:12] INFO gipfel.something [admin] [192.168.1.100] [Chrome/Win10/11] 用户 admin 登录成功

兼容升级前的旧格式（可选字段缺失时回退为 '-'）：
    [2026-08-31 18:04:12] INFO gipfel.something [admin] 用户 admin 登录成功
    [2026-08-31 18:04:12] INFO gipfel.something 用户 admin 登录成功
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from django.conf import settings

# operator、client_ip、device 字段（[...]）均为可选，兼容升级前无这些字段的旧日志行
LINE_RE = re.compile(
    r"^\[([^\]]+)\]\s+(\w+)\s+(\S+?)(?:\s+\[([^\]]*)\])?(?:\s+\[([^\]]*)\])?(?:\s+\[([^\]]*)\])?\s+(.*)$"
)

# 单次最多读入内存的字节数（超过则只取尾部该大小），防止超大文件拖垮服务
MAX_READ_BYTES = 8 * 1024 * 1024


def _safe_path(filename: str) -> Path:
    """校验文件位于允许的日志目录内，防止路径穿越。"""
    base = Path(settings.LOG_ALLOW_DIR).resolve()
    if not filename:
        raise ValueError("文件名不能为空")
    # 仅允许基础文件名（不含路径分隔符），再拼到 LOG_DIR
    if filename != os.path.basename(filename):
        raise ValueError("非法文件名")
    target = (base / filename).resolve()
    if target.parent != base:
        raise ValueError("非法路径")
    return target


def list_log_files() -> list[dict]:
    """列出日志目录内 gipfel.log 及其按日滚动文件。"""
    base = Path(settings.LOG_ALLOW_DIR)
    if not base.exists():
        return []
    files = []
    for p in sorted(base.iterdir(), key=lambda x: x.name):
        if not p.is_file():
            continue
        if p.name == settings.LOG_FILE_NAME or p.name.startswith(
            settings.LOG_FILE_NAME + "."
        ):
            try:
                st = p.stat()
                files.append(
                    {
                        "name": p.name,
                        "size": st.st_size,
                        "mtime": datetime.fromtimestamp(st.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )
            except OSError:
                continue
    # 当前日志排最前
    files.sort(key=lambda f: (f["name"] != settings.LOG_FILE_NAME, f["name"]))
    return files


def _read_text_tail(path: Path, max_bytes: int = MAX_READ_BYTES) -> str:
    """读取文本；文件过大时只取尾部 max_bytes 字节。"""
    size = path.stat().st_size
    if size <= max_bytes:
        return path.read_text(encoding="utf-8", errors="replace")
    with open(path, "rb") as f:
        f.seek(-max_bytes, os.SEEK_END)
        # 丢弃首行可能截断的半行
        f.readline()
        return f.read().decode("utf-8", errors="replace")


def _parse_line(line: str) -> dict:
    m = LINE_RE.match(line)
    if m:
        # group(4)=operator, group(5)=client_ip, group(6)=device, group(7)=message
        # 所有 [...] 字段均为可选，缺失时回退为 '-'
        operator = m.group(4) or "-"
        client_ip = m.group(5) or "-"
        device = m.group(6) or "-"
        message = m.group(7)
        # 兼容旧格式：当只有 1~2 个 [...] 时，后面的可选组可能捕获到 message 开头
        # 如果 message 为空而某个可选组有值，说明它实际是 message 的一部分
        if not message:
            if m.group(6):
                device = "-"
                message = m.group(6)
            elif m.group(5):
                client_ip = "-"
                device = "-"
                message = m.group(5)
        return {
            "time": m.group(1),
            "level": m.group(2).upper(),
            "logger": m.group(3),
            "operator": operator,
            "client_ip": client_ip,
            "device": device,
            "message": message,
        }
    return {"time": "", "level": "", "logger": "", "operator": "-", "client_ip": "-", "device": "-", "message": line}


def read_logs(
    filename: str,
    mode: str = "tail",
    lines: int = 300,
    level: str = "ALL",
    q: str = "",
) -> dict:
    """读取并解析日志。

    - mode="tail"：取文件尾部，再按过滤条件筛选后返回最近 lines 行
    - mode="range"：取全文（受 MAX_READ_BYTES 限制），筛选后返回前 lines 行
    返回 {rows, total, file, size, truncated}
    """
    path = _safe_path(filename)
    if not path.exists():
        return {"rows": [], "total": 0, "file": filename, "size": 0, "truncated": False}

    text = _read_text_tail(path)
    truncated = path.stat().st_size > MAX_READ_BYTES

    raw_lines = [ln for ln in text.splitlines() if ln.strip()]
    # 多行合并：将不以日志头 [timestamp] 开头的续行合并到上一条日志的 message 末尾
    merged_rows: list[dict] = []
    for ln in raw_lines:
        if LINE_RE.match(ln):
            merged_rows.append(_parse_line(ln))
        elif merged_rows:
            # 续行：追加到上一条日志的 message 中（保留换行符以便展示）
            merged_rows[-1]["message"] += "\n" + ln
        else:
            # 文件开头就是续行（异常情况），单独处理
            merged_rows.append(_parse_line(ln))
    rows = merged_rows

    level = (level or "ALL").upper()
    q = (q or "").strip().lower()

    def match(r: dict) -> bool:
        if level != "ALL" and r["level"] != level:
            return False
        if q and q not in (
            r["message"] + " " + r["logger"] + " " + (r.get("operator") or "")
            + " " + (r.get("client_ip") or "") + " " + (r.get("device") or "")
        ).lower():
            return False
        return True

    filtered = [r for r in rows if match(r)]

    if mode == "tail":
        window = filtered[-max(1, lines):]
    else:
        window = filtered[: max(1, lines)]

    return {
        "rows": window,
        "total": len(filtered),
        "file": filename,
        "size": path.stat().st_size,
        "truncated": truncated,
    }
