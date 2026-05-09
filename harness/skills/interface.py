"""Skill 接口定义 — 面向场景的组合能力。

Skill = Prompt 模板 + Tool 编排 + 规则配置
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from harness.core.hooks import HookContext
from harness.core.types import LLMMessage, ToolDefinition


@dataclass
class SkillMetadata:
    """Skill 元数据。"""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""

    # 匹配规则: 当用户输入命中这些关键词时自动匹配
    match_keywords: list[str] = field(default_factory=list)

    # 依赖的 Plugin 名称列表
    plugin_deps: list[str] = field(default_factory=list)


@dataclass
class SkillContext:
    """Skill 执行上下文。"""
    task: str                          # 用户原始任务
    messages: list[LLMMessage] = field(default_factory=list)   # 当前对话
    tools: list[ToolDefinition] = field(default_factory=list)  # 可用工具
    plugin_registry: Any = None        # Plugin 注册中心引用
    metadata: dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    """Skill 基类 — 所有 Skill 必须实现此接口。

    Skill 不直接调用 Plugin，而是通过以下方式工作：
    1. 在系统提示中注入领域知识
    2. 通过依赖的 Plugin 暴露 Tools 给 Agent
    3. 通过 Hook 在关键点介入进行校验和后处理
    """

    metadata: SkillMetadata

    @abstractmethod
    async def get_system_prompt(self, context: SkillContext) -> str:
        """返回此 Skill 的系统提示，注入到 Agent 的 System Prompt 中。

        Args:
            context: Skill 执行上下文

        Returns:
            str: 系统提示内容
        """
        ...

    @abstractmethod
    async def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        """返回此 Skill 可用的工具列表。

        从依赖的 Plugin 中收集工具。

        Args:
            context: Skill 执行上下文

        Returns:
            list[ToolDefinition]: 工具定义列表
        """
        ...

    async def on_before_think(self, ctx: HookContext) -> HookContext | None:
        """Hook: 思考前 — 注入系统提示。"""
        context: SkillContext | None = ctx.data.get("skill_context")
        if context:
            prompt = await self.get_system_prompt(context)
            ctx.set_modified("system_prompt_extra", prompt)
        return ctx

    async def on_after_action(self, ctx: HookContext) -> HookContext | None:
        """Hook: 动作后 — 校验输出。"""
        return ctx

    async def on_step_end(self, ctx: HookContext) -> HookContext | None:
        """Hook: Step 结束 — 后处理。"""
        return ctx

    async def on_before_action(self, ctx: HookContext) -> HookContext | None:
        """Hook: 动作前 — 拦截危险操作。"""
        return ctx

    def match(self, task: str) -> bool:
        """判断此 Skill 是否匹配用户任务。

        通过关键词匹配来决定是否激活此 Skill。

        Args:
            task: 用户任务

        Returns:
            bool: 是否匹配
        """
        if not self.metadata.match_keywords:
            return False
        task_lower = task.lower()
        return any(kw.lower() in task_lower for kw in self.metadata.match_keywords)

    def register_hooks(self) -> dict[str, list]:
        """注册此 Skill 需要 Hook 的事件。

        子类可以重写此方法来注册更多 Hook。

        Returns:
            dict: event_name → [handler_functions]
        """
        hooks = {}
        hooks["on_before_think"] = [self.on_before_think]
        hooks["on_after_action"] = [self.on_after_action]
        hooks["on_step_end"] = [self.on_step_end]
        hooks["on_before_action"] = [self.on_before_action]
        return hooks
