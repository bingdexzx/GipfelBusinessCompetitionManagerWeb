"""流量限制 API 视图。

仅超级管理员可访问。
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.rate_limit import (
    clear_rate_limit_store,
    get_rate_limit_config,
    reset_rate_limit_config,
    update_rate_limit_config,
)


class RateLimitConfigView(APIView):
    """GET/PUT /api/system/rate-limit — 流量限制配置。"""
    
    permission_classes = (IsAuthenticated,)
    
    def get(self, request):
        """获取流量限制配置。"""
        if request.user.role != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可访问", code=403, status_code=403)
        
        config = get_rate_limit_config()
        
        # 计算当前使用情况
        from apps.common.rate_limit import _rate_limit_store, _cleanup_old_records
        usage = {}
        for role, role_config in config.items():
            if role_config.get("enabled", False):
                window = role_config.get("window", 60)
                # 统计该角色所有用户的当前请求数
                total_requests = 0
                for user_id, records in _rate_limit_store.items():
                    _cleanup_old_records(user_id, window)
                    total_requests += len(records)
                usage[role] = {
                    "currentRequests": total_requests,
                    "maxRequests": role_config.get("requests", 0),
                }
        
        return Response({
            "config": config,
            "usage": usage,
        })
    
    def put(self, request):
        """更新流量限制配置。"""
        if request.user.role != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可访问", code=403, status_code=403)
        
        data = request.data
        if not isinstance(data, dict):
            raise BusinessError("请求数据格式错误", code=400, status_code=400)
        
        role = data.get("role")
        if not role or role not in ("SUPER_ADMIN", "COMPETITION_ADMIN", "PLAYER"):
            raise BusinessError("无效的角色", code=400, status_code=400)
        
        config = data.get("config", {})
        
        # 验证配置
        if "enabled" in config and not isinstance(config["enabled"], bool):
            raise BusinessError("enabled 必须为布尔值", code=400, status_code=400)
        if "requests" in config:
            if not isinstance(config["requests"], (int, float)) or config["requests"] < 1:
                raise BusinessError("requests 必须为正整数", code=400, status_code=400)
            config["requests"] = int(config["requests"])
        if "window" in config:
            if not isinstance(config["window"], (int, float)) or config["window"] < 1:
                raise BusinessError("window 必须为正整数", code=400, status_code=400)
            config["window"] = int(config["window"])
        
        update_rate_limit_config(role, config)
        
        return Response({
            "message": "配置已更新",
            "config": get_rate_limit_config(),
        })


class RateLimitResetView(APIView):
    """POST /api/system/rate-limit/reset — 重置流量限制。"""
    
    permission_classes = (IsAuthenticated,)
    
    def post(self, request):
        """重置流量限制配置和记录。"""
        if request.user.role != "SUPER_ADMIN":
            raise BusinessError("仅超级管理员可访问", code=403, status_code=403)
        
        action = request.data.get("action", "config")
        
        if action == "config":
            reset_rate_limit_config()
            return Response({"message": "配置已重置为默认值"})
        elif action == "records":
            clear_rate_limit_store()
            return Response({"message": "流量限制记录已清空"})
        elif action == "all":
            reset_rate_limit_config()
            clear_rate_limit_store()
            return Response({"message": "配置和记录已重置"})
        else:
            raise BusinessError("无效的 action", code=400, status_code=400)