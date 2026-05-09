"""Hooks 系统 — 贯穿 Agent 生命周期的扩展点。"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Awaitable, Callable

from harness.core.types import HookMode


class HookPriority(IntEnum):
    """Hook 执行优先级 (值越小越先执行)。"""
    SYSTEM = 0      # 系统级 (权限检查、日志)
    PLUGIN = 50     # 插件级
    SKILL = 75      # 技能级
    NORMAL = 100    # 普通级
    LATE = 200      # 用户级


# 所有支持的事件名称
HOOK_EVENTS = frozenset({
    "on_harness_start",
    "on_harness_stop",
    "on_session_start",
    "on_session_end",
    "on_step_start",
    "on_step_end",
    "on_before_think",
    "on_after_think",
    "on_before_action",
    "on_after_action",
    "on_checkpoint",
    "on_error",
})


@dataclass
class HookContext:
    """Hook 上下文 — 在事件链中传递。"""
    event: str
    data: Any
    abort: bool = False
    abort_reason: str | None = None
    modified: dict[str, Any] = field(default_factory=dict)

    def set_modified(self, key: str, value: Any) -> None:
        self.modified[key] = value

    def get_modified(self, key: str, default: Any = None) -> Any:
        return self.modified.get(key, default)


HookFn = Callable[[HookContext], Awaitable[HookContext | None]]


class HookRegistry:
    """Hook 注册中心 — 管理所有 Hook 的注册与分发。"""

    def __init__(self):
        self._hooks: dict[str, list[tuple[int, HookFn, HookMode]]] = {}

    def register(
        self,
        event: str,
        fn: HookFn,
        priority: int = HookPriority.NORMAL,
        mode: HookMode = HookMode.OBSERVE,
    ) -> None:
        """注册一个 Hook 函数到指定事件。

        Args:
            event: 事件名称，必须是 HOOK_EVENTS 中的值
            fn: 异步回调函数
            priority: 执行优先级，越小越先执行
            mode: Hook 执行模式

        Raises:
            ValueError: 如果事件名称不合法
        """
        if event not in HOOK_EVENTS:
            raise ValueError(
                f"Unknown event '{event}'. Valid events: {sorted(HOOK_EVENTS)}"
            )
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"Hook function must be async: {fn}")
        self._hooks.setdefault(event, []).append((priority, fn, mode))
        self._hooks[event].sort(key=lambda x: x[0])

    def unregister(self, event: str, fn: HookFn) -> None:
        """取消注册一个 Hook 函数。"""
        if event not in self._hooks:
            return
        self._hooks[event] = [
            (p, f, m) for p, f, m in self._hooks[event] if f is not fn
        ]

    async def emit(self, event: str, data: Any = None) -> HookContext:
        """发射事件，按优先级依次执行所有注册的 Hook。

        Args:
            event: 事件名称
            data: 事件携带的数据

        Returns:
            HookContext: 经过所有 Hook 处理后的上下文

        Raises:
            HookAbortError: 如果有 ABORT 模式的 Hook 中止了流程
        """
        ctx = HookContext(event=event, data=data)
        handlers = self._hooks.get(event, [])

        for priority, fn, mode in handlers:
            try:
                result = await fn(ctx)
                if result is not None:
                    ctx = result
            except Exception as e:
                ctx.abort = True
                ctx.abort_reason = f"Hook '{fn.__name__}' failed: {e}"

            if mode == HookMode.ABORT and ctx.abort:
                raise HookAbortError(event, ctx.abort_reason or "Hook aborted")

        return ctx

    def list_events(self) -> list[str]:
        """列出所有有 Hook 注册的事件。"""
        return [e for e, h in self._hooks.items() if h]

    def count_hooks(self, event: str | None = None) -> int:
        """统计 Hook 数量。"""
        if event:
            return len(self._hooks.get(event, []))
        return sum(len(h) for h in self._hooks.values())

    def clear(self) -> None:
        """清除所有注册的 Hook。"""
        self._hooks.clear()


class HookAbortError(Exception):
    """Hook 中止异常。"""

    def __init__(self, event: str, reason: str):
        self.event = event
        self.reason = reason
        super().__init__(f"Hook aborted at '{event}': {reason}")
