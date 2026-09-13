"""Ensure LOGVIEWER_SECRET_KEY in backend/.env (generate when empty/missing).

Idempotent: an existing non-empty value is kept as-is. When empty or absent,
a strong random key (base64 of 32 random bytes) is written in place.
ASCII-only console output for Windows codepage safety.

审计 X-12：改前这里写死 `encoding="utf-8"` 读取，且用 `re.search` 只匹配**第一条**：
  - `.env` 被记事本存成 GBK ⇒ `UnicodeDecodeError` 直接冒泡，`bootstrap-dev.bat` 只看到
    "failed to ensure LOGVIEWER_SECRET_KEY" 与非 0 退出码，真正原因（文件编码）完全不提示；
  - `.env` 带 UTF-8 BOM ⇒ 行首多了 `\\ufeff`，正则匹配不到 ⇒ 脚本把新键**追加**到文件末尾，
    文件里出现两条同名键，而 `settings.py` 读的是**前面那条**（仍为空）⇒ 日志查看器
    fail-fast 拒绝启动，表现成"bootstrap 成功但 8120 起不来"。
现在：用 `utf-8-sig` + `errors="replace"` 容错读取（同时解决 BOM），检测替换符时给出
"请以 UTF-8 保存"的明确提示；逐行扫描并对同名键取**最后一条**；写入时先删掉全部同名行、
只保留唯一一条；已有值过短时告警（弱值不再被默默放过）。

Usage (called by scripts/bootstrap-dev.bat after the venv is ready):
    python scripts/gen_logviewer_key.py
"""
import base64
import io
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
ENV_PATH = os.path.join(ROOT_DIR, "backend", ".env")

KEY = "LOGVIEWER_SECRET_KEY"
MIN_LEN = 32


def read_env(path: str) -> str:
    """容错读取 .env：utf-8-sig 同时解决 BOM；无法解码的字节用替换符占位并告警。"""
    with io.open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")
    if "\ufffd" in text:
        print("[WARN]  backend/.env contains bytes that are not valid UTF-8 "
              "(probably saved as GBK/ANSI). Please re-save it as UTF-8; "
              "undecodable bytes were replaced.")
    return text


def find_key_index(lines: list[str]) -> int:
    """返回 KEY 的**最后一条**记录下标；不存在返回 -1。"""
    idx = -1
    for i, line in enumerate(lines):
        if line.lstrip("\ufeff").strip().startswith(KEY + "="):
            idx = i
    return idx


def key_value(line: str) -> str:
    return line.split("=", 1)[1].strip().strip('"').strip("'") if "=" in line else ""


def main() -> int:
    if not os.path.exists(ENV_PATH):
        print("[ERROR] missing " + ENV_PATH + " (copy .env.example first)")
        return 1
    src = read_env(ENV_PATH)
    lines = src.split("\n")
    idx = find_key_index(lines)
    duplicates = sum(
        1 for ln in lines if ln.lstrip("\ufeff").strip().startswith(KEY + "=")
    )

    if idx >= 0:
        current = key_value(lines[idx])
        if current:
            if len(current) < MIN_LEN:
                print("[WARN]  LOGVIEWER_SECRET_KEY looks weak (len={}); "
                      "delete the line and re-run to regenerate".format(len(current)))
            else:
                print("[OK]    LOGVIEWER_SECRET_KEY already set")
            if duplicates > 1:
                print("[WARN]  backend/.env has {} {} lines; collapsing to one".format(duplicates, KEY))
                _write_single(ENV_PATH, lines, current)
            return 0

    new_key = base64.b64encode(os.urandom(32)).decode("ascii")
    _write_single(ENV_PATH, lines, new_key)
    print("[OK]    generated LOGVIEWER_SECRET_KEY in backend/.env")
    return 0


def _write_single(path: str, lines: list[str], value: str) -> None:
    """删掉全部同名行（含空值/弱值那条），只写唯一一行 —— 避免 settings 读到旧的那条。"""
    kept = [ln for ln in lines if not ln.lstrip("\ufeff").strip().startswith(KEY + "=")]
    while kept and kept[-1] == "":
        kept.pop()
    kept.append(KEY + "=" + value)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(kept) + "\n")


if __name__ == "__main__":
    sys.exit(main())
