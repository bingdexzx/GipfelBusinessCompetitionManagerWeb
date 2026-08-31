#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动日志查看器独立服务（端口由 backend/.env 的 LOG_VIEWER_PORT 决定，默认 8120）。

用法：
  python scripts/start_logviewer.py            # 读取 .env 的 LOG_VIEWER_PORT
  python scripts/start_logviewer.py 9000       # 临时指定端口
  LOG_VIEWER_PORT=9000 python scripts/start_logviewer.py

需使用已安装 Django 的 Python（推荐 backend/.venv）。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 项目根
BACKEND = ROOT / "backend"
LOGVIEWER = BACKEND / "logviewer"
ENV_FILE = BACKEND / ".env"

DEFAULT_PORT = 8120


def load_env_port():
    port = DEFAULT_PORT
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == "LOG_VIEWER_PORT":
                val = val.strip().strip('"').strip("'")
                if val.isdigit():
                    port = int(val)
    # 环境变量优先
    env_port = os.environ.get("LOG_VIEWER_PORT")
    if env_port and env_port.isdigit():
        port = int(env_port)
    return port


def pick_python():
    # 优先使用 backend/.venv 中的解释器
    candidates = [
        BACKEND / ".venv" / "Scripts" / "python.exe",   # Windows
        BACKEND / ".venv" / "bin" / "python",            # Linux/macOS
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def main():
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    else:
        port = load_env_port()

    if not LOGVIEWER.exists():
        print("未找到日志查看器目录：%s" % LOGVIEWER, file=sys.stderr)
        sys.exit(1)

    py = pick_python()
    print("启动日志查看器：http://localhost:%d  (日志目录 backend/logs)" % port)
    print("Ctrl+C 停止")
    try:
        subprocess.run(
            [py, "manage.py", "runserver", str(port), "--noreload"],
            cwd=str(LOGVIEWER),
            check=True,
        )
    except KeyboardInterrupt:
        print("\n已停止日志查看器。")
    except subprocess.CalledProcessError as e:
        print("日志查看器启动失败：%s" % e, file=sys.stderr)
        sys.exit(e.returncode)


if __name__ == "__main__":
    main()
