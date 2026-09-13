# -*- coding: utf-8 -*-
"""合同通过监听程序（独立运行 · 只读后端 · 本机自动处理 · 不影响网页端）

功能：
  1. 静默常驻：默认只写本地日志，无控制台输出；--verbose 可见明细。
  2. 监听合同通过：轮询 /api/contracts?status=EXECUTED，发现 executedAt 比
     上次更新的合同（即"合同通过"信号）→ 拉详情 → 按合同类型 key 分发。
  3. 按类型执行函数：处理函数定义在本目录 handlers.py 中，函数命名约定
         handle_<key拼音形态>_passed(contract: dict, ctx: dict) -> None
     未找到函数时使用内置默认行为（把合同全量 JSON 存档到 records/<key>/）。
  4. 类型目录实时同步（新建/改名）：
     - 轮询 /api/contract-types 维护 typeId → key 目录；
     - 出现新 key → 自动在 handlers.py 末尾生成默认函数（幂等，不覆盖）；
     - 某 typeId 的 key 改变 → 自动把对应函数"改名"（@标注行与函数名随新 key
       更新，函数体原样保留），随后热加载立即生效。
  5. 自动化保障：登录态自动续期、崩溃/断网不影响下一轮、单实例互斥、
     已处理进度持久化（重启不重复）、handlers.py 被修改后自动热加载。

用法：
    python contract_watcher.py --server http://127.0.0.1:8000 ^
        --username admin --password "xxx" [--competition 1]
    （首次运行会建立进度基线：只处理"之后"新通过的合同；加 --backfill 处理存量）

账号要求：contract:view（+ 若要自动生成/改名功能则需 contractType:view）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("contract_watcher")

WATCHER_DIR = Path(__file__).resolve().parent
HANDLERS_FILE = WATCHER_DIR / "handlers.py"
STATE_FILE = WATCHER_DIR / "data" / "state.json"
LOG_FILE = WATCHER_DIR / "watcher.log"
RECORDS_DIR = WATCHER_DIR / "records"

MARKER_PREFIX = "# ===== [auto] ContractType.key = "
MARKER_SUFFIX = " ====="
# 连续登录失败多少轮后停止监听（审计 CW-10）
MAX_CONSECUTIVE_AUTH_FAILURES = 5
# 审计 CW-12：失败退避上限（秒）与合同类型目录的最小同步间隔（秒）
MAX_BACKOFF_SECONDS = 60.0
DEFAULT_CATALOG_INTERVAL = 60.0
MARKER_RE = re.compile(r"^# ===== \[auto\] ContractType\.key = (.*?) =====$", re.MULTILINE)
_SLUG_RE = re.compile(r"\W+")

# 审计 CW-19：在模块导入时绑定真实 `time.sleep`。用例常把 `模组.time.sleep` 换成「跑够轮数就抛
# 停止信号」的假实现（见 tests/fix_verify/watcher），看门狗线程若用被替换的版本会误触发那个信号 ——
# 线程里的异常不会中断主循环，只会让看门狗静默失效。
_REAL_SLEEP = time.sleep
# 审计 CW-19：心跳与停滞看门狗默认值
DEFAULT_HEARTBEAT_INTERVAL = 30.0
DEFAULT_STALL_TIMEOUT = 300.0


class LoopHeartbeat:
    """主循环的「心跳 + 停滞看门狗」（审计 CW-19）。

    改前轮询与处理在**同一线程串行**：处理期间完全不轮询（`--interval 3` 形同虚设），一旦
    handler 里的 Excel COM 调用永久挂起，整个程序停摆 —— 不写日志、不退出、没有心跳，
    运维只能靠「账本没更新」发现（`SOAK_REPORT.md:14-17` 实测过 `RPC 服务器不可用`）。

    这里不重写 Excel 自动化的线程模型（风险大于收益），而是给主循环装上**可观测性与自愈**：
      - `tick()`：每完成一轮就刷新一次（写心跳文件 + 记日志）；
      - `is_stalled()`：距上次心跳超过 `stall_timeout` 秒即判定停滞（0/负数=关闭）；
      - 看门狗线程周期调用 `check_stalled()`，停滞时写 ERROR 日志并以非零码退出进程
        （`--no-exit-on-stall` 可改为只告警），交给任务计划/守护进程重启。
    """

    def __init__(
        self,
        interval: float,
        stall_timeout: float,
        heartbeat_file=None,
        exit_on_stall: bool = True,
    ):
        self.interval = max(1.0, float(interval))
        self.stall_timeout = float(stall_timeout)
        self.heartbeat_file = Path(heartbeat_file) if heartbeat_file else None
        self.exit_on_stall = bool(exit_on_stall)
        self.last_tick = time.monotonic()
        self.rounds = 0
        self.stalled = False
        self.stop_event = None

    def tick(self, detail: str = "") -> None:
        """刷新心跳（每轮主循环结束调用一次）。"""
        self.last_tick = time.monotonic()
        self.rounds += 1
        if self.heartbeat_file is not None:
            try:
                self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
                self.heartbeat_file.write_text(
                    json.dumps(
                        {"rounds": self.rounds, "at": now_iso(), "detail": detail},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                log.debug("心跳文件写入失败：%s", self.heartbeat_file, exc_info=True)
        log.info("心跳 #%d%s", self.rounds, f"：{detail}" if detail else "")

    def age(self) -> float:
        """距上次心跳的秒数。"""
        return max(0.0, time.monotonic() - self.last_tick)

    def is_stalled(self) -> bool:
        if self.stall_timeout <= 0:
            return False
        return self.age() > self.stall_timeout

    def check_stalled(self) -> bool:
        """看门狗周期调用：停滞则置位并告警，返回是否停滞。"""
        if self.stalled or not self.is_stalled():
            return self.stalled
        self.stalled = True
        log.error(
            "主循环已 %.0f 秒没有推进（超过 --stall-timeout=%.0f 秒）："
            "疑似 handler 里的 Excel 调用挂起，已记录停滞告警%s",
            self.age(), self.stall_timeout,
            "，本进程即将退出以便守护进程重启"
            if self.exit_on_stall else "（--no-exit-on-stall：只告警）",
        )
        return True

    def watchdog_loop(self, sleep_fn=None) -> bool:
        """看门狗线程主体：停滞且启用退出时返回 True。"""
        sleeper = sleep_fn or _REAL_SLEEP
        while True:
            if self.stop_event is not None and self.stop_event.is_set():
                return False
            sleeper(self.interval)
            if self.check_stalled() and self.exit_on_stall:
                return True


def start_watchdog(hb: LoopHeartbeat, sleep_fn=_REAL_SLEEP):
    """启动看门狗线程；返回 (thread, stop_event)。

    停滞时用 `os._exit(3)` 结束进程：主线程此刻正卡在 COM 调用里，`sys.exit` 无法可靠生效，
    而「带着共享锁静默挂死」正是本缺陷要消灭的状态。
    """
    import threading

    sleeper = sleep_fn or _REAL_SLEEP
    stop_event = threading.Event()
    hb.stop_event = stop_event

    def _run():
        if hb.watchdog_loop(sleeper):
            log.error("看门狗判定主循环停滞：进程退出（退出码 3），请由守护进程重启")
            sys.stderr.flush()
            os._exit(3)

    thread = threading.Thread(target=_run, name="watcher-watchdog", daemon=True)
    thread.start()
    return thread, stop_event


# ==================== 小工具 ====================

def slug_of(key: str) -> str:
    return _SLUG_RE.sub("_", str(key)).strip("_").lower() or "key"


def func_name_of(key: str) -> str:
    return f"handle_{slug_of(key)}_passed"


def safe_dirname(key: str) -> str:
    """把合同类型 key 变成安全的输出子目录名。

    审计 CW-24：改前只替换 `\\/:*?"<>|`，`..`（以及 `.`/空白/空串）会被原样返回 ——
    `out_dir/..` 直接越出输出根目录（`default_archive` 还会 `mkdir(parents=True)`），
    即「合同类型的 key」可以决定文件落到哪里。这类 key 统一中性化为 `unknown`。
    """
    name = re.sub(r'[\\/:*?"<>|]', "_", str(key)).strip()
    if not name or set(name) == {"."}:
        return "unknown"
    return name


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_executed_at(value):
    """把 executedAt 解析为可比较的 datetime（无法解析返回 None）。

    审计 CW-05：改前水位线用**字符串**比较（`t > last_seen`），而后端序列化形态不固定：
    `…:46Z` 与 `…:46.731818Z` 字符串比较会认为后者更小（'.' < 'Z' 且长度不同）→ 同秒内后
    通过的合同被判为「不新」，永久漏账。
    """
    from datetime import datetime, timezone

    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def max_executed_at(values) -> str:
    """按解析后的时间取最大 executedAt（返回原始字符串形态）；无法解析的退回字符串比较。"""
    best = ""
    best_dt = None
    for v in values:
        if not v:
            continue
        dt = parse_executed_at(v)
        if not best:
            best, best_dt = str(v), dt
            continue
        if dt is None or best_dt is None:
            if str(v) > best:
                best = str(v)
            continue
        if dt > best_dt:
            best, best_dt = str(v), dt
    return best


def build_executed_query(
    competition_id: int | None, updated_after: str | None = None, page: int | None = None
) -> str:
    """拼 `/api/contracts` 的查询串（审计 CW-12）。

    传 `updated_after` 时走后端**增量协议**（`apps/common/sync.py` 的 `updatedAfter`）：只返回
    `updated_at` 晚于该基线的条目，**不分页**、服务端游标 —— 每轮请求量只与"这轮新增/变更"
    成正比，而不是与历史 EXECUTED 合同总量成正比（改前每轮把全部历史分页拉一遍，
    合同数 N ⇒ 每轮 ceil(N/200)+1 个重请求，间隔 3 秒且永不衰减）。
    """
    params = {"status": "EXECUTED"}
    if competition_id is not None:
        # 审计 CW-11：改前用 `if competition_id:` —— 0 被视为「不筛选」，静默跨比赛
        params["competitionId"] = str(competition_id)
    if updated_after:
        params["updatedAfter"] = str(updated_after)
    else:
        params["page"] = str(page or 1)
        params["pageSize"] = "200"
    return urllib.parse.urlencode(params)


def next_backoff(previous: float, base: float, cap: float = MAX_BACKOFF_SECONDS, rng=None) -> float:
    """指数退避 + 抖动（审计 CW-12）：失败后下一轮等待时间。

    改前无论成功失败都固定 `time.sleep(max(0.5, --interval))` —— 后端不可用时仍以同一节奏
    持续打请求，且永不衰减。现在是 `min(cap, max(base, previous*2))` 再叠加 0~25% 抖动
    （多实例/多进程同频重试的"惊群"会被抖动打散）。
    """
    rnd = rng or random.random
    base = max(0.5, float(base))
    nxt = min(float(cap), max(base, float(previous) * 2))
    return round(nxt * (1.0 + 0.25 * rnd()), 3)


# 审计 CW-20：跨机器共享的实例互斥锁（放在共享盘/共享目录上）
LOCK_STALE_SECONDS = 90.0


class SharedLock:
    """放在**共享位置**上的单实例锁（审计 CW-20）。

    改前只用 `socket.bind(("127.0.0.1", --port))` 做互斥 —— 它只在当前主机有效：两台机器
    （`README.md:175-179` 鼓励用任务计划/`@reboot` 自启，多机部署很常见）或本机换 `--port`
    起第二个实例时，两个实例会各自拉取同一批合同、各自记账（账本路径相同则两个 Excel 交错写
    同一文件，后保存者覆盖前者；各用副本则会话账本分叉），而文档「重复启动会被端口锁拒绝」
    给出了过强的安全感。

    现在把互斥点放到**共享资源**上：`--lock-file` 指向共享路径（默认本地 `data/watcher.lock`），
    用「独占创建 + 心跳 + 过期接管」实现：

    - `acquire()`：目标存在且**心跳未过期** ⇒ 返回 False（另一个实例在跑）；
      心跳过期（进程被杀/断电/网络分区）⇒ 接管并告警，避免死锁；
    - `heartbeat()`：每轮刷新 mtime，让别的实例知道我们还活着；
    - `release()`：正常退出时删除锁文件。
    """

    def __init__(self, path, stale_after: float = LOCK_STALE_SECONDS, owner: str | None = None):
        self.path = Path(path)
        self.stale_after = float(stale_after)
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}"

    def _read_owner(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def age(self) -> float:
        """锁文件的年龄（秒）；不存在返回 -1。"""
        try:
            return max(0.0, time.time() - self.path.stat().st_mtime)
        except OSError:
            return -1.0

    def acquire(self) -> tuple[bool, str]:
        """尝试获取锁，返回 `(是否拿到, 说明)`。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # `x` 模式是原子的：文件已存在即失败（比"先判断再创建"没有竞态）
            with self.path.open("x", encoding="utf-8") as fh:
                fh.write(self.owner)
        except FileExistsError:
            age = self.age()
            other = self._read_owner()
            if 0 <= age < self.stale_after:
                return False, (
                    f"另一个监听实例正在运行（锁 {self.path} 由 {other or '未知'} 持有，"
                    f"{age:.0f} 秒前心跳）：本实例退出。若确认对方已停止，"
                    f"请删除该锁文件或等 {self.stale_after:.0f} 秒心跳过期后重试"
                )
            # 心跳过期：接管（否则被 kill -9 / 断电的实例会把锁永久占住）
            try:
                self.path.write_text(self.owner, encoding="utf-8")
                log.warning(
                    "接管控件锁（%s）：原持有者 %s 的心跳已过期（%.0f 秒），判定为已停止运行",
                    self.path, other or "未知", age,
                )
                return True, (
                    f"接管控件锁 {self.path}：原持有者 {other or '未知'} 的心跳已过期"
                    f"（{age:.0f} 秒），判定为已停止运行"
                )
            except OSError as e:
                return False, f"接管锁 {self.path} 失败：{e}"
        except OSError as e:
            return False, f"无法创建锁文件 {self.path}：{e}"
        return True, f"已取得单实例锁 {self.path}（owner={self.owner}）"

    def heartbeat(self) -> None:
        """刷新心跳（每轮调用一次）。"""
        try:
            self.path.write_text(self.owner, encoding="utf-8")
        except OSError:
            log.debug("锁心跳刷新失败：%s", self.path, exc_info=True)

    def release(self) -> None:
        try:
            if self.path.exists() and self._read_owner() == self.owner:
                self.path.unlink()
        except OSError:
            log.debug("锁文件删除失败：%s", self.path, exc_info=True)


# ==================== HTTP（标准库，只读后端） ====================

def http_json(method: str, url: str, token: str | None = None, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Backend:
    """后端客户端：自动登录与 401 自动续期。"""

    def __init__(self, server: str, username: str, password: str):
        self.server = server.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        # 审计 CW-12：最近一次增量拉取拿到的服务端时间（下一轮用它作游标）
        self.last_server_time: str | None = None

    def login(self) -> None:
        env = http_json(
            "POST", f"{self.server}/api/auth/login",
            body={"username": self.username, "password": self.password},
        )
        if env.get("code") != 0:
            raise RuntimeError(f"登录失败：{env.get('message')}")
        self.token = env["data"]["token"]

    def api(self, path: str) -> dict:
        if not self.token:
            self.login()
        try:
            env = http_json("GET", f"{self.server}{path}", self.token)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.login()
                env = http_json("GET", f"{self.server}{path}", self.token)
            else:
                raise
        if env.get("code") != 0:
            raise RuntimeError(f"接口 {path} 返回错误：{env.get('message')}")
        return env["data"]

    def fetch_contract_types(self) -> list[dict]:
        """全量合同类型目录（含 id/key/name）。"""
        data = self.api("/api/contract-types?enabledOnly=false")
        return data if isinstance(data, list) else data.get("items") or []

    def fetch_executed_ids(
        self, competition_id: int | None, updated_after: str | None = None
    ) -> list[tuple[int, str]]:
        """EXECUTED 合同 id 与 executedAt 列表（executedAt 用于增量判断）。

        审计 CW-04：改前按 offset 分页（page=N）逐页拼接，期间有合同执行/撤销会让分页漂移，
        同一条合同可能重复出现在两页里 → 同轮重复分发（重复记账）。这里按合同 id 去重，
        同 id 保留更新的 executedAt。

        审计 CW-12：传 `updated_after` 时改用后端增量协议（服务端游标、不分页），避免每轮把
        全部历史 EXECUTED 合同（含完整 DSL/graph）重新拉一遍；服务端时间存到
        `self.last_server_time` 供下一轮当游标。
        """
        by_id: dict[int, str] = {}
        # 审计 CW-27：状态已是 EXECUTED 但 executedAt 为空的合同原本被**静默**忽略
        # （文档还断言这种数据不存在）。这里至少给出告警，便于发现后端数据异常。
        missing_executed_at: list[int] = []
        page: int | None = 1
        while True:
            query = build_executed_query(competition_id, updated_after, page)
            data = self.api(f"/api/contracts?{query}")
            batch = data.get("items") or []
            total = data.get("total") or len(batch)
            for it in batch:
                if not it.get("executedAt"):
                    try:
                        missing_executed_at.append(int(it["id"]))
                    except (KeyError, TypeError, ValueError):
                        pass
                    continue
                cid = int(it["id"])
                et = str(it["executedAt"])
                prev = by_id.get(cid)
                by_id[cid] = et if prev is None else max_executed_at([prev, et])
            if data.get("incremental"):
                # 增量响应本身就是完整结果（服务端已按 updated_at 过滤），不再翻页
                server_time = data.get("serverTime")
                if server_time:
                    self.last_server_time = str(server_time)
                page = None
                break
            if not batch or len(batch) >= total:
                break
            page = (page or 1) + 1
        if missing_executed_at:
            log.warning(
                "有 %d 份 EXECUTED 合同没有 executedAt（%s…）：本轮按「未通过」忽略，"
                "请检查后端数据（这些合同不会被记账）",
                len(missing_executed_at), missing_executed_at[:10],
            )
        return list(by_id.items())

    def fetch_contract_detail(self, contract_id: int) -> dict:
        return self.api(f"/api/contracts/{contract_id}")


# ==================== handlers.py 的生成 / 改名 / 加载 ====================

def encode_marker_key(key: str) -> str:
    """把 key 编码成「单行、无引号风险」的形态写进标注行（审计 CW-07）。

    后端对 ContractType.key 只校验非空与长度，可以出现换行或引号。标注行是 python 注释，
    换行会把一条标注行拆成两行（MARKER_RE 不再匹配、`in text` 检查永远失败 → 每轮重复追加）；
    docstring 里直接内插 `"` 还会提前终止字符串 → handlers.py 变成语法错误、**所有** handler
    失效。这里统一转义，读取时用 decode_marker_key() 还原成原始 key。
    """
    return str(key).replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")


def decode_marker_key(text: str) -> str:
    """还原 encode_marker_key() 的转义（对旧文件里的原样 key 是幂等的）。"""
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def marker_line(key: str) -> str:
    return MARKER_PREFIX + encode_marker_key(key) + MARKER_SUFFIX


def write_handlers_atomic(text: str) -> bool:
    """原子写入 handlers.py：先 compile 校验，再备份 .bak 并 os.replace。

    审计 CW-07：改前直接 write_text、既不校验也不备份 —— 生成出语法错误的文件后不会自愈
    （load_handlers 捕获异常返回 {}，全部类型一起退化为默认存档）。校验失败一律不落盘。
    """
    try:
        compile(text, str(HANDLERS_FILE), "exec")
    except SyntaxError as e:
        log.error(
            "拒绝写入 handlers.py：生成的代码无法通过语法校验（%s，第 %s 行），已保持原文件不变",
            e.msg, e.lineno,
        )
        return False
    try:
        if HANDLERS_FILE.exists():
            bak = HANDLERS_FILE.with_name(HANDLERS_FILE.name + ".bak")
            bak.write_text(HANDLERS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        tmp = HANDLERS_FILE.with_name(HANDLERS_FILE.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        import os

        os.replace(tmp, HANDLERS_FILE)
    except OSError:
        log.exception("handlers.py 写入失败（已保留 .bak 与临时文件）")
        return False
    return True


def build_default_section(key: str) -> str:
    func = func_name_of(key)
    # 审计 CW-07：docstring 里用转义后的展示名（无反斜杠歧义、无引号），不再直接内插原始 key
    display = encode_marker_key(key).replace('"', "'")
    return (
        "\n\n" + marker_line(key) + "\n"
        f"def {func}(contract: dict, ctx: dict) -> None:\n"
        f'    """{display} 类型合同通过后的处理（自动生成的默认函数）。\n'
        "    定制：删除下面这行 [auto-default] 注释后，替换为你自己的实现。\n"
        "    可用：ctx['out_dir']（输出根目录）、ctx['typeKey']（当前合同类型 key）、\n"
        "          ctx['default_archive'](contract, ctx)（通用存档）。\"\"\"\n"
        "    # [auto-default]\n"
        '    ctx["default_archive"](contract, ctx)\n'
    )


def section_span(lines: list[str], marker_index: int) -> tuple[int, int]:
    """返回从 marker 行开始到下一 marker（或文件尾）的行区间 [start, end)。"""
    start = marker_index
    end = len(lines)
    for i in range(marker_index + 1, len(lines)):
        if MARKER_RE.match(lines[i].strip()):
            end = i
            break
    return start, end


def ensure_handlers_file() -> None:
    if not HANDLERS_FILE.exists():
        HANDLERS_FILE.write_text(
            "# 合同类型处理函数文件（由 contract_watcher.py 自动维护）。\n"
            "# 自动生成的默认函数会按 ContractType.key 追加/改名；在函数体内修改即可定制，\n"
            "# 程序只会调整『标注行与函数名』，不会覆盖你的函数体。\n",
            encoding="utf-8",
        )


def func_def_pattern(func: str) -> re.Pattern:
    """匹配 `def <func>(`（含缩进），用于判断函数名是否已被占用。"""
    return re.compile(rf"^[ \t]*def[ \t]+{re.escape(func)}[ \t]*\(", re.MULTILINE)


def upsert_handler_for_key(key: str) -> bool:
    """handlers.py 中为该 key 生成默认函数（已存在则跳过）。返回是否新增。

    审计 CW-06：改前只检查「标注行是否存在」。用户按说明删掉标注块、自己写了
    `handle_<key>_passed` 后，标注行消失 → 这里会在文件**末尾**再追加一个同名 def，
    Python 后者生效 ⇒ 用户的自定义实现被静默屏蔽（且日志仍显示「已按类型处理」）。
    现在追加前先检查同名函数是否已存在：已存在就跳过并告警，绝不生成第二个同名 def。
    """
    text = HANDLERS_FILE.read_text(encoding="utf-8")
    if marker_line(key) in text:
        return False
    func = func_name_of(key)
    if func_def_pattern(func).search(text):
        log.warning(
            "key=%s 已有同名函数 %s（用户自定义或与其它 key 的 slug 冲突），"
            "不再追加自动生成的默认块（避免同名 def 后者生效屏蔽用户实现）", key, func,
        )
        return False
    return write_handlers_atomic(text.rstrip() + build_default_section(key) + "\n")


def rename_handler_key(old_key: str, new_key: str) -> bool:
    """类型 key 改名：只更新标注行与函数名，函数体原样保留。返回是否修改。"""
    if old_key == new_key:
        return False
    text = HANDLERS_FILE.read_text(encoding="utf-8")
    lines = text.split("\n")
    old_func = func_name_of(old_key)
    new_func = func_name_of(new_key)
    changed = False
    for i, line in enumerate(lines):
        if line.strip() == marker_line(old_key):
            lines[i] = marker_line(new_key)
            changed = True
        elif line.lstrip().startswith("def ") and old_func in line:
            # 审计 CW-25：改前是 `line.replace(old_func, new_func)` 的子串替换 ——
            # 当另一个 key 的函数名把 old_func 作为前缀时（如 key `a` → handle_a_passed、
            # key `a_passed` → handle_a_passed_passed），改名 `a` 会连带把另一个函数改成
            # handle_b_passed_passed，而它的标注行仍是 a_passed ⇒ 该 key 的 handler 静默失效。
            # 只替换「def <old_func>(」这一处，且要求函数名完整匹配。
            lines[i] = re.sub(
                rf"(def\s+){re.escape(old_func)}(\s*\()",
                lambda m: f"{m.group(1)}{new_func}{m.group(2)}",
                line,
                count=1,
            )
            changed = True
    if changed:
        return write_handlers_atomic("\n".join(lines))
    return changed


def load_handlers() -> dict[str, object]:
    """加载 handlers.py 并返回 {key: 处理函数}（按标注行 key → 函数名解析）。"""
    ensure_handlers_file()
    text = HANDLERS_FILE.read_text(encoding="utf-8")
    # 标注行里的 key 是转义形态（CW-07），这里还原成后端原始 key，便于 registry 按 key 命中
    keys = [decode_marker_key(m.group(1)) for m in MARKER_RE.finditer(text)]
    module_name = f"watcher_handlers_{int(time.time() * 1000)}"
    spec = importlib.util.spec_from_file_location(module_name, HANDLERS_FILE)
    if spec is None or spec.loader is None:
        return {}
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - 用户代码语法错误等：降级为默认行为
        log.exception("handlers.py 加载失败，本轮使用内置默认行为")
        return {}
    registry: dict[str, object] = {}
    by_func: dict[str, list[str]] = {}
    for key in keys:
        func = func_name_of(key)
        by_func.setdefault(func, []).append(key)
    # 审计 CW-06：slug 相同（如 material-procurement 与 material_procurement）的多个 key
    # 会共用同一个函数名，模块级「后定义的 def 生效」⇒ 其中一个 key 的处理逻辑静默失效。
    for func, key_list in by_func.items():
        if len(key_list) > 1:
            log.warning(
                "函数名冲突：key=%s 的 slug 相同（都映射到 %s），它们会共用同一实现，"
                "请把其中一个 ContractType.key 改成不冲突的形态",
                key_list, func,
            )
    for key in keys:
        fn = getattr(mod, func_name_of(key), None)
        if callable(fn):
            if key in registry:
                log.warning("key=%s 的函数名冲突（%s），后者未生效", key, func_name_of(key))
                continue
            registry[key] = fn
    # 审计 CW-06：用户可能删掉自动生成的标注块、自己写 `handle_<key拼音形态>_passed`。
    # 没有标注行就没有 key→函数的映射，改前这种「按命名约定写」的实现永远不会被注册
    # （退化为默认存档）。这里把**未被标注行占用**的约定命名函数按 slug 也登记一份，
    # dispatch 找不到原 key 时会退回 slug 查找。
    claimed = {id(fn) for fn in registry.values()}
    for name, obj in vars(mod).items():
        m = re.fullmatch(r"handle_(.+)_passed", name)
        if not m or not callable(obj) or id(obj) in claimed:
            continue
        slug = m.group(1)
        if slug in registry:
            continue
        registry[slug] = obj
        log.info("按命名约定注册处理函数 %s → key(slug)=%s（无标注行）", name, slug)
    return registry


# ==================== 处理执行 ====================

def default_archive(contract: dict, ctx: dict) -> Path:
    """内置默认行为：把合同全量 JSON 存档到 out_dir/<typeKey>/，
    并自动同时产出翻译版（可读）JSON：<同名>_readable.json。

    翻译使用同目录 readable.py（translate_contract）；翻译失败不影响原始存档。
    """
    key = ctx.get("typeKey") or (contract.get("contractType") or {}).get("key") or "unknown"
    sub = Path(ctx["out_dir"]) / safe_dirname(key)
    sub.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    f = sub / f"contract_{contract['id']}_{stamp}.json"
    # 审计 CW-23：时间戳只到秒 —— 同一秒内处理两次（正是 CW-03/04 的重复路径）会**静默覆盖**
    # 上一份存档，重复处理不留任何痕迹（恰好掩盖了重复记账的现场）。已存在时自动加序号。
    seq = 1
    while f.exists():
        seq += 1
        f = sub / f"contract_{contract['id']}_{stamp}_{seq}.json"
    f.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from readable import translate_contract

        rec = translate_contract(contract)
        if isinstance(rec, dict):
            rf = f.with_name(f.stem + "_readable.json")
            rf.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - 翻译失败不影响原始存档
        log.debug("翻译版记录生成失败 contract=%s（原始存档不受影响）", contract.get("id"), exc_info=True)
    return f


def dispatch(contract: dict, registry: dict, out_dir: Path, competition_id: int | None) -> bool:
    """分发一个已执行合同；返回是否处理成功。

    改前：异常在此被吞掉且无返回值，调用方（主循环）只按列表 max 推进水位 —— 处理失败的
    合同被水位越过，永久静默漏记、永不重试、无告警（审计 CW-02）。现在把成败回传给调用方，
    由调用方记入待处理队列并推迟水位。
    """
    key = (contract.get("contractType") or {}).get("key") or "unknown"
    ctx = {
        "out_dir": out_dir,
        "typeKey": key,
        "competitionId": contract.get("competitionId", competition_id),
        "default_archive": default_archive,
    }
    fn = registry.get(key)
    if fn is None:
        # 用户自定义函数常见于「没有标注行、按 handle_<slug>_passed 约定命名」（审计 CW-06），
        # 这类实现按 slug 登记，故这里退回 slug 查找，避免它们被当成「未注册」而只做默认存档。
        fn = registry.get(slug_of(key))
    try:
        if fn is None:
            log.info("未注册处理函数 type=%s → 默认存档 contract=#%s", key, contract["id"])
            f = default_archive(contract, ctx)
            log.info("已默认存档 contract=#%s → %s", contract["id"], f)
        else:
            fn(contract, ctx)
            log.info("已按类型处理 contract=#%s type=%s handler=%s", contract["id"], key,
                     getattr(fn, "__name__", fn))
        return True
    except Exception:  # noqa: BLE001 - 单个合同处理失败不影响后续与网页端
        log.exception("处理合同 #%s(type=%s) 失败：记入待处理队列，水位不越过它，下一轮重试",
                      contract["id"], key)
        return False


# ==================== 主循环 ====================

def save_state(state: dict) -> None:
    """持久化进度（原子写，审计 CW-13）。

    改前直接 `write_text`：写一半被中断（断电 / 进程被杀 / 磁盘满）会留下**截断的 JSON**，
    下一次启动 `json.loads` 抛错后静默把 state 当空对象 → 水位与待处理队列一起丢失
    （旧版本会因此全量重放历史合同；现在虽不会重放，但待处理合同与目录缓存也会丢）。
    改为临时文件 + `os.replace` 原子替换，并保留一份 .bak 便于事后诊断。
    """
    import os

    payload = json.dumps(state, ensure_ascii=False)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(payload, encoding="utf-8")
        if STATE_FILE.exists():
            try:
                STATE_FILE.with_name(STATE_FILE.name + ".bak").write_text(
                    STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8"
                )
            except OSError:
                pass
        os.replace(tmp, STATE_FILE)
    except OSError:
        log.exception("进度文件写入失败：%s", STATE_FILE)


def establish_baseline(
    backend: "Backend", state: dict, competition_id: int | None, backfill: bool
) -> bool:
    """建立首次运行基线（进度水位），返回水位是否可用。

    改前：`fetch_executed_ids` 抛异常时会把 `lastExecutedAt=""` **写进 state** —— 水位一旦为
    空，下一轮所有历史 EXECUTED 合同都被判为「新通过」而全量重放，配合无幂等键的处理函数就是
    重复记账（审计 CW-01：一次网络抖动即触发）。

    现在：拉取失败不写水位（保持「未建立」状态），本轮不处理任何合同，下一轮重试；
    只有确实拿到列表（哪怕是空列表）才写入基线。`--backfill` 是用户显式要求回填存量，
    此时才允许空水位。
    """
    if "baselineAt" not in state:
        state["baselineAt"] = now_iso()
    if "lastExecutedAt" in state:
        return True
    if backfill:
        state["lastExecutedAt"] = ""
        save_state(state)
        log.warning("首次运行基线：已指定 --backfill，水位置空 → 存量已执行合同将全部处理一次")
        return True
    try:
        rows = backend.fetch_executed_ids(competition_id)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # 审计 CW-10：认证失败必须冒泡到主循环计数（否则基线阶段会永远静默重试）
            raise
        save_state(state)  # 只落 baselineAt，不落 lastExecutedAt
        log.warning(
            "首次运行基线建立失败（%s）：本轮不处理任何合同，下一轮重试；"
            "不会写入空水位（否则历史合同会被全量重放）", e,
        )
        return False
    except Exception as e:  # noqa: BLE001 - 拿不到基线就不能开始处理
        save_state(state)  # 只落 baselineAt，不落 lastExecutedAt
        log.warning(
            "首次运行基线建立失败（%s）：本轮不处理任何合同，下一轮重试；"
            "不会写入空水位（否则历史合同会被全量重放）", e,
        )
        return False
    state["lastExecutedAt"] = max_executed_at(t for _, t in rows)
    save_state(state)
    log.info(
        "首次运行基线已建立：lastExecutedAt=%r（%d 条历史已执行合同不再处理；如需回填请用 --backfill）",
        state["lastExecutedAt"], len(rows),
    )
    return True


def process_fresh_contracts(
    backend: "Backend", state: dict, registry: dict, out_dir: Path, competition_id: int | None
) -> None:
    """处理「新通过」的合同，并安全推进水位（审计 CW-02）。

    改前：dispatch 吞异常且无返回值，水位按列表 max 推进 —— 处理失败或详情状态不符的合同
    被水位越过，永久静默漏记、永不重试、无告警。

    现在：
      - 上一轮失败的合同存于 state["pendingExecuted"]，每轮先重试，成功才移出队列；
      - 水位只推进到「已成功处理」的最新 executedAt，失败合同不会被水位越过；
      - 详情状态不符（列表说 EXECUTED、详情说不是）同样记入待处理并告警，而不是静默跳过。
    """
    rows = backend.fetch_executed_ids(competition_id, state.get("lastUpdatedAt"))
    # 审计 CW-12：记下服务端时间作为下一轮的增量游标（增量协议返回 serverTime）
    server_time = getattr(backend, "last_server_time", None)
    if server_time:
        state["lastUpdatedAt"] = server_time
    watermark = state.get("lastExecutedAt") or ""
    # 水位线比较必须按时间而非字符串（审计 CW-05）：'…:46Z' vs '…:46.731818Z' 字符串比较会反向
    watermark_dt = parse_executed_at(watermark)
    pending = state.get("pendingExecuted") or []

    def is_newer(et: str) -> bool:
        dt = parse_executed_at(et)
        if dt is None:
            return False  # 无法解析的时间不当作新合同，避免每轮重放
        if watermark_dt is None:
            return True  # 水位不可解析（旧版本写入的异常值）：按「新」处理一次
        return dt > watermark_dt

    # 待处理队列（含上一轮失败的）+ 本轮新出现的，按 executedAt 升序、按合同 id 去重
    queue: dict[int, str] = {}
    for item in pending:
        try:
            queue[int(item["id"])] = str(item.get("executedAt") or "")
        except (KeyError, TypeError, ValueError):
            continue
    for cid, et in rows:
        if is_newer(et):
            queue[int(cid)] = str(et)
    items = sorted(queue.items(), key=lambda kv: (parse_executed_at(kv[1]) or datetime.min.replace(tzinfo=timezone.utc), kv[0]))

    advanced_to = watermark
    still_pending: list[dict] = []
    for cid, et in items:
        try:
            contract = backend.fetch_contract_detail(cid)
        except Exception as e:  # noqa: BLE001 - 拉详情失败同样不能丢
            log.warning("拉取合同 #%s 详情失败（%s）→ 记入待处理，下一轮重试", cid, e)
            still_pending.append({"id": cid, "executedAt": et})
            continue
        if contract.get("status") != "EXECUTED":
            log.warning(
                "合同 #%s 详情状态为 %s（列表却给出 executedAt=%s）→ 记入待处理并告警，不推进水位",
                cid, contract.get("status"), et,
            )
            still_pending.append({"id": cid, "executedAt": et})
            continue
        if dispatch(contract, registry, out_dir, competition_id):
            if parse_executed_at(et) is not None and (
                parse_executed_at(advanced_to) is None or parse_executed_at(et) > parse_executed_at(advanced_to)
            ):
                advanced_to = et
        else:
            still_pending.append({"id": cid, "executedAt": et})

    state["pendingExecuted"] = still_pending
    # 审计 CW-12：增量游标（lastUpdatedAt）也必须落盘 —— 否则重启后会退回全量拉取
    if advanced_to != watermark:
        state["lastExecutedAt"] = advanced_to
        save_state(state)
    elif still_pending or server_time:
        # 水位没动也要落盘：待处理队列必须在重启后继续重试；增量游标同理
        save_state(state)
    if still_pending:
        log.error(
            "仍有 %d 个合同未处理成功（%s），已保留在待处理队列，下一轮重试；"
            "请检查 handlers.py 与输出目录权限",
            len(still_pending), [p["id"] for p in still_pending],
        )


def sync_catalog(
    backend: Backend, state: dict, registry_ref: list, min_interval: float = DEFAULT_CATALOG_INTERVAL
) -> bool:
    """类型目录同步：新 key 生成默认函数；改名的 key 自动改名；返回目录是否有变化。

    审计 CW-12：改前每轮都全量拉一次 `/api/contract-types`（含完整 DSL），而合同类型的
    新建/改名是低频事件。现在按 `min_interval`（默认 60 秒，`--catalog-interval 0` 可关闭节流）
    限制最小同步间隔；状态存 `state["catalogSyncedAt"]`（单调时钟秒）。
    """
    now = time.monotonic()
    last = state.get("catalogSyncedAt")
    if min_interval and min_interval > 0 and isinstance(last, (int, float)) and now - last < min_interval:
        return False
    state["catalogSyncedAt"] = now
    try:
        types = backend.fetch_contract_types()
    except Exception as e:  # noqa: BLE001 - 无 contractType:view 时降级（仅影响自动生成）
        log.warning("获取合同类型目录失败（需 contractType:view 才能自动生成/改名）：%s", e)
        return False
    catalog = state.setdefault("catalog", {})  # {typeId: key}
    changed = False
    for t in types:
        tid, key = str(t.get("id")), str(t.get("key") or "")
        if not tid or not key:
            continue
        old = catalog.get(tid)
        if old is None:
            if upsert_handler_for_key(key):
                log.info("类型目录发现新 key=%s → 已自动生成默认函数", key)
                changed = True
        elif old != key:
            if rename_handler_key(old, key):
                log.info("类型 key 改名 %s → %s（typeId=%s）→ 已自动改名并保留函数体", old, key, tid)
                changed = True
        catalog[tid] = key
    if changed:
        registry_ref[0] = load_handlers()
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="合同通过监听程序（独立运行）")
    ap.add_argument("--server", required=True)
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--competition", type=int, default=None)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument(
        "--catalog-interval", type=float, default=DEFAULT_CATALOG_INTERVAL,
        help="合同类型目录的最小同步间隔（秒，0=每轮都同步）",
    )
    ap.add_argument("--out-dir", default=str(RECORDS_DIR))
    ap.add_argument("--port", type=int, default=47653, help="单实例互斥端口（仅本机有效）")
    ap.add_argument(
        "--lock-file", default=str(WATCHER_DIR / "data" / "watcher.lock"),
        help="跨机器共享的单实例锁文件（多机跑同一账本时指向同一个共享路径）",
    )
    ap.add_argument("--backfill", action="store_true", help="首次运行也处理存量已执行合同")
    ap.add_argument("--verbose", action="store_true", help="控制台同步输出明细")
    # 审计 CW-19：心跳与停滞看门狗（轮询/处理同线程串行时，挂起的唯一可观测信号）
    ap.add_argument(
        "--heartbeat-interval", type=float, default=DEFAULT_HEARTBEAT_INTERVAL,
        help="心跳/看门狗检查周期（秒）",
    )
    ap.add_argument(
        "--stall-timeout", type=float, default=DEFAULT_STALL_TIMEOUT,
        help="主循环多久没推进就判定停滞并退出（秒；0=关闭看门狗）",
    )
    ap.add_argument(
        "--heartbeat-file", default=str(WATCHER_DIR / "data" / "heartbeat.json"),
        help="心跳文件路径（外部监控可读；留空则只写日志）",
    )
    ap.add_argument(
        "--no-exit-on-stall", action="store_true",
        help="检测到停滞时只告警、不退出（默认退出以便守护进程重启）",
    )
    args = ap.parse_args()

    # 审计 CW-11：`--competition 0` / 负数会被下游的 `if competition_id:` 当成「不筛选」，
    # 于是监听程序悄悄跨**所有**比赛记账（把 A 比赛的合同记到 B 的账上）。这里显式拒绝。
    if args.competition is not None and args.competition <= 0:
        print(
            f"✗ --competition 必须是正整数（收到 {args.competition}）："
            "0/负数会被当成「不筛选」而跨比赛混记，已拒绝启动",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        filename=str(LOG_FILE), filemode="a", encoding="utf-8",
    )
    if args.verbose:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        log.addHandler(console)

    # 单实例互斥（本机端口；退出自动释放）
    try:
        lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_sock.bind(("127.0.0.1", args.port))
        lock_sock.listen(1)
    except OSError:
        print(f"另一个监听实例已在运行（端口 {args.port} 被占用），本实例退出。"
              f"如需更换端口请用 --port。", file=sys.stderr)
        return 1

    # 审计 CW-20：端口锁只在**本机**有效。真正的互斥点必须放在共享资源上（账本/记录目录所在
    # 的共享盘），否则两台机器（或本机换 --port 起的第二个实例）会各自记账 ⇒ 重复入账。
    instance_lock = SharedLock(args.lock_file)
    acquired, why = instance_lock.acquire()
    if not acquired:
        print(f"✗ {why}", file=sys.stderr)
        return 1
    log.info("%s", why)

    WATCHER_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            # 审计 CW-13：改前静默 `state = {}` —— 损坏时水位/待处理队列静默丢失且无任何提示。
            # 现在记 error 并把坏文件改名留证，便于排查（内容不再被下一轮覆盖）。
            log.error("进度文件损坏（%s: %s），已按空进度启动；坏文件保留为 %s.corrupt",
                      type(e).__name__, e, STATE_FILE.name)
            try:
                STATE_FILE.replace(STATE_FILE.with_name(STATE_FILE.name + ".corrupt"))
            except OSError:
                pass
            state = {}

    backend = Backend(args.server, args.username, args.password)
    try:
        backend.login()
    except Exception as e:  # noqa: BLE001
        print(f"启动失败（检查服务器地址/账号密码/是否已改密）：{e}", file=sys.stderr)
        return 1

    ensure_handlers_file()
    registry: list = [load_handlers()]
    last_mtime = HANDLERS_FILE.stat().st_mtime
    sync_catalog(backend, state, registry, args.catalog_interval)

    # 首次运行基线：未建立成功前不处理任何合同（审计 CW-01）
    # 连续认证失败计数（审计 CW-10）：达到阈值就明确报错退出，不再无限静默失败
    consecutive_auth_failures = 0
    try:
        baseline_ready = establish_baseline(backend, state, args.competition, args.backfill)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        # 启动时就 401：不直接崩，交给主循环按 CW-10 的阈值处理
        consecutive_auth_failures = 1
        baseline_ready = False
        log.warning("登录态失效（连续第 1 次），下一轮自动重登")
    log.info("监听启动 server=%s competition=%s out=%s backfill=%s",
             args.server, args.competition, out_dir, args.backfill)

    # 审计 CW-19：心跳 + 停滞看门狗（轮询与处理同线程串行，挂起时这是唯一的可观测信号）
    heartbeat = LoopHeartbeat(
        args.heartbeat_interval, args.stall_timeout,
        heartbeat_file=args.heartbeat_file or None,
        exit_on_stall=not args.no_exit_on_stall,
    )
    if args.stall_timeout > 0:
        start_watchdog(heartbeat)
        log.info(
            "已启用停滞看门狗：每 %.0f 秒检查一次，超过 %.0f 秒无进展即%s；心跳文件 %s",
            heartbeat.interval, heartbeat.stall_timeout,
            "退出进程（退出码 3）" if heartbeat.exit_on_stall else "仅告警",
            heartbeat.heartbeat_file or "（只写日志）",
        )
    else:
        log.info("未启用停滞看门狗（--stall-timeout 0）")

    # 审计 CW-12：失败退避 —— 后端不可用时按指数+抖动退避，成功后立刻恢复常规节奏
    consecutive_failures = 0
    current_delay = max(0.5, args.interval)

    try:
        while True:
            round_failed = False
            try:
                # 0) 基线未建立（首次拉取失败）→ 每轮重试，期间不处理合同
                if not baseline_ready:
                    baseline_ready = establish_baseline(
                        backend, state, args.competition, args.backfill
                    )
                    if not baseline_ready:
                        round_failed = True
                        consecutive_failures += 1
                        current_delay = next_backoff(current_delay, args.interval)
                        time.sleep(current_delay)
                        continue
                # 1) handlers.py 被手动修改 → 热加载
                try:
                    mtime = HANDLERS_FILE.stat().st_mtime
                    if mtime != last_mtime:
                        last_mtime = mtime
                        registry[0] = load_handlers()
                        log.info("handlers.py 已变更，热加载完成")
                except OSError:
                    pass
                # 2) 类型目录同步（新 key 生成 / key 改名自动改名；按 --catalog-interval 节流）
                sync_catalog(backend, state, registry, args.catalog_interval)
                # 3) 检测合同通过并处理；水位只在成功处理后推进（失败进待处理队列重试）
                before_watermark = state.get("lastExecutedAt")
                process_fresh_contracts(backend, state, registry[0], out_dir, args.competition)
                # 审计 CW-19：每完成一轮就刷新心跳（看门狗据此判断主循环是否还在推进）
                advanced = state.get("lastExecutedAt") != before_watermark
                heartbeat.tick(
                    f"水位={state.get('lastExecutedAt') or '（空）'}"
                    + ("（本轮有推进）" if advanced else "")
                    + (f"、待处理 {len(state.get('pendingExecuted') or [])} 个"
                       if state.get("pendingExecuted") else "")
                )
            except urllib.error.HTTPError as e:
                round_failed = True
                if e.code == 401:
                    consecutive_auth_failures += 1
                    log.warning(
                        "登录态失效（连续第 %d 次），下一轮自动重登", consecutive_auth_failures
                    )
                    # 审计 CW-10：改前凭据失效后无限静默失败 —— 进程不退、不告警、状态不变，
                    # 用户以为程序在正常工作，实际上一条合同都不会再被处理。连续失败到阈值即
                    # 明确报错退出，让守护进程/运维能发现。
                    if consecutive_auth_failures >= MAX_CONSECUTIVE_AUTH_FAILURES:
                        msg = (
                            f"连续 {consecutive_auth_failures} 轮登录失败（账号被禁用/改密/密码变更？），"
                            "已停止监听：请更新启动参数里的账号密码后重新运行"
                        )
                        log.error(msg)
                        print(f"✗ {msg}", file=sys.stderr)
                        return 1
                else:
                    consecutive_auth_failures = 0
                    log.warning("后端请求失败 HTTP %s", e.code)
            except Exception:  # noqa: BLE001 - 静默容错：任何异常都不影响下一轮与网页端
                round_failed = True
                log.exception("本轮执行异常（已隔离，继续下一轮）")

            # 审计 CW-12：改前无论成败都固定 `time.sleep(max(0.5, --interval))` —— 后端不可用时
            # 仍以同一节奏持续打请求且永不衰减。现在失败时指数退避（含抖动，上限 60s），
            # 成功后立即回到 `--interval`。
            if round_failed:
                consecutive_failures += 1
                current_delay = next_backoff(current_delay, args.interval)
                log.info("连续第 %d 轮失败：本轮结束后退避 %.1fs 再试", consecutive_failures, current_delay)
            else:
                if consecutive_failures:
                    log.info("后端已恢复（此前连续失败 %d 轮）", consecutive_failures)
                consecutive_failures = 0
                current_delay = max(0.5, args.interval)
            # 审计 CW-20：每轮刷新共享锁心跳，让别的实例知道本实例还活着（否则会被判过期接管）
            instance_lock.heartbeat()
            time.sleep(current_delay)
    except BaseException:
        # 审计 CW-20：异常/中断退出时释放共享锁（否则别的机器要等心跳过期才能接管）
        instance_lock.release()
        raise


def rows_max(rows: list) -> str:
    return max((t for _, t in rows), default="")


if __name__ == "__main__":
    sys.exit(main())
