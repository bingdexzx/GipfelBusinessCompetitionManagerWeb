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
        """EXECUTED 合同 id 与 executedAt 列表（executedAt 用于增量判断）。

        审计 CW-04：改前按 offset 分页（page=N）逐页拼接，期间有合同执行/撤销会让分页漂移，
        同一条合同可能重复出现在两页里 → 同轮重复分发（重复记账）。这里按合同 id 去重，
        同 id 保留更新的 executedAt。
        """
        by_id: dict[int, str] = {}
        page = 1
        while True:
            params = f"status=EXECUTED&page={page}&pageSize=200"
            if competition_id:
                params += f"&competitionId={competition_id}"
            data = self.api(f"/api/contracts?{params}")
            batch = data.get("items") or []
            total = data.get("total") or len(batch)
            for it in batch:
                if not it.get("executedAt"):
                    continue
                cid = int(it["id"])
                et = str(it["executedAt"])
                prev = by_id.get(cid)
                by_id[cid] = et if prev is None else max_executed_at([prev, et])
            if not batch or len(batch) >= total:
                return list(by_id.items())
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
    if MARKER_PREFIX + key + MARKER_SUFFIX in text:
        return False
    func = func_name_of(key)
    if func_def_pattern(func).search(text):
        log.warning(
            "key=%s 已有同名函数 %s（用户自定义或与其它 key 的 slug 冲突），"
            "不再追加自动生成的默认块（避免同名 def 后者生效屏蔽用户实现）", key, func,
        )
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
    """持久化进度。"""
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


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
    rows = backend.fetch_executed_ids(competition_id)
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
    if advanced_to != watermark:
        state["lastExecutedAt"] = advanced_to
        save_state(state)
    elif still_pending:
        # 水位没动也要落盘：待处理队列必须在重启后继续重试
        save_state(state)
    if still_pending:
        log.error(
            "仍有 %d 个合同未处理成功（%s），已保留在待处理队列，下一轮重试；"
            "请检查 handlers.py 与输出目录权限",
            len(still_pending), [p["id"] for p in still_pending],
        )


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

    # 首次运行基线：未建立成功前不处理任何合同（审计 CW-01）
    baseline_ready = establish_baseline(backend, state, args.competition, args.backfill)
    log.info("监听启动 server=%s competition=%s out=%s backfill=%s",
             args.server, args.competition, out_dir, args.backfill)

    while True:
        try:
            # 0) 基线未建立（首次拉取失败）→ 每轮重试，期间不处理合同
            if not baseline_ready:
                baseline_ready = establish_baseline(
                    backend, state, args.competition, args.backfill
                )
                if not baseline_ready:
                    time.sleep(max(0.5, args.interval))
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
            # 2) 类型目录同步（新 key 生成 / key 改名自动改名）
            sync_catalog(backend, state, registry)
            # 3) 检测合同通过并处理；水位只在成功处理后推进（失败进待处理队列重试）
            process_fresh_contracts(backend, state, registry[0], out_dir, args.competition)
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
