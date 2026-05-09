"""Skill 接口定义 — 面向场景的组合能力。

支持 YAML frontmatter (SKILL.md)、渐进式加载、工具过滤、优先级匹配。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from harness.core.hooks import HookContext
from harness.core.types import LLMMessage, ToolDefinition


# ---- YAML Frontmatter 解析 ---- #

SKILL_MANIFEST_TEMPLATE = """---
name: my_skill
version: "1.0.0"
description: Brief description of what this skill does
author: ""
allowed_tools:
  - read_file
  - write_file
model: opus
context: |
  You are a specialized assistant for this task.
  Provide detailed instructions here.

  ## Guidelines
  1. Follow these rules carefully
  2. Use the allowed tools appropriately
---

This section contains additional markdown content or notes.
"""


@dataclass
class SkillManifest:
    """Skill 清单 — 从 YAML frontmatter 解析而来。"""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    context: str = ""


def parse_skill_manifest(text: str) -> SkillManifest | None:
    """从文本中解析 YAML frontmatter (--- 分隔)。

    Args:
        text: 包含 YAML frontmatter 的文本

    Returns:
        SkillManifest | None: 解析成功返回清单，否则返回 None
    """
    if not text.strip().startswith("---"):
        return None

    try:
        import yaml
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1])
            if isinstance(frontmatter, dict):
                return SkillManifest(
                    name=frontmatter.get("name", "unnamed"),
                    version=str(frontmatter.get("version", "1.0.0")),
                    description=frontmatter.get("description", ""),
                    author=frontmatter.get("author", ""),
                    allowed_tools=frontmatter.get("allowed_tools", []),
                    model=frontmatter.get("model"),
                    context=frontmatter.get("context", ""),
                )
    except ImportError:
        pass
    except Exception:
        pass
    return None


# ---- 核心数据类型 ---- #

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

    # 允许的工具列表 (空 = 全部允许)
    allowed_tools: list[str] = field(default_factory=list)

    # 匹配优先级 (越大越优先匹配)
    priority: int = 0

    # 推荐使用的模型
    recommended_model: str | None = None


@dataclass
class SkillContext:
    """Skill 执行上下文。"""
    task: str                          # 用户原始任务
    messages: list[LLMMessage] = field(default_factory=list)   # 当前对话
    tools: list[ToolDefinition] = field(default_factory=list)  # 可用工具
    plugin_registry: Any = None        # Plugin 注册中心引用
    metadata: dict[str, Any] = field(default_factory=dict)


# ---- 工具模式类型 ---- #

class SkillToolMode:
    """Skill 工具执行模式。

    SKILL_TOOL: 低开销模式 — 注入当前 Agent 上下文，共享上下文窗口。
                适用于简单工具、数据查找、文件操作等。
    AGENT_TOOL: 高开销模式 — 在隔离上下文中运行子 Agent。
                适用于复杂推理、长任务、独立子任务。
    """
    SKILL_TOOL = "skill_tool"
    AGENT_TOOL = "agent_tool"


# ---- Skill 基类 ---- #

class Skill(ABC):
    """Skill 基类 — 所有 Skill 必须实现此接口。

    生命周期: match → create_context → get_system_prompt → get_tools → (hooks)

    Skill 不直接调用 Plugin，而是通过以下方式工作：
    1. 在系统提示中注入领域知识
    2. 通过依赖的 Plugin 暴露 Tools 给 Agent
    3. 通过 Hook 在关键点介入进行校验和后处理
    """

    metadata: SkillMetadata

    @abstractmethod
    async def get_system_prompt(self, context: SkillContext) -> str:
        """返回此 Skill 的系统提示，注入到 Agent 的 System Prompt 中。"""
        ...

    def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        """返回此 Skill 可用的工具列表。

        如果 metadata.allowed_tools 非空，则只返回白名单内的工具。
        子类可重写此方法自定义工具收集逻辑。

        Args:
            context: Skill 执行上下文

        Returns:
            list[ToolDefinition]: 工具定义列表
        """
        tools = self._collect_tools(context)
        if self.metadata.allowed_tools:
            allowed = set(self.metadata.allowed_tools)
            return [t for t in tools if t.name in allowed]
        return tools

    def _collect_tools(self, context: SkillContext) -> list[ToolDefinition]:
        """收集工具 — 供子类重写。(默认使用 Context 中的工具)"""
        return context.tools

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

    def match(self, task: str) -> float:
        """判断此 Skill 是否匹配用户任务，返回匹配得分。

        得分越高表示匹配度越高。0 表示不匹配。

        Args:
            task: 用户任务

        Returns:
            float: 匹配得分 (0.0 = 不匹配, >0 = 匹配度)
        """
        if not self.metadata.match_keywords:
            return 0.0
        task_lower = task.lower()
        score = 0.0
        for kw in self.metadata.match_keywords:
            kw_lower = kw.lower()
            if kw_lower in task_lower:
                # 精确匹配关键词加分
                score += 1.0
                # 精确短语匹配额外加分
                if len(kw_lower.split()) > 1:
                    score += 0.5
        # 加上优先级权重
        score += self.metadata.priority * 0.1
        return score

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

    @property
    def tool_mode(self) -> str:
        """返回工具执行模式。

        子类可重写此属性。

        Returns:
            str: "skill_tool" 或 "agent_tool"
        """
        return SkillToolMode.SKILL_TOOL


class SKILL:
    """用于从 YAML frontmatter 快速创建简单 Skill 的装饰器/工厂。

    使用方式:
        from harness.skills.interface import SKILL

        my_skill = SKILL.from_yaml(\"\"\"---
        name: greeter
        description: A simple greeting skill
        allowed_tools: [read_file]
        context: |
          You are a friendly greeter.
        ---\"\"\")
    """

    @staticmethod
    def from_yaml(text: str) -> "SimpleYamlSkill | None":
        """从 YAML frontmatter 创建 Skill。"""
        manifest = parse_skill_manifest(text)
        if manifest is None:
            return None
        return SimpleYamlSkill(manifest)


class SimpleYamlSkill(Skill):
    """从 YAML frontmatter 创建简单 Skill。"""

    def __init__(self, manifest: SkillManifest):
        self._manifest = manifest
        self.metadata = SkillMetadata(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            allowed_tools=manifest.allowed_tools,
            recommended_model=manifest.model,
        )

    async def get_system_prompt(self, context: SkillContext) -> str:
        return self._manifest.context
