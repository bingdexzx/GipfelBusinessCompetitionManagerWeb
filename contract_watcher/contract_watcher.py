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
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("contract_watcher")

WATCHER_DIR = Path(__file__).resolve().parent
HANDLERS_FILE = WATCHER_DIR / "handlers.py"
STATE_FILE = WATCHER_DIR / "data" / "state.json"
LOG_FILE = WATCHER_DIR / "watcher.log"
RECORDS_DIR = WATCHER_DIR / "records"

MARKER_PREFIX = "# ===== [auto] ContractType.key = "
MARKER_SUFFIX = " ====="
MARKER_RE = re.compile(r"^# ===== \[auto\] ContractType\.key = (.*?) =====$", re.MULTILINE)
_SLUG_RE = re.compile(r"\W+")


# ==================== 小工具 ====================

def slug_of(key: str) -> str:
    return _SLUG_RE.sub("_", str(key)).strip("_").lower() or "key"


def func_name_of(key: str) -> str:
    return f"handle_{slug_of(key)}_passed"


def safe_dirname(key: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(key))


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

    def fetch_executed_ids(self, competition_id: int | None) -> list[tuple[int, str]]:
        """EXECUTED 合同 id 与 executedAt 列表（executedAt 用于增量判断）。"""
        out: list[tuple[int, str]] = []
        page = 1
        while True:
            params = f"status=EXECUTED&page={page}&pageSize=200"
            if competition_id:
                params += f"&competitionId={competition_id}"
            data = self.api(f"/api/contracts?{params}")
            batch = data.get("items") or []
            total = data.get("total") or len(batch)
            for it in batch:
                if it.get("executedAt"):
                    out.append((int(it["id"]), str(it["executedAt"])))
            if not batch or len(batch) >= total:
                return out
            page += 1

    def fetch_contract_detail(self, contract_id: int) -> dict:
        return self.api(f"/api/contracts/{contract_id}")


# ==================== handlers.py 的生成 / 改名 / 加载 ====================

def build_default_section(key: str) -> str:
    func = func_name_of(key)
    return (
        "\n\n" + MARKER_PREFIX + key + MARKER_SUFFIX + "\n"
        f"def {func}(contract: dict, ctx: dict) -> None:\n"
        f'    """{key} 类型合同通过后的处理（自动生成的默认函数）。\n'
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


def upsert_handler_for_key(key: str) -> bool:
    """handlers.py 中为该 key 生成默认函数（已存在则跳过）。返回是否新增。"""
    text = HANDLERS_FILE.read_text(encoding="utf-8")
    if MARKER_PREFIX + key + MARKER_SUFFIX in text:
        return False
    text = text.rstrip() + build_default_section(key) + "\n"
    HANDLERS_FILE.write_text(text, encoding="utf-8")
    return True


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
        if line.strip() == MARKER_PREFIX + old_key + MARKER_SUFFIX:
            lines[i] = MARKER_PREFIX + new_key + MARKER_SUFFIX
            changed = True
        elif line.lstrip().startswith("def ") and old_func in line:
            lines[i] = line.replace(old_func, new_func)
            changed = True
    if changed:
        HANDLERS_FILE.write_text("\n".join(lines), encoding="utf-8")
    return changed


def load_handlers() -> dict[str, object]:
    """加载 handlers.py 并返回 {key: 处理函数}（按标注行 key → 函数名解析）。"""
    ensure_handlers_file()
    text = HANDLERS_FILE.read_text(encoding="utf-8")
    keys = [m.group(1) for m in MARKER_RE.finditer(text)]
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
    for key in keys:
        fn = getattr(mod, func_name_of(key), None)
        if callable(fn):
            if key in registry:
                log.warning("key=%s 的函数名冲突（%s），后者未生效", key, func_name_of(key))
                continue
            registry[key] = fn
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


def dispatch(contract: dict, registry: dict, out_dir: Path, competition_id: int | None) -> None:
    key = (contract.get("contractType") or {}).get("key") or "unknown"
    ctx = {
        "out_dir": out_dir,
        "typeKey": key,
        "competitionId": contract.get("competitionId", competition_id),
        "default_archive": default_archive,
    }
    fn = registry.get(key)
    try:
        if fn is None:
            log.info("未注册处理函数 type=%s → 默认存档 contract=#%s", key, contract["id"])
            f = default_archive(contract, ctx)
            log.info("已默认存档 contract=#%s → %s", contract["id"], f)
        else:
            fn(contract, ctx)
            log.info("已按类型处理 contract=#%s type=%s handler=%s", contract["id"], key,
                     getattr(fn, "__name__", fn))
    except Exception:  # noqa: BLE001 - 单个合同处理失败不影响后续与网页端
        log.exception("处理合同 #%s(type=%s) 失败（已隔离）", contract["id"], key)


# ==================== 主循环 ====================

def sync_catalog(backend: Backend, state: dict, registry_ref: list) -> bool:
    """类型目录同步：新 key 生成默认函数；改名的 key 自动改名；返回目录是否有变化。"""
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
    ap.add_argument("--out-dir", default=str(RECORDS_DIR))
    ap.add_argument("--port", type=int, default=47653, help="单实例互斥端口")
    ap.add_argument("--backfill", action="store_true", help="首次运行也处理存量已执行合同")
    ap.add_argument("--verbose", action="store_true", help="控制台同步输出明细")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        filename=str(LOG_FILE), filemode="a", encoding="utf-8",
    )
    if args.verbose:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        log.addHandler(console)

    # 单实例互斥（socket 占端口；退出自动释放）
    try:
        lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_sock.bind(("127.0.0.1", args.port))
        lock_sock.listen(1)
    except OSError:
        print(f"另一个监听实例已在运行（端口 {args.port} 被占用），本实例退出。"
              f"如需更换端口请用 --port。", file=sys.stderr)
        return 1

    WATCHER_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
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
    sync_catalog(backend, state, registry)

    if "baselineAt" not in state:
        state["baselineAt"] = now_iso()
        state["lastExecutedAt"] = ""
        if not args.backfill:
            try:
                rows = backend.fetch_executed_ids(args.competition)
                state["lastExecutedAt"] = max((t for _, t in rows), default="")
            except Exception:  # noqa: BLE001
                state["lastExecutedAt"] = ""
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    log.info("监听启动 server=%s competition=%s out=%s backfill=%s",
             args.server, args.competition, out_dir, args.backfill)

    while True:
        try:
            # 1) handlers.py 被手动修改 → 热加载
            try:
                mtime = HANDLERS_FILE.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    registry[0] = load_handlers()
                    log.info("handlers.py 已变更，热加载完成")
            except OSError:
                pass
            # 2) 类型目录同步（新 key 生成 / key 改名自动改名）
            sync_catalog(backend, state, registry)
            # 3) 检测合同通过
            rows = backend.fetch_executed_ids(args.competition)
            last_seen = state.get("lastExecutedAt") or ""
            fresh = sorted([(cid, t) for cid, t in rows if t > last_seen], key=lambda x: x[1])
            for cid, et in fresh:
                contract = backend.fetch_contract_detail(cid)
                if contract.get("status") != "EXECUTED":
                    continue
                dispatch(contract, registry[0], out_dir, args.competition)
                last_seen = max(last_seen, et)
            # 4) 持久化进度
            new_max = max((t for _, t in rows), default="")
            if new_max and new_max > (state.get("lastExecutedAt") or ""):
                state["lastExecutedAt"] = new_max
                STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log.warning("登录态失效，下一轮自动重登")
            else:
                log.warning("后端请求失败 HTTP %s", e.code)
        except Exception:  # noqa: BLE001 - 静默容错：任何异常都不影响下一轮与网页端
            log.exception("本轮执行异常（已隔离，继续下一轮）")
        time.sleep(max(0.5, args.interval))


def rows_max(rows: list) -> str:
    return max((t for _, t in rows), default="")


if __name__ == "__main__":
    sys.exit(main())
