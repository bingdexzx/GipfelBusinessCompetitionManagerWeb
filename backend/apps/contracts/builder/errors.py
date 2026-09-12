"""合同类型代码化建库的异常类型。

分三类，便于使用者在脚本里精确捕获：

- `BuildError`   —— 写脚本时的问题（引用缺失、类型不符、必填缺失、重复定义）。
                     发生在 `build()` 之前或之中，**不会写任何数据**。
- `SchemaError`  —— 编译产物不符合后端契约（属于本库的 bug，不是使用者的问题）。
- `DataError`    —— 读取比赛数据时的问题（比赛不存在、快照缺表等）。

设计原则：**能提前发现的错误一律提前到构建期**。运行期才发现的问题（尤其是
「聚合把不存在的名字按 0 计入」这类静默错误）是本次落地要消灭的主要对象。
"""
from __future__ import annotations

from typing import Any, Iterable


class ContractBuilderError(Exception):
    """本库所有异常的基类。"""


class BuildError(ContractBuilderError):
    """建库脚本错误：应当由脚本作者修正。"""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}（{self.hint}）" if self.hint else self.message


class SchemaError(ContractBuilderError):
    """编译产物违反后端契约：属于本库缺陷。"""


class DataError(ContractBuilderError):
    """读取比赛数据失败。"""


# ==================== 常用错误构造 ====================


def unknown_name(kind: str, name: str, available: Iterable[str], *, limit: int = 12) -> BuildError:
    """「名字不存在」的统一报错：附可用清单与最相近的候选，便于直接定位拼写错误。"""
    options = [str(x) for x in available]
    close = _closest(name, options)
    hint_parts = []
    if close:
        hint_parts.append(f"是不是想写「{close}」？")
    if options:
        shown = "、".join(options[:limit])
        more = f" 等 {len(options)} 个" if len(options) > limit else ""
        hint_parts.append(f"可用：{shown}{more}")
    else:
        hint_parts.append(f"当前比赛没有任何{kind}")
    return BuildError(f"{kind}「{name}」不存在", hint=" ".join(hint_parts))


def type_mismatch(field: str, declared: str, needed: str, effect: str) -> BuildError:
    """效果种类与字段类型不匹配：这是「降低抽象」要消灭的核心问题。

    以前 `op="ADD"` 的含义取决于字段类型，写错只能在运行期算出差值；
    现在效果名自带字段类型契约，不匹配直接报错。
    """
    return BuildError(
        f"字段「{field}」的类型声明是 {declared}，但效果「{effect}」只能作用于 {needed} 字段",
        hint=_EFFECT_TYPE_HINTS.get(needed, ""),
    )


def _closest(target: str, options: list[str]) -> str | None:
    """极简近似匹配：大小写无关的包含关系 + 编辑距离阈值。"""
    if not options or not target:
        return None
    low = target.lower()
    for opt in options:
        if opt.lower() == low:
            return opt
    for opt in options:
        if low in opt.lower() or opt.lower() in low:
            return opt
    best: tuple[int, str] | None = None
    for opt in options:
        d = _edit_distance(low, opt.lower())
        if d <= max(1, len(low) // 3) and (best is None or d < best[0]):
            best = (d, opt)
    return best[1] if best else None


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_EFFECT_TYPE_HINTS: dict[str, str] = {
    "NUMBER": "数值字段请用 add_number / sub_number / set_number",
    "LIST": "列表字段请用 append_items / remove_items / set_value",
    "DICTIONARY": "字典字段请用 add_dict / sub_dict / remove_keys / set_value",
    "ANY": "任意类型字段请用 set_value",
}


def require(condition: Any, message: str, *, hint: str | None = None) -> None:
    """轻量断言：不满足即抛 BuildError。"""
    if not condition:
        raise BuildError(message, hint=hint)
