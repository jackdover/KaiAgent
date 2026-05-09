"""Harness 顶层入口 — 组装所有组件，对外暴露统一接口。"""

from __future__ import annotations

from typing import Any

from harness.config.schema import HarnessConfig
from harness.core.hooks import HookRegistry, HookPriority
from harness.core.loop import AgentLoop
from harness.core.memory import (
    EpisodicMemory,
    EpisodicMemoryConfig,
    Summarizer,
    WorkingMemory,
    WorkingMemoryConfig,
)
from harness.core.permissions import PermissionLevel, PermissionPolicy
from harness.core.recovery import RecoveryManager
from harness.core.types import SessionResult
from harness.plugins import PluginRegistry
from harness.plugins.builtins.file import FilePlugin
from harness.plugins.builtins.shell import ShellPlugin
from harness.plugins.builtins.web import WebPlugin
from harness.skills import SkillRegistry, SkillContext


class Harness:
    """Harness 顶层入口 — Agent 运行时。

    使用方式:
        harness = Harness()
        await harness.start()
        result = await harness.run("帮我读一下 README.md")
        await harness.stop()
    """

    def __init__(self, config: HarnessConfig | None = None):
        self.config = config or HarnessConfig.default()
        self._started = False

        # 子系统 (延迟初始化)
        self._hooks: HookRegistry | None = None
        self._permissions: PermissionPolicy | None = None
        self._loop: AgentLoop | None = None
        self._working_memory: WorkingMemory | None = None
        self._episodic_memory: EpisodicMemory | None = None
        self._recovery: RecoveryManager | None = None
        self._plugin_registry: PluginRegistry | None = None
        self._skill_registry: SkillRegistry | None = None

    # ---- 属性访问 ----

    @property
    def hooks(self) -> HookRegistry:
        assert self._hooks is not None, "Harness not started"
        return self._hooks

    @property
    def permissions(self) -> PermissionPolicy:
        assert self._permissions is not None, "Harness not started"
        return self._permissions

    @property
    def loop(self) -> AgentLoop:
        assert self._loop is not None, "Harness not started"
        return self._loop

    @property
    def plugins(self) -> PluginRegistry:
        assert self._plugin_registry is not None, "Harness not started"
        return self._plugin_registry

    @property
    def skills(self) -> SkillRegistry:
        assert self._skill_registry is not None, "Harness not started"
        return self._skill_registry

    # ---- 生命周期 ----

    async def start(self) -> None:
        """启动 Harness，初始化所有子系统。"""
        if self._started:
            return

        # 1. 初始化 Hook 系统
        self._hooks = HookRegistry()

        # 2. 初始化权限系统
        self._permissions = self._build_permissions()

        # 3. 初始化 Plugin 系统 (要先于 Loop，因为 Loop 依赖 Plugin 系统)
        self._plugin_registry = PluginRegistry()
        await self._init_plugins()

        # 4. 初始化记忆系统
        self._working_memory = WorkingMemory(
            WorkingMemoryConfig(
                max_tokens=self.config.memory.working_max_tokens,
            )
        )
        self._episodic_memory = EpisodicMemory(
            EpisodicMemoryConfig(
                persist_dir=self.config.memory.episodic_persist_dir,
            )
        )

        # 5. 初始化恢复管理器
        self._recovery = RecoveryManager(
            checkpoint_dir=self.config.recovery.checkpoint_dir,
        )

        # 6. 初始化摘要器
        summarizer = Summarizer()

        # 7. 初始化 Agent Loop (依赖 Plugin 系统)
        self._loop = AgentLoop(
            hooks=self._hooks,
            working_memory=self._working_memory,
            episodic_memory=self._episodic_memory,
            recovery=self._recovery,
            summarizer=summarizer,
            plugin_registry=self._plugin_registry,
            max_steps=self.config.max_steps,
        )

        # 8. 初始化 Skill 系统
        self._skill_registry = SkillRegistry()

        self._started = True
        await self._hooks.emit("on_harness_start", self)

        self._started = True
        await self._hooks.emit("on_harness_start", self)

    async def stop(self) -> None:
        """停止 Harness，清理资源。"""
        if not self._started:
            return
        await self._hooks.emit("on_harness_stop", self)
        if self._plugin_registry:
            await self._plugin_registry.stop_all()
        self._started = False

    async def run(
        self,
        task: str,
        session_id: str | None = None,
    ) -> SessionResult:
        """运行一个任务。

        Args:
            task: 用户任务描述
            session_id: 可选的 session ID (用于恢复中断的任务)

        Returns:
            SessionResult: 执行结果
        """
        if not self._started:
            await self.start()

        # 匹配 Skill，收集工具，注入系统提示
        selected_skill = self._skill_registry.select_skill(task)

        if selected_skill:
            # 为选中的 Skill 创建上下文并注入
            skill_context = SkillContext(
                task=task,
                plugin_registry=self._plugin_registry,
                tools=self._plugin_registry.collect_tools(),
            )
            # 注册 Skill 的 Hook
            skill_hooks = selected_skill.register_hooks()
            for event, handlers in skill_hooks.items():
                for handler in handlers:
                    self._hooks.register(event, handler, priority=HookPriority.SKILL)
        else:
            # 无匹配 Skill 时使用所有 Plugin 的工具
            tools = self._plugin_registry.collect_tools()
            self._loop.set_tools(tools)

        return await self._loop.execute(task, session_id=session_id)

    # ---- 注册快捷方法 ----

    def register_hook(self, event: str, fn, priority: int = 100) -> None:
        """注册一个 Hook。"""
        self.hooks.register(event, fn, priority)

    def register_plugin(self, plugin) -> None:
        """注册一个 Plugin 实例。"""
        self.plugins.register(plugin)

    def register_skill(self, skill) -> None:
        """注册一个 Skill。"""
        self.skills.register(skill)

    # ---- 内部方法 ----

    async def _init_plugins(self) -> None:
        """初始化 Plugin 系统。"""
        if self.config.plugins.builtin_enabled:
            # 注册内置 Plugin
            builtins = [FilePlugin(), ShellPlugin(), WebPlugin()]
            for plugin in builtins:
                self._plugin_registry.register(plugin)

            # 自动发现额外 Plugin
            if self.config.plugins.extra_paths:
                discovered = self._plugin_registry.discover(
                    *self.config.plugins.extra_paths
                )
                for plugin in discovered:
                    self._plugin_registry.register(plugin)

        # 加载、初始化、启动所有 Plugin
        await self._plugin_registry.load_all()
        await self._plugin_registry.init_all(self)
        await self._plugin_registry.start_all()

        # 注册 Plugin 的 Hook
        plugin_hooks = self._plugin_registry.collect_hooks()
        for event, handlers in plugin_hooks.items():
            for handler in handlers:
                self._hooks.register(event, handler, priority=HookPriority.PLUGIN)

    def _register_tool_exec_hook(self) -> None:
        """注册 Tool 执行 Hook — 将 Plugin 的 execute_tool 方法桥接到 Agent Loop。"""
        async def tool_exec_hook(ctx: HookContext) -> HookContext | None:
            step = ctx.data
            if not step or not step.action:
                return ctx
            if not step.action.tool_calls:
                return ctx

            # 为每个 tool_call 执行 Plugin 工具
            results = []
            for tc in step.action.tool_calls:
                # 在所有 Plugin 中查找能处理此工具的
                for plugin in self._plugin_registry._plugins.values():
                    if hasattr(plugin, 'execute_tool'):
                        result = await plugin.execute_tool(tc.name, tc.arguments)
                        results.append({
                            "tool_call_id": tc.tool_call_id,
                            "name": tc.name,
                            "result": result,
                        })
                        break
                else:
                    results.append({
                        "tool_call_id": tc.tool_call_id,
                        "name": tc.name,
                        "result": f"Error: No plugin found for tool '{tc.name}'",
                    })

            # 将结果写回 step
            if step.observation:
                step.observation.tool_results = results
                step.observation.content = (
                    f"Executed {len(results)} tool call(s)"
                )

            return ctx

        self._hooks.register(
            "on_after_action", tool_exec_hook, priority=HookPriority.SYSTEM
        )

    def _build_permissions(self) -> PermissionPolicy:
        """根据配置构建权限策略。"""
        perm = self.config.permission
        return PermissionPolicy(
            level=self.config.permission_level,
            read_paths=perm.get("read_paths", ["."]),
            write_paths=perm.get("write_paths", []),
            exec_commands=perm.get("exec_commands", []),
            network_hosts=perm.get("network_hosts", []),
            env_vars=perm.get("env_vars", []),
        )

    def is_running(self) -> bool:
        """检查 Harness 是否正在运行。"""
        return self._started
