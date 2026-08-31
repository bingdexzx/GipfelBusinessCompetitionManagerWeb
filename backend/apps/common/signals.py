"""Django 写操作信号分发器：post_save/post_delete → 审计落库 + 实时广播。

在 apps.common.apps.ready() 中对全部「已注册且在 MODEL_TO_RESOURCE 中有映射」
的模型统一 connect 信号；无需每个 app 各自接入。

注意点：
- 信号处理器跑在 HTTP 线程（同步上下文），所以 ORM / 审计 / emit 全用同步 API
- python-socketio 的 AsyncServer.emit 被同步调用时，内部会把动作投递到 ASGI 事件循环，
  不依赖当前线程的 loop，因此可直接在同步视图事务提交后的信号回调中调用
- 为避免 M2M/嵌套事务导致「未提交数据就广播」，处理器仅在 `instance.pk` 已存在
  且（对 post_save 而言）created 语义明确时才广播
- 审计 changes 的构造：created 动作仅保存前值为空；updated 动作由于 Django 不给 diff，
  广播以 instance 为权威，审计仅记录「有更新」（与原 NestJS Prisma $allOperations 粒度一致）
"""
from __future__ import annotations

import logging
import threading

from django.db.models.signals import post_delete, post_save

logger = logging.getLogger("gipfel")


# ==================== 信号总开关（供批量操作临时屏蔽，股票推进轮次等场景） ====================
_signals_enabled_local = threading.local()


def _set_enabled(enabled: bool) -> None:
    _signals_enabled_local.value = enabled


def _is_enabled() -> bool:
    return bool(getattr(_signals_enabled_local, "value", True))


class suppress_signals:
    """上下文管理器：临时关闭所有写操作信号（审计 + 广播）。

    用法：
        with suppress_signals():
            for obj in many: obj.save()  # 不触发 per-row 信号
        emit_resource_changed(..., "bulk")  # 随后统一 bulk 广播

    典型场景：stock advance_round 对 StockOrder/Holding/Candle 大量 save，
    若不抑制会每 save 都发出 resource:changed（单条），前端会收到上百条事件。
    """

    prev: bool

    def __enter__(self) -> "suppress_signals":
        self.prev = _is_enabled()
        _set_enabled(False)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _set_enabled(self.prev)


# ==================== 动作名映射（action ∈ created / updated / deleted） ====================
def _action_for_post_save(created: bool) -> str:
    return "created" if created else "updated"


# ==================== changes 摘要（给审计使用） ====================
def _summarize_instance(instance) -> dict:
    """把模型实例的字段转为扁平 dict（仅用于审计落库，不作为广播内容）。"""
    data: dict = {}
    try:
        from django.db import models

        for f in instance._meta.concrete_fields:
            if isinstance(f, (models.ForeignKey, models.OneToOneField)):
                data[f.attname] = getattr(instance, f.attname, None)
            elif isinstance(f, (models.DateTimeField, models.DateField)):
                v = getattr(instance, f.name, None)
                data[f.name] = v.isoformat() if v else None
            else:
                try:
                    data[f.name] = getattr(instance, f.name)
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        pass
    return data


# ==================== 主处理器 ====================
def _on_post_save(sender, instance, created, raw, **kwargs):
    if raw:  # loaddata / fixture 场景跳过
        return
    if not _is_enabled():  # 批量操作临时屏蔽（股票推进轮次等）
        return

    from apps.realtime.emit import (
        extract_competition_id,
        resolve_model_info,
    )
    from apps.common.audit import log_write

    resource, _is_global = resolve_model_info(sender)
    if not resource:
        return

    record_id = getattr(instance, "pk", None)
    if not isinstance(record_id, int):
        return

    competition_id = extract_competition_id(instance)
    action = _action_for_post_save(created)

    # 1) 审计落库
    try:
        changes = {action: _summarize_instance(instance)}
        log_write(
            model=resource,
            action=f"{resource}:{action}",
            record_id=record_id,
            changes=changes,
            competition_id=competition_id,
        )
    except Exception:  # noqa: BLE001
        logger.debug("审计写入失败 model=%s", resource, exc_info=True)

    # 2) 实时广播
    try:
        from apps.realtime.emit import emit_resource_changed

        emit_resource_changed(resource, record_id, competition_id, action)
    except Exception:  # noqa: BLE001
        logger.debug("广播失败 resource=%s id=%s", resource, record_id, exc_info=True)


def _on_post_delete(sender, instance, **kwargs):
    if not _is_enabled():
        return
    from apps.realtime.emit import (
        extract_competition_id,
        resolve_model_info,
    )
    from apps.common.audit import log_write

    resource, _is_global = resolve_model_info(sender)
    if not resource:
        return

    record_id = getattr(instance, "pk", None)
    if not isinstance(record_id, int):
        return

    competition_id = extract_competition_id(instance)
    action = "deleted"

    try:
        changes = {"deleted": _summarize_instance(instance)}
        log_write(
            model=resource,
            action=f"{resource}:{action}",
            record_id=record_id,
            changes=changes,
            competition_id=competition_id,
        )
    except Exception:  # noqa: BLE001
        logger.debug("审计写入失败 model=%s del", resource, exc_info=True)

    try:
        from apps.realtime.emit import emit_resource_changed

        emit_resource_changed(resource, record_id, competition_id, action)
    except Exception:  # noqa: BLE001
        logger.debug("广播失败 resource=%s id=%s del", resource, record_id, exc_info=True)


# ==================== 统一 connect：在 CommonConfig.ready() 调用 ====================
def connect_all_signals() -> None:
    """对所有已注册的、有 MODEL_TO_RESOURCE 映射的模型，connect post_save/post_delete。

    必须在 django.setup() 完成且所有 apps 都已 populate 之后调用。
    """
    from django.apps import apps
    from apps.realtime.emit import MODEL_TO_RESOURCE

    tracked = set(MODEL_TO_RESOURCE.keys())

    for app_conf in apps.get_app_configs():
        try:
            models_mod = app_conf.models_module
        except Exception:  # noqa: BLE001
            continue
        if models_mod is None:
            continue
        for model in app_conf.get_models():
            name = model.__name__
            if name not in tracked:
                continue
            # None 表示该模型只列在映射里但显式标记为「不广播」（如 PartMaterial/子表）
            if MODEL_TO_RESOURCE.get(name) is None:
                continue
            post_save.connect(_on_post_save, sender=model, weak=False)
            post_delete.connect(_on_post_delete, sender=model, weak=False)
            logger.debug("signals connected for model=%s", name)
