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
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
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
# 项目标识（审计 D-02）：PID 文件里的记录必须带它，避免同一 %TEMP% 下多个 checkout
# 共用一份记录、也避免把别的项目的进程当成自己的。
PROJECT_ID = "gipfel-dev:" + hashlib.sha256(str(ROOT).lower().encode("utf-8")).hexdigest()[:12]


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
        # 审计 D-01：改前这里直接建议跑 `stop-dev.bat`，而那个脚本会**无差别强杀**
        # 任何监听这些端口的进程（可能是 Docker、另一个 Vite、用户的其它服务）。
        # 现在改为：先让用户确认占用者是不是本项目，再走安全的 `dev.py stop`。
        error("If it is a leftover instance of THIS repository, run: python scripts\\dev.py stop")
        error("Otherwise check who owns the port first (dev.py stop lists the owners; it never kills them).")
        return False

    info("Ports free: %s" % ", ".join(f"{host}:{port}" for host, port in ports))
    info("Services: %s" % " / ".join(s.name for s in services))
    return True


def _write_pid_file(supervisor_pid: int, services: list[Service]) -> None:
    """记录监管进程与子进程的**可校验身份**（审计 D-02）。

    改前只写 4 个裸 PID：PID 会被系统回收，非优雅退出（关窗 X / 任务管理器 / taskkill）
    又不会删这个文件，用户几小时后再跑 `stop-dev.bat` 就会强杀**无关**进程树。
    现在每条记录带上「PID、映像名、进程创建时间、项目根路径哈希、nonce」，供 stop 时逐条校验。
    """
    try:
        records = [
            _pid_record(supervisor_pid, role="supervisor"),
        ]
        records += [_pid_record(s.pid, role=s.name) for s in services if s.pid]
        lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records]
        PID_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        warn(f"Cannot write {PID_FILE}: {exc}")


def _pid_record(pid: int, *, role: str = "", nonce: str = "") -> dict:
    """一条可校验的进程记录。"""
    info_map = _process_info(pid) or {}
    return {
        "pid": int(pid),
        "role": role,
        "image": info_map.get("image") or "",
        "created": info_map.get("created") or "",
        "root": PROJECT_ID,
        "nonce": nonce or uuid.uuid4().hex[:12],
    }


def _process_info(pid: int) -> dict | None:
    """查询进程的映像名与创建时间（Windows 用 PowerShell，其它平台用 /proc）。

    返回 `{"image": ..., "created": ...}`；查询不到（进程已退出/无权限）返回 None。
    """
    if IS_WINDOWS:
        cmd = (
            "powershell -NoProfile -NonInteractive -Command "
            f"\"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' "
            "-ErrorAction SilentlyContinue; "
            "if($p){'{0}|{1}' -f $p.Name,$p.CreationDate}\""
        )
        try:
            out = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except Exception:  # noqa: BLE001 - 查询失败按「无身份」处理
            return None
        if "|" not in out:
            return None
        image, _, created = out.partition("|")
        return {"image": image.strip(), "created": created.strip()}
    # POSIX：/proc/<pid>（Linux）/ ps（macOS）
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
        stat = Path(f"/proc/{pid}").stat()
        return {"image": Path(exe).name, "created": str(int(stat.st_ctime))}
    except OSError:
        try:
            out = subprocess.run(
                ["ps", "-o", "comm=,lstart=", "-p", str(int(pid))],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            return None
        if not out:
            return None
        parts = out.split(None, 1)
        return {"image": parts[0], "created": (parts[1] if len(parts) > 1 else "")}


def pid_record_matches(record: dict, info: dict | None) -> tuple[bool, str]:
    """判断一条 PID 记录是否仍然指向「当初那个进程」（审计 D-01 / D-02）。

    返回 `(是否匹配, 原因)`。任一关键字段不符即视为**不可信** —— 调用方只能提示，绝不能杀。
    """
    if not isinstance(record, dict) or record.get("pid") is None:
        return False, "记录格式无法识别"
    if str(record.get("root") or "") != PROJECT_ID:
        return False, "记录不属于本仓库（项目标识不符）"
    if info is None:
        return False, "进程已退出或无法查询其身份"
    image = str(info.get("image") or "")
    image_ok = any(image.lower() == want for want in ("python.exe", "node.exe", "python", "node"))
    if not image_ok:
        return False, f"映像名不是本项目的服务进程（实际 {image or '未知'}）"
    expected_created = str(record.get("created") or "")
    actual_created = str(info.get("created") or "")
    if expected_created and actual_created and expected_created != actual_created:
        return False, "PID 已被系统回收后分配给其它进程（创建时间不符）"
    if not expected_created:
        return False, "记录缺少创建时间，无法确认身份"
    return True, "身份校验通过"


def read_pid_records() -> list[dict]:
    """读取 PID 文件；兼容改前的「每行一个裸 PID」旧格式（旧格式一律不可信）。"""
    if not PID_FILE.exists():
        return []
    try:
        text = PID_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
            continue
        if line.isdigit():      # 旧格式：没有身份信息
            records.append({"pid": int(line), "legacy": True})
    return records


def stop_command() -> int:
    """`dev.py stop`：只停止**身份可校验**的本项目进程（审计 D-01 / D-02）。

    改前 `stop-dev.bat` 的两条路径都危险：按端口无差别强杀任何监听 8000/5173/8120 的进程
    （可能是 Docker、另一个 Vite、用户的其它服务），以及按 PID 文件裸杀（PID 被回收后误杀）。
    现在统一走这里：逐条校验身份，不符只提示；端口占用只列出候选，绝不代杀。
    """
    records = read_pid_records()
    stopped = 0
    checked = 0
    for record in records:
        pid = record.get("pid")
        if record.get("legacy"):
            warn(f"PID {pid}：来自旧版 PID 文件（没有身份信息），**不杀**；"
                 "请自行确认该进程后再处理")
            continue
        checked += 1
        matched, why = pid_record_matches(record, _process_info(int(pid)))
        if not matched:
            warn(f"PID {pid}（{record.get('role') or '未知角色'}）：{why} —— 跳过，不杀")
            continue
        info(f"PID {pid}（{record.get('role') or '未知角色'}）：{why} —— 停止")
        if IS_WINDOWS:
            _force_kill_tree(int(pid))
        else:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass
        stopped += 1

    if records:
        _remove_pid_file()

    # 端口占用只报告候选，绝不代杀（`taskkill /PID <监听者>` 会连带杀掉 Docker 等无关服务）
    busy = _report_busy_ports()
    print()
    if stopped:
        ok(f"Stopped {stopped} process(es) recorded by this repository.")
    elif checked:
        info("No verifiable dev process was running.")
    else:
        info("No PID file found (nothing recorded by this repository).")
    if busy:
        warn("以下端口仍被占用，请自行确认占用者是否属于本项目：")
        for host, port, owner in busy:
            print(f"    - {host}:{port}  <- {owner}")
        info("确认是属于本项目的残留后，可用: taskkill /PID <pid> /T /F")
    return 0


def _report_busy_ports() -> list[tuple[str, int, str]]:
    """列出开发端口当前的占用者（PID + 映像名 + 命令行），仅用于提示。"""
    out: list[tuple[str, int, str]] = []
    for host, port in _dev_ports():
        if not _port_in_use(host, port):
            continue
        pid = _listening_pid(port)
        owner = "占用者未知"
        if pid:
            proc = _process_info(pid) or {}
            cmdline = _process_cmdline(pid)
            owner = f"PID {pid} {proc.get('image') or '?'}"
            if cmdline:
                owner += f" | {cmdline[:140]}"
        out.append((host, port, owner))
    return out


def _dev_ports() -> list[tuple[str, int]]:
    return [
        (BACKEND_HOST, BACKEND_PORT),
        (VITE_HOST, VITE_PORT),
        (LOGVIEWER_HOST, _read_logviewer_port()),
    ]


def _listening_pid(port: int) -> int | None:
    """用 netstat 找出监听该端口的 PID（只读，不杀）。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=15
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper().startswith("TCP") and parts[3].upper() == "LISTENING":
            if parts[1].endswith(f":{port}") and parts[4].isdigit():
                return int(parts[4])
    return None


def _process_cmdline(pid: int) -> str:
    if not IS_WINDOWS:
        return ""
    cmd = (
        "powershell -NoProfile -NonInteractive -Command "
        f"\"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' "
        "-ErrorAction SilentlyContinue).CommandLine\""
    )
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


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


def check_command() -> int:
    """同步前置检查（审计 X-19）：依赖是否存在 + 三个开发端口是否空闲。

    背景：`start` 是**异步**启动，父批处理拿不到子进程的退出码，于是 `start-dev.bat`
    改前无论 dev.py 是否成功都 `exit /b 0` —— CI/IDE 把"启动失败"当成功，后续步骤
    在超时后才失败。这个入口把同一套 `_check_preconditions` 同步跑一遍，失败返回 1，
    供 start-dev.bat 在 `start` 之前调用。

    刻意**不**调用 `_pause_if_console()`：是否暂停由调用方（批处理的 :fail 分支）决定，
    避免双击用户被要求按两次回车。
    """
    logviewer_port = _read_logviewer_port()
    services = _build_services(logviewer_port)
    print("=" * 72)
    print(" Gipfel dev preconditions check")
    print("=" * 72)
    passed = _check_preconditions(logviewer_port, services)
    if passed:
        ok("Preconditions OK.")
    else:
        error("Preconditions FAILED; services were NOT started.")
    return 0 if passed else 1


def main() -> int:
    _prepare_console()

    arg = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""

    # 审计 D-01 / D-02：`dev.py stop` 是安全的清理入口（逐条校验进程身份后才停，
    # 端口占用只报告不代杀）。`scripts\stop-dev.bat` 现在只是它的包装。
    if arg in ("stop", "--stop"):
        return stop_command()

    # 审计 X-19：同步前置检查，供 start-dev.bat 在 `start` 之前调用，让"启动失败"
    # 能真正反映到批处理/调用方的退出码上。
    if arg in ("check", "--check-only"):
        return check_command()

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
