"""Skill 注册中心 — Skill 注册、匹配、编排。"""

from __future__ import annotations

from typing import Any

from harness.core.hooks import HookContext
from harness.skills.interface import Skill, SkillContext
from harness.core.types import ToolDefinition


class SkillRegistry:
    """Skill 注册中心 — 管理所有 Skill 的注册、匹配和生命周期。"""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._contexts: dict[str, SkillContext] = {}

    # ---- 注册与发现 ----

    def register(self, skill: Skill) -> None:
        """注册一个 Skill。"""
        name = skill.metadata.name
        self._skills[name] = skill

    def unregister(self, name: str) -> None:
        """取消注册一个 Skill。"""
        self._skills.pop(name, None)
        self._contexts.pop(name, None)

    def get(self, name: str) -> Skill | None:
        """根据名称获取 Skill。"""
        return self._skills.get(name)

    # ---- 匹配 ----

    def match_skills(self, task: str) -> list[Skill]:
        """根据用户任务匹配适合的 Skill。

        Args:
            task: 用户任务

        Returns:
            list[Skill]: 匹配的 Skill 列表 (按匹配度排序)
        """
        matched = []
        for skill in self._skills.values():
            if skill.match(task):
                matched.append(skill)
        return matched

    def select_skill(self, task: str) -> Skill | None:
        """选择最适合的 Skill。

        如果有多个 Skill 匹配，返回第一个。
        如果没有匹配，返回 None。

        Args:
            task: 用户任务

        Returns:
            Skill | None: 选中的 Skill
        """
        matched = self.match_skills(task)
        return matched[0] if matched else None

    # ---- Hook 收集 ----

    def collect_hooks(self) -> dict[str, list]:
        """收集所有 Skill 的 Hook 注册。"""
        hooks: dict[str, list] = {}
        for skill in self._skills.values():
            skill_hooks = skill.register_hooks()
            for event, handlers in skill_hooks.items():
                hooks.setdefault(event, []).extend(handlers)
        return hooks

    # ---- 上下文管理 ----

    async def create_context(
        self,
        task: str,
        plugin_registry: Any = None,
    ) -> SkillContext:
        """为任务创建 Skill 执行上下文。"""
        return SkillContext(
            task=task,
            plugin_registry=plugin_registry,
        )

    async def get_tools(
        self,
        task: str,
        plugin_registry: Any,
    ) -> list[ToolDefinition]:
        """收集选中 Skill 的工具列表。

        如果有 Skill 匹配，返回该 Skill 的工具。
        否则返回所有 Plugin 的工具。

        Args:
            task: 用户任务
            plugin_registry: Plugin 注册中心

        Returns:
            list[ToolDefinition]: 工具定义列表
        """
        selected = self.select_skill(task)
        if selected:
            context = await self.create_context(task, plugin_registry)
            return await selected.get_tools(context)

        # 没有匹配的 Skill 时，返回所有 Plugin 的工具
        if plugin_registry:
            return plugin_registry.collect_tools()
        return []

    async def get_system_prompt(
        self,
        task: str,
        plugin_registry: Any,
    ) -> str | None:
        """获取选中 Skill 的系统提示。

        Returns:
            str | None: 系统提示内容，无匹配时返回 None
        """
        selected = self.select_skill(task)
        if selected:
            context = await self.create_context(task, plugin_registry)
            return await selected.get_system_prompt(context)
        return None

    # ---- 查询 ----

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有已注册 Skill 的元信息。"""
        return [
            {
                "name": s.metadata.name,
                "version": s.metadata.version,
                "description": s.metadata.description,
                "match_keywords": s.metadata.match_keywords,
                "plugin_deps": s.metadata.plugin_deps,
            }
            for s in self._skills.values()
        ]

    @property
    def count(self) -> int:
        return len(self._skills)

    def clear(self) -> None:
        """清除所有 Skill。"""
        self._skills.clear()
        self._contexts.clear()
