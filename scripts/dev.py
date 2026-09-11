"""Windows 开发启动监管进程：Django(:8000) + Vite(:5173) + 日志查看器(:8120)。

为什么需要它（替代纯 .bat 的 `start /B` 方案）：
    cmd 的 `start` / `start /B` 会把子进程放进**新的进程组**，控制台按 Ctrl+C
    产生的 CTRL_C_EVENT 不会投递给它们 —— 服务照常运行，只有 cmd.exe 自己收到
    信号并停在「终止批处理操作吗(Y/N)?」，窗口看起来卡死、端口也不释放。
    本进程自己当监管者：子进程依旧以 CREATE_NEW_PROCESS_GROUP 启动，退出时由
    我们**定向**向每个子进程组发送 CTRL_BREAK_EVENT（Windows 上唯一可定向到
    进程组的控制台事件，实测子进程能收到），超时再用 `taskkill /T /F` 兜底。

用法（正常由 scripts\\start-dev.bat 在独立窗口拉起，单独运行也可以）：
    python scripts\\dev.py

端口/目录约定与改造前的 start-dev.bat 完全一致：
    Django     127.0.0.1:8000（本脚本写死，不读 .env 的 PORT）
    Vite       127.0.0.1:5173
    LogViewer  127.0.0.1:<backend/.env 的 LOG_VIEWER_PORT，默认 8120>
    - 三个子进程的 stdout/stderr 直接流到本控制台（不落日志文件）
    - 子进程工作目录分别为 backend / frontend / backend/logviewer，
      保证 backend/.env 里 `LOG_DIR="./logs"` 落在 backend/logs
    - 进程号写入 %TEMP%\\gipfel-dev.pids，供 scripts\\stop-dev.bat 兜底强杀
"""
from __future__ import annotations

import ctypes
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# CreateProcess 标志 / 控制台事件常量（Windows）
CREATE_NEW_PROCESS_GROUP = 0x00000200
CTRL_BREAK_EVENT = 1

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
LOGVIEWER = BACKEND / "logviewer"
VENV_PYTHON = BACKEND / ".venv" / "Scripts" / "python.exe"
VITE_JS = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"

BACKEND_HOST, BACKEND_PORT = "127.0.0.1", 8000
VITE_HOST, VITE_PORT = "127.0.0.1", 5173
LOGVIEWER_HOST = "127.0.0.1"
DEFAULT_LOGVIEWER_PORT = 8120

PID_FILE = Path(tempfile.gettempdir()) / "gipfel-dev.pids"
SHUTDOWN_GRACE_SECONDS = 8.0
PROBE_INTERVAL_SECONDS = 1.0


def info(msg: str) -> None:
    print(f"[INFO]  {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"[OK]    {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN]  {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", flush=True)


def _prepare_console() -> None:
    """UTF-8 控制台 + 无缓冲输出：日志里的中文不乱码、不丢行。"""
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:  # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _pause_if_console() -> None:
    """出错时不要瞬间关窗（双击 start-dev.bat 的用户看不到报错）。"""
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input("\nPress Enter to exit ...")
    except (EOFError, KeyboardInterrupt):
        pass


def _read_logviewer_port() -> int:
    """取 backend/.env 的 LOG_VIEWER_PORT（与旧 start-dev.bat 的 findstr 行为一致：取最后一条）。"""
    port = DEFAULT_LOGVIEWER_PORT
    env_file = BACKEND / ".env"
    if not env_file.exists():
        return port
    try:
        for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line.startswith("LOG_VIEWER_PORT="):
                continue
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value.isdigit():
                port = int(value)
    except OSError:
        pass
    return port


def _port_in_use(host: str, port: int, timeout: float = 0.5) -> bool:
    """端口是否已被监听：直接尝试 connect（避开 TIME_WAIT 与 Windows SO_REUSEADDR 的坑）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
    return True


def _probe(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 400
    except Exception:  # noqa: BLE001
        return False


def _send_ctrl_break(pid: int) -> bool:
    """向某个进程组定向发送 CTRL_BREAK_EVENT（dwProcessGroupId = 组长 pid）。

    CTRL_C_EVENT 无法定向（dwProcessGroupId 非 0 时目标收不到），只有 CTRL_BREAK
    能精确投递给一个进程组，因此这里用它做优雅停止（daphne / node 都能据此退出）。
    """
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid))
    except Exception:  # noqa: BLE001
        return False


def _force_kill_tree(pid: int) -> None:
    """兜底强杀：连同子进程（venv redirector -> 真解释器 / node）一起杀。"""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        pass


@dataclass
class Service:
    name: str
    argv: list[str]
    cwd: Path
    url: str
    probe_seconds: int
    proc: subprocess.Popen | None = field(default=None)
    exit_reported: bool = False

    @property
    def pid(self) -> int:
        return self.proc.pid if self.proc else 0

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        self.proc = subprocess.Popen(  # noqa: S603
            self.argv,
            cwd=str(self.cwd),
            env=env,
            creationflags=creationflags,
        )

    def wait_ready(self) -> bool:
        info(f"Probing {self.name} {self.url} ...")
        deadline = time.time() + self.probe_seconds
        while time.time() < deadline:
            if _probe(self.url):
                ok(f"{self.name} ready")
                return True
            if not self.alive():
                self.exit_reported = True
                warn(f"{self.name} exited early (code {self.proc.poll() if self.proc else '?'})")
                return False
            time.sleep(PROBE_INTERVAL_SECONDS)
        warn(f"{self.name} not responding after {self.probe_seconds}s (continuing anyway)")
        return False


def _build_services(logviewer_port: int) -> list[Service]:
    node = os.environ.get("NODE_EXE") or "node"
    return [
        Service(
            name="Django",
            argv=[
                str(VENV_PYTHON),
                "manage.py",
                "runserver",
                f"{BACKEND_HOST}:{BACKEND_PORT}",
                "--noreload",
            ],
            cwd=BACKEND,
            url=f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/health",
            probe_seconds=24,
        ),
        Service(
            name="Vite",
            argv=[node, str(VITE_JS), "--host", VITE_HOST, "--port", str(VITE_PORT)],
            cwd=FRONTEND,
            url=f"http://{VITE_HOST}:{VITE_PORT}/",
            probe_seconds=30,
        ),
        Service(
            name="LogViewer",
            argv=[
                str(VENV_PYTHON),
                "manage.py",
                "runserver",
                f"{LOGVIEWER_HOST}:{logviewer_port}",
                "--noreload",
            ],
            cwd=LOGVIEWER,
            url=f"http://{LOGVIEWER_HOST}:{logviewer_port}/api/health",
            probe_seconds=24,
        ),
    ]


def _check_preconditions(logviewer_port: int, services: list[Service]) -> bool:
    if not VENV_PYTHON.exists():
        error(f"{VENV_PYTHON} not found. Run scripts\\bootstrap-dev.bat first.")
        return False
    if not VITE_JS.exists():
        error(f"Frontend deps missing ({VITE_JS}). Run scripts\\bootstrap-dev.bat first.")
        return False
    if not (LOGVIEWER / "manage.py").exists():
        error(f"{LOGVIEWER / 'manage.py'} not found.")
        return False

    ports = [(BACKEND_HOST, BACKEND_PORT), (VITE_HOST, VITE_PORT), (LOGVIEWER_HOST, logviewer_port)]
    busy = [f"{host}:{port}" for host, port in ports if _port_in_use(host, port)]
    if busy:
        error("Port already in use: %s" % ", ".join(busy))
        error("Another dev instance is probably still alive. Run scripts\\stop-dev.bat, then retry.")
        return False

    info("Ports free: %s" % ", ".join(f"{host}:{port}" for host, port in ports))
    info("Services: %s" % " / ".join(s.name for s in services))
    return True


def _write_pid_file(supervisor_pid: int, services: list[Service]) -> None:
    try:
        lines = [str(supervisor_pid)] + [str(s.pid) for s in services if s.pid]
        PID_FILE.write_text("\n".join(lines) + "\n", encoding="ascii")
    except OSError as exc:
        warn(f"Cannot write {PID_FILE}: {exc}")


def _remove_pid_file() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _stop_services(services: list[Service]) -> None:
    """优雅停止：定向 CTRL_BREAK -> 等待 -> taskkill /T /F 兜底。"""
    alive = [s for s in services if s.alive()]
    if not alive:
        return
    warn(f"Stopping {len(alive)} child process(es) ...")
    for svc in alive:
        delivered = _send_ctrl_break(svc.pid) if IS_WINDOWS else False
        if delivered:
            continue
        try:
            svc.proc.send_signal(signal.SIGTERM if IS_WINDOWS else signal.SIGINT)
        except OSError:
            pass

    deadline = time.time() + SHUTDOWN_GRACE_SECONDS
    while time.time() < deadline and any(s.alive() for s in services):
        time.sleep(0.2)

    for svc in services:
        if not svc.alive():
            continue
        warn(f"{svc.name} did not exit in {SHUTDOWN_GRACE_SECONDS:.0f}s, force killing ...")
        if IS_WINDOWS:
            _force_kill_tree(svc.pid)
        else:
            svc.proc.kill()
        try:
            svc.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    ok("All services stopped.")


_stop_requested = False


def _handle_signal(signum, frame) -> None:  # noqa: ARG001
    global _stop_requested
    _stop_requested = True


def main() -> int:
    _prepare_console()

    logviewer_port = _read_logviewer_port()
    services = _build_services(logviewer_port)

    print("=" * 72)
    print(" Gipfel dev supervisor  (Ctrl+C stops Django + Vite + LogViewer)")
    print("=" * 72)
    if not _check_preconditions(logviewer_port, services):
        _pause_if_console()
        return 1

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break
        signal.signal(signal.SIGBREAK, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    try:
        for svc in services:
            info(f"Starting {svc.name} -> {' '.join(svc.argv[1:])}")
            try:
                svc.start()
            except OSError as exc:
                error(f"Cannot start {svc.name}: {exc}")
                _pause_if_console()
                return 1
            time.sleep(1)
        _write_pid_file(os.getpid(), services)

        for svc in services:
            svc.wait_ready()

        print()
        ok("All services started.")
        print(f"    Frontend (Vite)  : http://{VITE_HOST}:{VITE_PORT}")
        print(f"    Backend  (Django): http://{BACKEND_HOST}:{BACKEND_PORT}")
        print(
            f"    LogViewer        : http://{LOGVIEWER_HOST}:{logviewer_port}"
            "  (account = Django superadmin)"
        )
        print("    Server output streams to this window (no log file).")
        print()
        warn("Press Ctrl+C to stop all child processes.")

        while not _stop_requested:
            time.sleep(0.5)
            if all(not s.alive() for s in services):
                warn("All services exited on their own, shutting down.")
                break
            for svc in services:
                if svc.exit_reported or svc.alive():
                    continue
                svc.exit_reported = True
                warn(f"{svc.name} exited (code {svc.proc.poll()}).")

        if _stop_requested:
            print()
            info("Ctrl+C received.")
        return 0
    finally:
        _stop_services(services)
        _remove_pid_file()


if __name__ == "__main__":
    sys.exit(main())
