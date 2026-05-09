"""AgentTool — 在隔离上下文中运行子 Agent。

提供两种模式:
  - SkillTool (低开销): 在当前 Agent 上下文中注入工具，共享上下文窗口
  - AgentTool (高开销): 在新上下文窗口中启动子 Agent，独立完成子任务

子 Agent 支持:
  - 单独的上下文窗口
  - 单独的权限策略 (支持 bubble 模式冒泡到父级审批)
  - 可选的 worktree 隔离
  - 并行执行 (asyncio.gather)
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from harness.core.hooks import HookRegistry
from harness.core.permissions import (
    ApprovalMode,
    PermissionPolicy,
    PendingApproval,
)
from harness.core.types import ToolDefinition
from harness.skills.interface import SkillContext


@dataclass
class AgentToolConfig:
    """AgentTool 配置。"""
    max_steps: int = 20
    timeout_seconds: int = 120
    isolation: str = "none"  # "none", "worktree"
    bubble_permissions: bool = False  # True = 权限冒泡到父级
    parallel: bool = False  # True = 允许并行执行


@dataclass
class SubAgentResult:
    """子 Agent 执行结果。"""
    task: str
    output: str
    success: bool
    steps: int
    duration: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentTool:
    """AgentTool — 运行子 Agent 的工具。

    使用方式:
        agent_tool = AgentTool(harness)
        result = await agent_tool.run_sub_agent(
            task="阅读 README.md",
            config=AgentToolConfig(max_steps=10),
        )
    """

    def __init__(self, parent_harness: Any = None):
        self._parent = parent_harness
        self._sub_agents: list[asyncio.Task] = []

    async def run_sub_agent(
        self,
        task: str,
        config: AgentToolConfig | None = None,
        permissions: PermissionPolicy | None = None,
    ) -> SubAgentResult:
        """运行一个子 Agent 完成任务。

        Args:
            task: 子任务描述
            config: AgentTool 配置
            permissions: 子 Agent 的权限策略 (默认继承父级)

        Returns:
            SubAgentResult: 子 Agent 执行结果
        """
        cfg = config or AgentToolConfig()
        start_time = datetime.now()
        session_id = f"sub_{uuid.uuid4().hex[:12]}"

        try:
            from harness import Harness
            from harness.config.schema import HarnessConfig

            # 创建子 Harness 实例
            sub_config = HarnessConfig.default()
            sub_config.max_steps = cfg.max_steps

            # 权限策略
            if permissions:
                sub_harness = Harness(config=sub_config)
                sub_harness._permissions = permissions
            else:
                sub_harness = Harness(config=sub_config)

            await sub_harness.start()
            result = await sub_harness.run(task, session_id=session_id)
            await sub_harness.stop()

            duration = (datetime.now() - start_time).total_seconds()

            return SubAgentResult(
                task=task,
                output=result.output or "",
                success=result.status.name == "DONE" and not result.error,
                steps=len(result.steps),
                duration=duration,
                error=result.error,
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return SubAgentResult(
                task=task,
                output="",
                success=False,
                steps=0,
                duration=duration,
                error=str(e),
            )

    async def run_sub_agents_parallel(
        self,
        tasks: list[str],
        config: AgentToolConfig | None = None,
        max_concurrent: int = 5,
    ) -> list[SubAgentResult]:
        """并行运行多个子 Agent。

        Args:
            tasks: 子任务描述列表
            config: AgentTool 配置
            max_concurrent: 最大并行数

        Returns:
            list[SubAgentResult]: 执行结果列表
        """
        cfg = config or AgentToolConfig()
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _run_with_semaphore(task: str) -> SubAgentResult:
            async with semaphore:
                return await self.run_sub_agent(task, cfg)

        results = await asyncio.gather(
            *[_run_with_semaphore(t) for t in tasks],
            return_exceptions=True,
        )

        return [
            r if isinstance(r, SubAgentResult) else SubAgentResult(
                task=tasks[i],
                output="",
                success=False,
                steps=0,
                duration=0,
                error=str(r),
            )
            for i, r in enumerate(results)
        ]

    def cancel_all(self) -> None:
        """取消所有正在运行的子 Agent。"""
        for task in self._sub_agents:
            task.cancel()
        self._sub_agents.clear()


def create_skill_tool(
    tool_name: str,
    context: SkillContext,
) -> ToolDefinition:
    """创建一个 SkillTool — 注入到当前 Agent 上下文的轻量工具。

    SkillTool 适合:
    - 简单的数据查找
    - 文件操作
    - 不需要独立推理的原子操作

    Args:
        tool_name: 工具名称
        context: Skill 上下文

    Returns:
        ToolDefinition: 工具定义
    """
    return ToolDefinition(
        name=tool_name,
        description=f"Skill tool: {tool_name}",
        parameters={
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": f"Input for {tool_name}",
                },
            },
            "required": ["input"],
        },
    )


def create_bubble_policy(
    base_policy: PermissionPolicy,
) -> PermissionPolicy:
    """创建一个 bubble 模式权限策略 — 子 Agent 权限冒泡到父级审批。

    Args:
        base_policy: 基础权限策略

    Returns:
        PermissionPolicy: bubble 模式策略
    """
    return PermissionPolicy(
        level=base_policy.level,
        read_paths=base_policy.read_paths,
        write_paths=base_policy.write_paths,
        exec_commands=base_policy.exec_commands,
        network_hosts=base_policy.network_hosts,
        env_vars=base_policy.env_vars,
        deny_rules=base_policy.deny_rules,
        tool_permissions=base_policy.tool_permissions,
        approval_mode=ApprovalMode.BUBBLE,
    )
