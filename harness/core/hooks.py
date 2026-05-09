"""Hooks 系统 — 贯穿 Agent 生命周期的扩展点。

支持 17+ 事件类型、matcher 条件过滤、command/http 三种 Hook 类型。
"""

from __future__ import annotations

import asyncio
import fnmatch
import inspect
import json
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


# 所有支持的事件名称 (17+ 事件)
HOOK_EVENTS = frozenset({
    # 生命周期事件
    "on_harness_start",
    "on_harness_stop",
    "on_session_start",
    "on_session_end",
    # Step 生命周期
    "on_step_start",
    "on_step_end",
    # Think 阶段
    "on_before_think",
    "on_after_think",
    # Action 阶段
    "on_before_action",
    "on_after_action",
    # 工具执行事件
    "on_pre_tool_use",
    "on_post_tool_use",
    "on_post_tool_use_failure",
    # 记忆压缩事件
    "on_pre_compact",
    "on_post_compact",
    # 用户交互事件
    "on_user_prompt_submit",
    # 其他
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


@dataclass
class HookMatcher:
    """Hook 匹配器 — 用于条件过滤 Hook 执行。

    所有条件均为可选，未设置的条件默认匹配。
    """

    tool_names: list[str] | None = None      # 工具名 glob 模式
    paths: list[str] | None = None           # 路径 glob 模式
    event_types: list[str] | None = None     # 事件类型列表
    custom: Callable[[HookContext], bool] | None = None  # 自定义匹配函数

    def matches(self, ctx: HookContext) -> bool:
        """检查 Hook 上下文是否匹配此过滤条件。"""
        if self.custom is not None and not self.custom(ctx):
            return False

        if self.tool_names:
            data = ctx.data
            tool_name = ""
            if hasattr(data, 'name'):
                tool_name = data.name
            elif isinstance(data, dict):
                tool_name = data.get('name', '') or data.get('tool_name', '')
            if not any(fnmatch.fnmatch(tool_name, pat) for pat in self.tool_names):
                return False

        if self.paths:
            data = ctx.data
            path = ""
            if isinstance(data, dict):
                path = data.get('path', '') or data.get('file_path', '')
            elif hasattr(data, 'path'):
                path = data.path if hasattr(data, 'path') else str(data)
            if not any(fnmatch.fnmatch(path, pat) for pat in self.paths):
                return False

        if self.event_types:
            if ctx.event not in self.event_types:
                return False

        return True


@dataclass
class HookRegistration:
    """Hook 注册信息。"""
    priority: int
    fn: HookFn
    mode: HookMode
    matcher: HookMatcher | None = None


class HookRegistry:
    """Hook 注册中心 — 管理所有 Hook 的注册与分发。"""

    def __init__(self):
        self._hooks: dict[str, list[HookRegistration]] = {}

    def register(
        self,
        event: str,
        fn: HookFn,
        priority: int = HookPriority.NORMAL,
        mode: HookMode = HookMode.OBSERVE,
        matcher: HookMatcher | None = None,
    ) -> None:
        """注册一个 Hook 函数到指定事件。

        Args:
            event: 事件名称，必须是 HOOK_EVENTS 中的值
            fn: 异步回调函数
            priority: 执行优先级，越小越先执行
            mode: Hook 执行模式
            matcher: 可选的条件匹配器

        Raises:
            ValueError: 如果事件名称不合法
            TypeError: 如果 fn 不是异步函数
        """
        if event not in HOOK_EVENTS:
            raise ValueError(
                f"Unknown event '{event}'. Valid events: {sorted(HOOK_EVENTS)}"
            )
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"Hook function must be async: {fn}")
        reg = HookRegistration(priority=priority, fn=fn, mode=mode, matcher=matcher)
        self._hooks.setdefault(event, []).append(reg)
        self._hooks[event].sort(key=lambda x: x.priority)

    def unregister(self, event: str, fn: HookFn) -> None:
        """取消注册一个 Hook 函数。"""
        if event not in self._hooks:
            return
        self._hooks[event] = [
            reg for reg in self._hooks[event] if reg.fn is not fn
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

        for reg in handlers:
            # 如果定义了 matcher，先检查是否匹配
            if reg.matcher is not None and not reg.matcher.matches(ctx):
                continue
            try:
                result = await reg.fn(ctx)
                if result is not None:
                    ctx = result
            except Exception as e:
                ctx.abort = True
                ctx.abort_reason = f"Hook '{reg.fn.__name__}' failed: {e}"

            if reg.mode == HookMode.ABORT and ctx.abort:
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

    # ---- 便捷方法：创建特定类型的 Hook ---- #

    async def register_command_hook(
        self,
        event: str,
        command: str,
        priority: int = HookPriority.NORMAL,
        mode: HookMode = HookMode.OBSERVE,
        matcher: HookMatcher | None = None,
        timeout: int = 30,
    ) -> None:
        """注册一个命令行 Hook — 事件触发时执行 shell 命令。

        命令的执行不阻塞 Agent Loop 上下文 (通过 asyncio.create_subprocess_shell)。

        Args:
            event: 事件名称
            command: 要执行的 shell 命令
            priority: 执行优先级
            mode: Hook 执行模式
            matcher: 可选的条件匹配器
            timeout: 超时秒数
        """
        async def _command_handler(ctx: HookContext) -> HookContext | None:
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                    output = ""
                    if stdout:
                        output += stdout.decode("utf-8", errors="replace")
                    if stderr:
                        if output:
                            output += "\n--- stderr ---\n"
                        output += stderr.decode("utf-8", errors="replace")
                    ctx.set_modified(f"command_{command[:20]}", output[:1000])
                except asyncio.TimeoutError:
                    proc.kill()
                    ctx.set_modified(f"command_{command[:20]}", "TIMEOUT")
            except Exception as e:
                ctx.set_modified(f"command_{command[:20]}", f"ERROR: {e}")
            return ctx

        self.register(event, _command_handler, priority, mode, matcher)

    async def register_http_hook(
        self,
        event: str,
        url: str,
        priority: int = HookPriority.NORMAL,
        mode: HookMode = HookMode.OBSERVE,
        matcher: HookMatcher | None = None,
        timeout: int = 10,
    ) -> None:
        """注册一个 HTTP Hook — 事件触发时 POST JSON 到 URL。

        Args:
            event: 事件名称
            url: 目标 URL
            priority: 执行优先级
            mode: Hook 执行模式
            matcher: 可选的条件匹配器
            timeout: 超时秒数
        """
        async def _http_handler(ctx: HookContext) -> HookContext | None:
            payload = {
                "event": ctx.event,
                "data": str(ctx.data)[:5000],
                "abort": ctx.abort,
                "modified_keys": list(ctx.modified.keys()),
            }
            try:
                import httpx
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=payload)
                    ctx.set_modified(f"http_{url[:30]}", resp.status_code)
            except ImportError:
                # 回退到 urllib
                try:
                    import urllib.request
                    data = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(
                        url, data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        ctx.set_modified(f"http_{url[:30]}", resp.status)
                except Exception as e:
                    ctx.set_modified(f"http_{url[:30]}", f"ERROR: {e}")
            except Exception as e:
                ctx.set_modified(f"http_{url[:30]}", f"ERROR: {e}")
            return ctx

        self.register(event, _http_handler, priority, mode, matcher)


class HookAbortError(Exception):
    """Hook 中止异常。"""

    def __init__(self, event: str, reason: str):
        self.event = event
        self.reason = reason
        super().__init__(f"Hook aborted at '{event}': {reason}")
