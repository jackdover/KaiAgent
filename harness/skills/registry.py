"""Skill 注册中心 — Skill 注册、匹配、编排。

支持渐进式加载 (先注册描述，命中后加载全文) 和得分排序匹配。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.core.hooks import HookContext
from harness.skills.interface import Skill, SkillContext, SkillMetadata, SimpleYamlSkill
from harness.core.types import ToolDefinition


# 轻量级 Skill 描述 — 在渐进式加载中用于匹配
@dataclass
class SkillDescriptor:
    """轻量级 Skill 描述 — 仅用于匹配决策的元信息。"""
    name: str
    description: str
    match_keywords: list[str]
    priority: int = 0
    loader: Any = None  # 加载函数: () -> Skill


class SkillRegistry:
    """Skill 注册中心 — 管理所有 Skill 的注册、匹配和生命周期。

    支持两种注册方式:
    1. register(skill) — 直接注册完整 Skill (全量加载)
    2. register_descriptor(descriptor) — 注册轻量级描述 (渐进式加载)
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._descriptors: dict[str, SkillDescriptor] = {}
        self._contexts: dict[str, SkillContext] = {}

    # ---- 注册与发现 ----

    def register(self, skill: Skill) -> None:
        """注册一个完整 Skill (全量加载模式)。"""
        name = skill.metadata.name
        self._skills[name] = skill

    def register_descriptor(self, descriptor: SkillDescriptor) -> None:
        """注册一个轻量级 Skill 描述 (渐进式加载模式)。

        匹配阶段仅使用描述信息，命中后才通过 loader 加载完整 Skill。
        """
        self._descriptors[descriptor.name] = descriptor

    def unregister(self, name: str) -> None:
        """取消注册一个 Skill。"""
        self._skills.pop(name, None)
        self._descriptors.pop(name, None)
        self._contexts.pop(name, None)

    def get(self, name: str) -> Skill | None:
        """根据名称获取 Skill。

        如果 Skill 是渐进式加载且尚未加载，会在此时加载。
        """
        skill = self._skills.get(name)
        if skill is None and name in self._descriptors:
            skill = self._load_skill(name)
        return skill

    def _load_skill(self, name: str) -> Skill | None:
        """加载渐进式 Skill (从 descriptor.loader)。"""
        descriptor = self._descriptors.get(name)
        if descriptor is None or descriptor.loader is None:
            return None
        try:
            skill = descriptor.loader()
            if isinstance(skill, Skill):
                self._skills[name] = skill
                return skill
        except Exception:
            pass
        return None

    def _ensure_loaded(self, name: str) -> bool:
        """确保指定 Skill 已加载。"""
        if name in self._skills:
            return True
        if name in self._descriptors:
            return self._load_skill(name) is not None
        return False

    # ---- 匹配 ----

    def match_skills(self, task: str) -> list[tuple[float, Skill | None, str]]:
        """根据用户任务匹配适合的 Skill，返回 (得分, Skill, 名称) 列表。

        先匹配已注册的完整 Skill，再匹配渐进式加载的描述。
        结果按得分降序排列。

        Args:
            task: 用户任务

        Returns:
            list[tuple[float, Skill | None, str]]: (匹配得分, Skill 对象或 None, 名称)
        """
        matches: list[tuple[float, Skill | None, str]] = []

        # 匹配已注册的完整 Skill
        for skill in self._skills.values():
            score = skill.match(task)
            if score > 0:
                matches.append((score, skill, skill.metadata.name))

        # 匹配渐进式加载的描述
        for name, desc in self._descriptors.items():
            if name in self._skills:
                continue  # 已作为完整 Skill 匹配
            score = self._descriptor_match(desc, task)
            if score > 0:
                matches.append((score, None, name))

        # 按得分降序排列
        matches.sort(key=lambda x: x[0], reverse=True)
        return matches

    def _descriptor_match(self, desc: SkillDescriptor, task: str) -> float:
        """匹配轻量级 Skill 描述。"""
        task_lower = task.lower()
        score = 0.0
        for kw in desc.match_keywords:
            if kw.lower() in task_lower:
                score += 1.0
                if len(kw.split()) > 1:
                    score += 0.5
        score += desc.priority * 0.1
        return score

    def select_skill(self, task: str) -> Skill | None:
        """选择最适合的 Skill。

        如果最高分匹配尚未加载，则自动加载。

        Args:
            task: 用户任务

        Returns:
            Skill | None: 选中的 Skill
        """
        matches = self.match_skills(task)
        if not matches:
            return None

        top_score, top_skill, top_name = matches[0]

        # 如果最高分匹配尚未加载，尝试加载
        if top_skill is None:
            self._ensure_loaded(top_name)
            top_skill = self._skills.get(top_name)

        return top_skill

    def list_loaded_descriptions(self) -> list[dict[str, Any]]:
        """列出所有已注册 Skill 的描述 (不触发加载)。

        用于在上下文中先显示 Skill 列表而不加载全部。
        """
        result = []

        # 完整加载的 Skill
        for name, skill in self._skills.items():
            m = skill.metadata
            result.append({
                "name": name,
                "version": m.version,
                "description": m.description,
                "match_keywords": m.match_keywords,
                "plugin_deps": m.plugin_deps,
                "allowed_tools": m.allowed_tools,
                "priority": m.priority,
                "loaded": True,
            })

        # 渐进式加载的未加载 Skill
        for name, desc in self._descriptors.items():
            if name not in self._skills:
                result.append({
                    "name": desc.name,
                    "description": desc.description,
                    "match_keywords": desc.match_keywords,
                    "priority": desc.priority,
                    "loaded": False,
                })

        return result

    # ---- Hook 收集 ----

    def collect_hooks(self) -> dict[str, list]:
        """收集所有已加载 Skill 的 Hook 注册。"""
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
            return selected.get_tools(context)

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
        """列出所有已注册 Skill 的元信息 (兼容旧接口)。"""
        return self.list_loaded_descriptions()

    @property
    def count(self) -> int:
        return len(self._skills) + len(self._descriptors)

    def clear(self) -> None:
        """清除所有 Skill。"""
        self._skills.clear()
        self._descriptors.clear()
        self._contexts.clear()
