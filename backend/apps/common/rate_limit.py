"""流量限制中间件。

按角色（SUPER_ADMIN / COMPETITION_ADMIN / PLAYER）限制 API 请求频率。
配置存储在内存中（重启丢失），超管可通过 API 动态调整。
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from django.conf import settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("gipfel")

# ==================== 默认配置 ====================
DEFAULT_RATE_LIMITS = {
    "SUPER_ADMIN": {
        "enabled": False,  # 超管默认不限制
        "requests": 1000,  # 请求数
        "window": 60,      # 时间窗口（秒）
    },
    "COMPETITION_ADMIN": {
        "enabled": True,
        "requests": 300,
        "window": 60,
    },
    "PLAYER": {
        "enabled": True,
        "requests": 100,
        "window": 60,
    },
}

# ==================== 全局状态 ====================
# 格式: {user_id: {role: [(timestamp, request_count), ...]}}
_rate_limit_store: dict[int, list[tuple[float, int]]] = defaultdict(list)
_config: dict[str, dict] = DEFAULT_RATE_LIMITS.copy()
_lock = Lock()

# 不限制的路径（静态文件、WebSocket、健康检查等）
_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/refresh",
    "/health",
    "/healthz",
}


def get_rate_limit_config() -> dict:
    """获取当前流量限制配置。"""
    return _config.copy()


def update_rate_limit_config(role: str, config: dict) -> None:
    """更新指定角色的流量限制配置。"""
    global _config
    if role not in _config:
        _config[role] = {}
    _config[role].update(config)
    logger.info(f"[rate_limit] 配置更新: {role} = {_config[role]}")


def reset_rate_limit_config() -> None:
    """重置为默认配置。"""
    global _config
    _config = DEFAULT_RATE_LIMITS.copy()
    logger.info("[rate_limit] 配置已重置为默认值")


def clear_rate_limit_store() -> None:
    """清空所有流量限制记录。"""
    global _rate_limit_store
    with _lock:
        _rate_limit_store.clear()
    logger.info("[rate_limit] 流量限制记录已清空")


def _cleanup_old_records(user_id: int, window: int) -> None:
    """清理过期的请求记录。"""
    cutoff = time.time() - window
    if user_id in _rate_limit_store:
        _rate_limit_store[user_id] = [
            (ts, count) for ts, count in _rate_limit_store[user_id]
            if ts > cutoff
        ]


def _get_request_count(user_id: int, window: int) -> int:
    """获取指定时间窗口内的请求数。"""
    _cleanup_old_records(user_id, window)
    return sum(count for _, count in _rate_limit_store[user_id])


def _record_request(user_id: int) -> None:
    """记录一次请求。"""
    with _lock:
        _rate_limit_store[user_id].append((time.time(), 1))


class RateLimitMiddleware(MiddlewareMixin):
    """流量限制中间件。"""
    
    def process_request(self, request):
        # 跳过非 API 请求
        if not request.path.startswith("/api/"):
            return None
        
        # 跳过豁免路径
        if request.path in _EXEMPT_PATHS:
            return None
        
        # 跳过未认证请求（由认证中间件处理）
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return None
        
        user = request.user
        role = getattr(user, "role", None)
        
        # 获取角色配置
        role_config = _config.get(role, {})
        if not role_config.get("enabled", False):
            return None
        
        user_id = user.id
        max_requests = role_config.get("requests", 100)
        window = role_config.get("window", 60)
        
        # 检查是否超限
        current_count = _get_request_count(user_id, window)
        if current_count >= max_requests:
            # 计算重试时间
            if _rate_limit_store[user_id]:
                oldest_ts = _rate_limit_store[user_id][0][0]
                retry_after = int(oldest_ts + window - time.time()) + 1
            else:
                retry_after = window
            
            logger.warning(
                f"[rate_limit] 用户 {user.username} (ID:{user_id}, 角色:{role}) "
                f"触发流量限制: {current_count}/{max_requests} (窗口:{window}s)"
            )
            
            return JsonResponse(
                {
                    "code": 429,
                    "message": "请求过于频繁，请稍后重试",
                    "retryAfter": retry_after,
                },
                status=429,
            )
        
        # 记录请求
        _record_request(user_id)
        
        return None