"""实时网关：对应原 NestJS 的 Socket.IO 网关。

- python-socketio AsyncServer，async_mode="asgi"，与 Django HTTP 同源同端口
  （由 backend/asgi.py 按 path 前缀分发 /socket.io/* 到本应用）
- CORS 交由 apps.common 中间件统一管控，此处 cors_allowed_origins="*"
- connect 事件校验 JWT（auth.token），并校验 tokenVersion（顶号下线）
- subscribe/unsubscribe：
    · 显式 { room }
    · 兼容前端 { competitionId } / { userId }（映射到 comp-{id} / user-{id}）
- sync:replay：补发 lastSeq 之后的事件（环形缓冲），并返回 serverSeq
- 顶号机制：JWT 校验失败时立刻向 user-{id} 广播 auth:required（踢现有连接下线）

导出 sio（AsyncServer 实例）与 application（ASGI 应用），供 asgi.py 引用。
"""
from __future__ import annotations

import logging

import socketio
from asgiref.sync import sync_to_async

logger = logging.getLogger("gipfel")

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=20,
)


# ==================== JWT 校验（连接握手） ====================
@sync_to_async
def _resolve_user(payload: dict):
    """根据 JWT payload 查询用户并校验 token_version。返回 user 或 None。"""
    from apps.users.models import User

    sub = payload.get("sub") if payload else None
    if not sub:
        return None
    try:
        user = User.objects.get(pk=sub)
    except User.DoesNotExist:
        return None
    except Exception:  # noqa: BLE001
        return None
    if payload.get("tv") != user.token_version:
        return None
    return user


@sio.event
async def connect(sid, environ, auth):
    """连接握手：校验 JWT，通过则建立会话并入本人房间；顶号时踢旧连接。"""
    # 在首次 connect 时把 ASGI running loop 注册到 emit 模块，
    # 让同步 Django HTTP 视图/信号能通过 run_coroutine_threadsafe 投递 emit
    try:
        import asyncio

        from .emit import register_loop

        register_loop(asyncio.get_running_loop())
    except Exception:  # noqa: BLE001
        pass

    token = None
    if isinstance(auth, dict):
        token = auth.get("token")
    # 兼容通过 query 传递 token
    if not token:
        qs = environ.get("QUERY_STRING", "") if environ else ""
        for pair in qs.split("&"):
            if pair.startswith("token="):
                token = pair[len("token="):]
                break

    if not token:
        logger.debug("socket.io 连接拒绝：缺少 token (sid=%s)", sid)
        return False

    from apps.auth.authentication import decode_jwt_payload

    payload = decode_jwt_payload(token)
    if payload is None:
        logger.debug("socket.io 连接拒绝：JWT 无效 (sid=%s)", sid)
        return False

    user = await _resolve_user(payload)
    if user is None:
        # 顶号：老 token 被新版本号顶掉，把该用户的所有旧连接踢掉
        sub = payload.get("sub") if payload else None
        if isinstance(sub, int):
            try:
                await sio.emit(
                    "auth:required",
                    {"reason": "token_version_mismatch"},
                    room=f"user-{sub}",
                )
            except Exception:  # noqa: BLE001
                pass
        logger.debug("socket.io 连接拒绝：用户不存在或已顶号 (sid=%s)", sid)
        return False

    await sio.save_session(
        sid,
        {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "competition_id": getattr(user, "competition_id", None),
        },
    )

    await sio.enter_room(sid, f"user-{user.id}")
    cid = getattr(user, "competition_id", None)
    if cid:
        await sio.enter_room(sid, f"comp-{cid}")

    logger.info("socket.io 已连接：sid=%s user=%s", sid, user.username)
    return True


@sio.event
async def disconnect(sid):
    logger.info("socket.io 已断开：sid=%s", sid)


# ==================== 房间订阅 ====================
def _parse_room_key(data) -> str | None:
    """从订阅 payload 中解析目标房间名（兼容 room/competitionId/userId 三种键）。"""
    if isinstance(data, dict):
        room = data.get("room")
        if isinstance(room, str) and room:
            return room
        cid = data.get("competitionId")
        if isinstance(cid, int):
            return f"comp-{cid}"
        if isinstance(cid, str) and cid.isdigit():
            return f"comp-{int(cid)}"
        uid = data.get("userId")
        if isinstance(uid, int):
            return f"user-{uid}"
        if isinstance(uid, str) and uid.isdigit():
            return f"user-{int(uid)}"
        return None
    if isinstance(data, str):
        return data if data else None
    return None


def _can_join(room: str, session: dict) -> bool:
    if room.startswith("user-"):
        try:
            uid = int(room[len("user-"):])
        except ValueError:
            return False
        return uid == session.get("user_id")
    if room.startswith("comp-"):
        try:
            cid = int(room[len("comp-"):])
        except ValueError:
            return False
        if session.get("role") == "SUPER_ADMIN":
            return True
        return cid == session.get("competition_id")
    return False


@sio.on("subscribe")
async def on_subscribe(sid, data):
    session = await sio.get_session(sid)
    room = _parse_room_key(data)
    if not room:
        return {"ok": False, "message": "缺少 room / competitionId / userId 参数"}
    if not _can_join(room, session):
        return {"ok": False, "message": "无权订阅该房间"}
    await sio.enter_room(sid, room)
    logger.debug("socket.io 订阅：sid=%s room=%s", sid, room)
    return {"ok": True, "room": room}


@sio.on("unsubscribe")
async def on_unsubscribe(sid, data):
    room = _parse_room_key(data)
    if not room:
        return {"ok": False, "message": "缺少 room / competitionId / userId 参数"}
    await sio.leave_room(sid, room)
    logger.debug("socket.io 取消订阅：sid=%s room=%s", sid, room)
    return {"ok": True, "room": room}


# ==================== 同步重放（补发 lastSeq 之后的事件） ====================
@sio.on("sync:replay")
async def on_sync_replay(sid, data):
    """按客户端 lastSeq 补发环形缓冲中 seq > lastSeq 的事件，并回传 serverSeq。

    事件过滤：
    - room=None（全局）→ 全量补发
    - room=comp-{id} → 仅当当前会话属于该比赛或为 SUPER_ADMIN 时补发
    - room=user-{id} → 仅当当前会话为该用户时补发
    """
    session = await sio.get_session(sid) or {}
    last_seq = 0
    if isinstance(data, dict):
        try:
            last_seq = int(data.get("lastSeq") or 0)
        except (TypeError, ValueError):
            last_seq = 0

    from .emit import replay_since, server_seq

    raw_events = replay_since(last_seq) if last_seq > 0 else []

    user_id = session.get("user_id")
    role = session.get("role")
    competition_id = session.get("competition_id")
    filtered = []
    for e in raw_events:
        room = e.get("room")
        if room is None:
            filtered.append({"event": e["event"], "data": e["data"]})
        elif room.startswith("user-"):
            try:
                r_uid = int(room[len("user-"):])
            except ValueError:
                continue
            if r_uid == user_id:
                filtered.append({"event": e["event"], "data": e["data"]})
        elif room.startswith("comp-"):
            try:
                r_cid = int(room[len("comp-"):])
            except ValueError:
                continue
            if role == "SUPER_ADMIN" or r_cid == competition_id:
                filtered.append({"event": e["event"], "data": e["data"]})
        # 其他房间类型暂不重放

    return {
        "ok": True,
        "events": filtered,
        "serverSeq": server_seq(),
    }


# ==================== ASGI 应用 ====================
application = socketio.ASGIApp(sio)
