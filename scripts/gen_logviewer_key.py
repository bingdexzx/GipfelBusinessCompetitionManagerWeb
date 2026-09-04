"""Ensure LOGVIEWER_SECRET_KEY in backend/.env (generate when empty/missing).

Idempotent: an existing non-empty value is kept as-is. When empty or absent,
a strong random key (base64 of 32 random bytes) is written in place.
ASCII-only console output for Windows codepage safety.

Usage (called by scripts/bootstrap-dev.bat after the venv is ready):
    python scripts/gen_logviewer_key.py
"""
import base64
import io
import os
import re
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
ENV_PATH = os.path.join(ROOT_DIR, "backend", ".env")


def main() -> int:
    if not os.path.exists(ENV_PATH):
        print("[ERROR] missing " + ENV_PATH + " (copy .env.example first)")
        return 1
    with io.open(ENV_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"(?m)^LOGVIEWER_SECRET_KEY=(.*)$", src)
    current = (m.group(1) if m else "").strip().strip('"').strip("'")
    if current:
        print("[OK]    LOGVIEWER_SECRET_KEY already set")
        return 0
    new_key = base64.b64encode(os.urandom(32)).decode("ascii")
    line = "LOGVIEWER_SECRET_KEY=" + new_key
    if m:
        src = src[: m.start()] + line + src[m.end():]
    else:
        if src and not src.endswith("\n"):
            src += "\n"
        src += line + "\n"
    with io.open(ENV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print("[OK]    generated LOGVIEWER_SECRET_KEY in backend/.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
