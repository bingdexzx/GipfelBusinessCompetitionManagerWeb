"""实时广播辅助：对应原 NestJS RealtimeService.emitResourceChanged。

【关键集成点】python-socketio AsyncServer(async_mode="asgi") 的 emit 必须在 ASGI
事件循环内执行（await sio.emit）；Django HTTP 视图/信号运行在同步线程中，直接
调用 sio.emit 会因「当前线程无正在运行的 event loop」而静默失败或抛异常。

修复方案（基于 experience 563698）：
1. gateway 保存其 ASGI server 的 running loop（在 connect 事件中记录）
2. 同步侧通过 `asyncio.run_coroutine_threadsafe(coro, loop)` 把协程投递到那个 loop
3. 结果用 Future 等待，但有 1s 超时；超时不阻断 HTTP 主流程
4. loop 未就绪时（如脚本/migrate/测试）降级为静默跳过

契约对齐前端 realtime/resource-changed.ts 的 ResourceChangedEvent：
    { resource, ids[], action ("created"|"updated"|"deleted"|"bulk"),
      competitionId, seq, ts }
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from itertools import islice

logger = logging.getLogger("gipfel")

EVENT_RESOURCE_CHANGED = "resource:changed"
EVENT_PERMISSIONS_CHANGED = "permissions:changed"

# 序列计数器
_seq_lock = threading.Lock()
_seq_value: int = 0

# 重放环形缓冲
_RING_MAX_LEN = 5000
_ring_lock = threading.Lock()
_event_ring: deque = deque(maxlen=_RING_MAX_LEN)
# 与 _event_ring 同步的 seq 序列（单调增），用于 replay_since 二分定位（避免 O(N) 线性扫描）
_ring_seqs: deque = deque(maxlen=_RING_MAX_LEN)

# ASGI 事件循环引用（由 gateway.connect 首次触发时赋值；仅写一次）
_loop_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    """由 gateway 在 connect 事件中调用，注册 ASGI 事件循环供同步侧投递 emit。"""
    global _loop
    with _loop_lock:
        # 覆盖重注册：ASGI worker 重启 / reload 后旧 loop 可能已关闭，
        # 必须刷新，否则 _run_coro_on_loop 会因 loop.is_running() 为 False 静默丢弃所有实时广播（#P3）
        if _loop is None or _loop.is_closed():
            _loop = loop


def _get_loop_safe() -> asyncio.AbstractEventLoop | None:
    """线程安全获取已注册的 ASGI loop。"""
    with _loop_lock:
        return _loop


# --------------------------------------------------------------------


def _next_seq() -> int:
    global _seq_value
    with _seq_lock:
        _seq_value += 1
        return _seq_value


def _current_seq() -> int:
    with _seq_lock:
        return _seq_value


def _push_ring(event, data: dict, room: str | None) -> None:
    entry = {
        "event": event,
        "data": data,
        "room": room,
        "seq": data.get("seq"),
        "ts_ms": data.get("ts"),
    }
    with _ring_lock:
        _event_ring.append(entry)
        _ring_seqs.append(data.get("seq"))


def _bisect_right_seqs(target: int) -> int:
    """在单调递增的 _ring_seqs 上二分，返回首个 seq > target 的下标。"""
    lo, hi = 0, len(_ring_seqs)
    while lo < hi:
        mid = (lo + hi) // 2
        if _ring_seqs[mid] <= target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def replay_since(last_seq: int) -> list[dict]:
    with _ring_lock:
        # 二分定位首个 > last_seq 的条目，仅返回其后（通常远小于环长），避免 O(N) 线性扫描
        idx = _bisect_right_seqs(last_seq)
        return list(islice(_event_ring, idx, None))


def server_seq() -> int:
    return _current_seq()


# ====================================================================
# MODEL → resource 映射（MODEL_TO_RESOURCE、GLOBAL_RESOURCES、辅助函数）
# ====================================================================
MODEL_TO_RESOURCE: dict[str, str] = {
    # P0
    "Competition": "competitions",
    "FiscalYear": "fiscalYears",
    "User": "users",
    "AuditLog": None,
    # P1 生产链与地图
    "Material": "materials",
    "Part": "parts",
    "PartMaterial": None,
    "PartTechRequirement": None,
    "Product": "products",
    "ProductPart": None,
    "ProductTechRequirement": None,
    "TechNode": "techNodes",
    "TechPrerequisite": None,
    "MapNodeType": "mapNodeTypes",
    "PathType": "pathTypes",
    "MapNode": "mapNodes",
    "MapEdge": "mapEdges",
    "Infrastructure": "infrastructures",
    "Fuel": "fuels",
    "Vehicle": "vehicles",
    "VehiclePathType": None,
    "Warehouse": "warehouses",
    "ProductionLine": "productionLines",
    # P2
    "IndustryType": "industryTypes",
    "IndustryField": None,
    "Company": "companies",
    "CompanyFieldValue": None,
    "ContractType": "contractTypes",
    "Contract": "contracts",
    "ContractFieldEffect": None,
    "Region": "regions",
    "ConsumerDemand": "consumerDemands",
    # P3
    "Message": "messages",
    "MessageRecipient": None,
    "Stock": "stocks",
    "StockFundsAccount": "stock-accounts",
    "StockHolding": "stock-holdings",
    "StockOrder": "stock-orders",
    "StockCandle": "stock-candles",
}

GLOBAL_RESOURCES = {"industryTypes"}


def resolve_model_info(model_class) -> tuple[str | None, bool]:
    name = getattr(model_class, "__name__", "")
    resource = MODEL_TO_RESOURCE.get(name)
    if not resource:
        return None, False
    return resource, resource in GLOBAL_RESOURCES


def extract_competition_id(instance) -> int | None:
    for attr in ("competition_id", "competitionId"):
        v = getattr(instance, attr, None)
        if isinstance(v, int):
            return v
    comp_ref = getattr(instance, "competition", None)
    if comp_ref is not None:
        cid = getattr(comp_ref, "id", None)
        if isinstance(cid, int):
            return cid
    return None


# ====================================================================
# 底层：投递到 ASGI 事件循环的线程安全 emit
# ====================================================================
def _run_coro_on_loop(coro) -> bool:
    """安全地把协程投递到已注册的 ASGI loop，返回是否「已尝试投递」。

    - loop 未注册 → 返回 False，调用方应静默降级
    - 投递成功 → 返回 True；注意结果不等待、不阻塞调用线程超过 10ms
    - 任何异常 → logger.debug 记录、不抛
    """
    loop = _get_loop_safe()
    if loop is None or not loop.is_running():
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        # 给调度器最多 10ms 把任务挂上；不等待 emit 完成（WebSocket 发报是 IO）
        future.result(timeout=0.01)
    except asyncio.TimeoutError:
        # 调度成功但未立即完成 → 正常（后台会继续）
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("ASGI 投递协程失败: %s", exc, exc_info=True)
    return True


def _emit_sio(event: str, payload: dict, room: str | None = None) -> None:
    """把事件投递到 sio；loop 未就绪或失败静默。"""
    try:
        from .gateway import sio
    except Exception:  # noqa: BLE001
        return

    async def _do_emit():
        try:
            if room:
                await sio.emit(event, payload, room=room)
            else:
                await sio.emit(event, payload)
        except Exception:  # noqa: BLE001
            logger.debug("emit_sio await 失败 event=%s", event, exc_info=True)

    # 如果当前就在 ASGI 循环内（Socket.IO 处理器本身），直接 await
    try:
        cur_loop = asyncio.get_running_loop()
        loop_ref = _get_loop_safe()
        if cur_loop is not None and (loop_ref is cur_loop):
            cur_loop.create_task(_do_emit())
            return
    except RuntimeError:
        pass  # 无运行中 loop → 走 run_coroutine_threadsafe

    _run_coro_on_loop(_do_emit())


# ====================================================================
# 广播 API
# ====================================================================
def emit_resource_changed(
    resource: str,
    record_id: int | None,
    competition_id: int | None,
    action: str,
    *,
    ids: list[int] | None = None,
) -> None:
    seq = _next_seq()
    ts_ms = int(time.time() * 1000)
    if ids is None:
        ids = [record_id] if isinstance(record_id, int) else []

    payload = {
        "resource": resource,
        "id": record_id if isinstance(record_id, int) else (ids[0] if ids else None),
        "ids": ids,
        "action": action,
        "competitionId": competition_id,
        "seq": seq,
        "ts": ts_ms,
    }

    is_global = resource in GLOBAL_RESOURCES
    room: str | None = None
    if not is_global and competition_id is not None:
        room = f"comp-{competition_id}"

    _push_ring(EVENT_RESOURCE_CHANGED, payload, room)
    _emit_sio(EVENT_RESOURCE_CHANGED, payload, room=room)


def emit_resource_changed_to_users(
    resource: str,
    record_id: int,
    user_ids,
    action: str,
    competition_id: int | None = None,
    ids: list[int] | None = None,
) -> None:
    """向指定用户房间广播资源变更（不进入环形重放：每用户独立房间）。"""
    seq = _next_seq()
    ts_ms = int(time.time() * 1000)
    if ids is None:
        ids = [record_id] if isinstance(record_id, int) else []
    payload = {
        "resource": resource,
        "id": record_id if isinstance(record_id, int) else (ids[0] if ids else None),
        "ids": ids,
        "action": action,
        "competitionId": competition_id,
        "seq": seq,
        "ts": ts_ms,
    }
    for uid in user_ids or []:
        _emit_sio(EVENT_RESOURCE_CHANGED, payload, room=f"user-{uid}")


def emit_to_users(user_ids, event: str, data) -> None:
    for uid in user_ids or []:
        _emit_sio(event, data, room=f"user-{uid}")


def emit_to_competition(competition_id: int | None, event: str, data) -> None:
    """向某比赛房间（comp-<id>）广播自定义事件。

    对应 NestJS RealtimeService.broadcastToCompetition，用于 resource:changed 之外
    的业务事件（如 fiscal-year:changed / competition:changed）。competition_id 为空
    时静默跳过，避免误广播到全局。
    """
    if competition_id is None:
        return
    _emit_sio(event, data, room=f"comp-{competition_id}")


# ====================================================================
# permissions:changed
# ====================================================================
def emit_permissions_changed(user_id: int, permission_version: int) -> None:
    seq = _next_seq()
    ts_ms = int(time.time() * 1000)
    payload = {
        "userId": user_id,
        "version": permission_version,
        "seq": seq,
        "ts": ts_ms,
    }
    room = f"user-{user_id}"
    _push_ring(EVENT_PERMISSIONS_CHANGED, payload, room)
    _emit_sio(EVENT_PERMISSIONS_CHANGED, payload, room=room)


