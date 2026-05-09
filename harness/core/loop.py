"""Agent Loop — 核心状态机，驱动 think→act→observe 循环。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

from harness.core.hooks import HookRegistry, HookContext, HookAbortError
from harness.core.memory import (
    EpisodicMemory,
    WorkingMemory,
    Summarizer,
)
from harness.core.permissions import PermissionDenied, PermissionPolicy, ResourceType
from harness.core.recovery import RecoveryManager
from harness.core.types import (
    Action,
    ActionType,
    AgentStatus,
    LLMMessage,
    LLMResponse,
    Observation,
    SessionResult,
    SessionState,
    Step,
    ToolCall,
    ToolDefinition,
)


class AgentLoop:
    """Agent 主循环 — 状态机驱动的 think→act→observe 执行引擎。

    状态流转:
        INIT → IDLE → THINKING → ACTING → OBSERVING → (→THINKING/→DONE)
    """

    # 工具名称到资源类型的映射
    _TOOL_RESOURCE_MAP: dict[str, ResourceType] = {
        "read_file": ResourceType.FILE_READ,
        "list_files": ResourceType.FILE_READ,
        "write_file": ResourceType.FILE_WRITE,
        "execute_command": ResourceType.EXEC_COMMAND,
        "http_get": ResourceType.NETWORK_REQUEST,
        "http_post": ResourceType.NETWORK_REQUEST,
    }

    def __init__(
        self,
        hooks: HookRegistry,
        working_memory: WorkingMemory,
        episodic_memory: EpisodicMemory,
        recovery: RecoveryManager,
        summarizer: Summarizer | None = None,
        llm_provider: Any | None = None,
        permissions: PermissionPolicy | None = None,
        plugin_registry: Any | None = None,
        max_steps: int = 50,
    ):
        self.hooks = hooks
        self.working_memory = working_memory
        self.episodic_memory = episodic_memory
        self.recovery = recovery
        self.summarizer = summarizer or Summarizer()
        self.llm = llm_provider
        self.permissions = permissions or PermissionPolicy()
        self.plugin_registry = plugin_registry
        self.max_steps = max_steps
        self._state: SessionState | None = None
        self._tools: list[ToolDefinition] = []

    @property
    def state(self) -> SessionState | None:
        """当前会话状态。"""
        return self._state

    def set_tools(self, tools: list[ToolDefinition]) -> None:
        """设置 LLM 可用的工具列表。"""
        self._tools = tools

    async def execute(self, task: str, session_id: str | None = None) -> SessionResult:
        """执行一个完整任务，包含多个 step。

        这是 Agent Loop 的主入口。

        Args:
            task: 用户任务
            session_id: 可选的 session ID (用于恢复)

        Returns:
            SessionResult: 会话执行结果
        """
        start_time = datetime.now()

        # 检查是否有 checkpoint 可恢复
        if session_id and self.recovery.has_checkpoint(session_id):
            await self._resume_session(session_id)
        else:
            self._state = SessionState(
                session_id=session_id or f"session_{uuid.uuid4().hex[:12]}",
                status=AgentStatus.IDLE,
                task=task,
            )

        await self.hooks.emit("on_session_start", self._state)
        await self.episodic_memory.start_session(self._state.session_id)

        step_count = 0
        final_error: str | None = None

        try:
            while step_count < self.max_steps:
                if self._state.status == AgentStatus.DONE:
                    break

                step_count += 1
                step = await self._run_one_step(task, step_count)

                # 检查是否完成
                if self._is_finished(step):
                    self._state.status = AgentStatus.DONE
                    break

                # 保存 checkpoint (每 3 步保存一次)
                if step_count % 3 == 0:
                    await self._checkpoint()

        except HookAbortError as e:
            self._state.status = AgentStatus.ERROR
            final_error = str(e)
        except Exception as e:
            self._state.status = AgentStatus.ERROR
            final_error = f"Unexpected error: {e}"
        else:
            # Loop ended normally (max_steps reached without finish)
            if self._state.status not in (AgentStatus.DONE, AgentStatus.ERROR):
                self._state.status = AgentStatus.DONE
        finally:
            await self._checkpoint()
            await self.episodic_memory.save()
            await self.hooks.emit("on_session_end", self._state)

        duration = (datetime.now() - start_time).total_seconds()
        output = (
            self._state.steps[-1].action.content
            if self._state.steps and self._state.steps[-1].action
            else None
        )

        return SessionResult(
            session_id=self._state.session_id,
            status=self._state.status,
            steps=list(self._state.steps),
            output=output,
            error=final_error,
            total_duration=duration,
        )

    async def _run_one_step(self, task: str, step_number: int) -> Step:
        """执行一个完整的 step: think → act → observe。

        Args:
            task: 用户任务
            step_number: 当前 step 编号

        Returns:
            Step: 完成的 step
        """
        step = Step(id=f"step_{step_number}")
        self._state.current_step = step
        self._state.status = AgentStatus.THINKING

        await self.hooks.emit("on_step_start", step)

        # --- THINK ---
        step.thought = await self._think(task, step_number)

        # --- ACT ---
        self._state.status = AgentStatus.ACTING
        step.action = await self._act(step.thought)
        await self.hooks.emit("on_before_action", step.action)

        # --- OBSERVE ---
        self._state.status = AgentStatus.OBSERVING
        step.observation = await self._observe(step.action)
        await self.hooks.emit("on_after_action", step)

        # 完成 step
        step.completed_at = datetime.now()
        self._state.steps.append(step)
        await self.episodic_memory.record_step(step)
        await self.hooks.emit("on_step_end", step)

        # 检查是否需要压缩
        await self._maybe_compress()

        return step

    async def _think(self, task: str, step_number: int) -> str | None:
        """THINK 阶段：LLM 推理，决定下一步做什么。

        组装上下文，调用 LLM，返回推理结果。
        """
        await self.hooks.emit("on_before_think", {"task": task, "step": step_number})

        if not self.llm:
            # 没有 LLM provider 时使用简单模式
            thought = f"[Step {step_number}] Thinking about: {task}"
            self._state.current_step.thought = thought
            await self.hooks.emit("on_after_think", thought)
            return thought

        # 组装上下文
        system_msg = await self.working_memory.get_system()
        context = (
            [system_msg]
            if system_msg
            else [LLMMessage(role="system", content=self._build_system_prompt(task))]
        )

        # 添加历史记忆
        episode_msgs = await self.episodic_memory.get_context()
        context.extend(episode_msgs)

        # 添加当前任务消息
        step_prompt = (
            f"Task: {task}\n"
            f"Current step: {step_number}/{self.max_steps}\n"
            f"Please think step by step about what to do next."
        )
        context.append(LLMMessage(role="user", content=step_prompt))

        # 调用 LLM
        tools = self._tools if self._tools else None
        response: LLMResponse = await self.llm.chat(
            messages=context,
            tools=tools,
        )

        thought = response.content
        if response.tool_calls:
            # 如果 LLM 直接返回了 tool_calls, 存储在 current_step 的 metadata 中
            self._state.current_step.metadata["pending_tool_calls"] = [
                tc.to_dict() if hasattr(tc, "to_dict") else tc
                for tc in response.tool_calls
            ]

        await self.hooks.emit("on_after_think", thought)
        return thought

    async def _act(self, thought: str | None) -> Action:
        """ACT 阶段：根据推理结果生成 Action。

        Args:
            thought: 推理结果

        Returns:
            Action: 要执行的动作
        """
        pending_tool_calls = (
            self._state.current_step.metadata.get("pending_tool_calls", [])
            if self._state.current_step
            else []
        )

        if pending_tool_calls:
            tool_calls = [
                ToolCall(
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", {}),
                    tool_call_id=tc.get("tool_call_id", ""),
                )
                for tc in pending_tool_calls
            ]
            return Action(
                type=ActionType.TOOL_CALL,
                content=None,
                tool_calls=tool_calls,
            )

        if not thought:
            return Action(
                type=ActionType.TEXT_RESPONSE,
                content="I have nothing to say.",
            )

        # 默认生成为文本回复
        return Action(type=ActionType.TEXT_RESPONSE, content=thought)

    async def _observe(self, action: Action) -> Observation:
        """OBSERVE 阶段：执行 action 并收集结果。

        Args:
            action: 要执行的动作

        Returns:
            Observation: 观察结果
        """
        if action.type == ActionType.FINISH:
            return Observation(content="Task finished.")

        if action.type == ActionType.TEXT_RESPONSE:
            return Observation(content=action.content or "")

        if action.type == ActionType.TOOL_CALL:
            return await self._execute_tool_calls(action.tool_calls)

        return Observation(content="No observation.")

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall]
    ) -> Observation:
        """执行工具调用并收集结果。

        优先通过 PluginRegistry 执行，无 Plugin 时返回模拟结果。
        """
        results = []
        for tc in tool_calls:
            await self.hooks.emit("on_pre_tool_use", tc)
            result = await self._execute_single_tool(tc)
            if result.get("result", "").startswith("Error"):
                await self.hooks.emit("on_post_tool_use_failure", result)
            else:
                await self.hooks.emit("on_post_tool_use", result)
            results.append(result)

        return Observation(
            content=f"Executed {len(tool_calls)} tool call(s)",
            tool_results=results,
        )

    def _get_tool_resource(self, tc: ToolCall) -> str:
        """从工具调用参数中提取要检查的资源标识符。"""
        resource_type = self._TOOL_RESOURCE_MAP.get(tc.name)
        if not resource_type:
            return tc.name
        if resource_type == ResourceType.EXEC_COMMAND:
            return tc.arguments.get("command", "")
        if resource_type in (ResourceType.FILE_READ, ResourceType.FILE_WRITE):
            return tc.arguments.get("path", "")
        if resource_type == ResourceType.NETWORK_REQUEST:
            return tc.arguments.get("url", "")
        return tc.name

    async def _execute_single_tool(self, tc: ToolCall) -> dict[str, Any]:
        """执行单个工具调用。"""
        # 权限检查 (使用工具级权限检查)
        resource_type = self._TOOL_RESOURCE_MAP.get(tc.name)
        if resource_type:
            resource = self._get_tool_resource(tc)
            try:
                self.permissions.check_tool(tc.name, resource)
            except PermissionDenied as e:
                return {
                    "tool_call_id": tc.tool_call_id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result": str(e),
                }

        # 有 PluginRegistry 时通过 Plugin 执行
        if self.plugin_registry:
            for plugin in self.plugin_registry._plugins.values():
                if hasattr(plugin, 'execute_tool'):
                    try:
                        plugin_result = await plugin.execute_tool(
                            tc.name, tc.arguments
                        )
                        return {
                            "tool_call_id": tc.tool_call_id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                            "result": plugin_result,
                        }
                    except PermissionDenied:
                        raise
                    except Exception as e:
                        return {
                            "tool_call_id": tc.tool_call_id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                            "result": f"Error: {e}",
                        }

        # 无 Plugin 时返回模拟结果
        return {
            "tool_call_id": tc.tool_call_id,
            "name": tc.name,
            "arguments": tc.arguments,
            "result": f"[Tool '{tc.name}' execution simulated]",
        }

    async def _resume_session(self, session_id: str) -> None:
        """从 checkpoint 恢复会话。"""
        checkpoint = await self.recovery.load(session_id)
        if checkpoint:
            self._state = await self.recovery.resume(checkpoint)

    async def _checkpoint(self) -> None:
        """保存 checkpoint。"""
        if self._state:
            await self.recovery.save(self._state)
            await self.hooks.emit("on_checkpoint", self._state)

    async def _maybe_compress(self) -> None:
        """在必要时压缩记忆。"""
        # 发射 PreCompact Hook (用于压缩前保存状态)
        await self.hooks.emit("on_pre_compact", self._state)

        # 检查 working memory 是否需要压缩
        if await self.working_memory.needs_compression():
            await self.working_memory.compress()

        # 检查 episodic memory 是否需要压缩
        if await self.episodic_memory.needs_compression():
            summary = await self.episodic_memory.compress()
            summary_msg = LLMMessage(
                role="system",
                content=f"[Episode Summary]: {summary.content}",
            )
            await self.working_memory.add(summary_msg)

        # 发射 PostCompact Hook
        await self.hooks.emit("on_post_compact", self._state)

    def _build_system_prompt(self, task: str) -> str:
        """构建 system prompt。"""
        lines = [
            "You are a capable AI assistant running in an agent harness.",
            "",
            "You operate in a think→act→observe loop:",
            "1. THINK: Reason about the task and decide what to do next",
            "2. ACT: Execute a tool call or provide a response",
            "3. OBSERVE: See the results and decide next step",
            "",
            "Available tools will be provided to you.",
            f"\nTask: {task}",
        ]
        return "\n".join(lines)

    def _is_finished(self, step: Step) -> bool:
        """判断任务是否完成。"""
        return (
            step.action is not None
            and step.action.type == ActionType.FINISH
        )
