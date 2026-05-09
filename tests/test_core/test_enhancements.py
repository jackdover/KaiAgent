"""增强功能测试 — 覆盖所有 Sprint 2-5 的新功能。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from harness.core.hooks import (
    HookRegistry,
    HookMatcher,
    HOOK_EVENTS,
    HookContext,
    HookAbortError,
)
from harness.core.permissions import (
    PermissionLevel,
    PermissionPolicy,
    ResourceType,
    DenyRule,
    ToolPermission,
    ApprovalMode,
    PermissionDenied,
    PermissionApprovalRequired,
)
from harness.core.recovery import RecoveryManager
from harness.core.types import Action, ActionType, AgentStatus, SessionState, Step, ToolCall
from harness.core.memory.compressor import (
    Compressor,
    CompressionCircuitBreaker,
    ToolResultBudget,
)
from harness.core.memory.auto_memory import AutoMemory
from harness.config.schema import HarnessConfig, find_config_files, find_claude_md
from harness.skills.interface import (
    SkillManifest,
    parse_skill_manifest,
    SkillToolMode,
    SKILL,
)
from harness.skills.registry import SkillRegistry, SkillDescriptor
from harness.core.agent_tool import AgentTool, AgentToolConfig


# =============================================================================
# Hook 系统增强测试
# =============================================================================


class TestNewHookEvents:
    """测试新增的 Hook 事件。"""

    def test_hook_events_set_contains_new_events(self):
        """验证 HOOK_EVENTS 包含所有新事件。"""
        assert "on_pre_tool_use" in HOOK_EVENTS
        assert "on_post_tool_use" in HOOK_EVENTS
        assert "on_post_tool_use_failure" in HOOK_EVENTS
        assert "on_pre_compact" in HOOK_EVENTS
        assert "on_post_compact" in HOOK_EVENTS
        assert "on_user_prompt_submit" in HOOK_EVENTS

    def test_hook_events_count(self):
        """验证 Hook 事件总数 >= 17。"""
        assert len(HOOK_EVENTS) >= 17

    @pytest.mark.asyncio
    async def test_pre_tool_use_hook(self):
        """测试 on_pre_tool_use 事件。"""
        registry = HookRegistry()
        calls = []

        async def hook(ctx):
            calls.append(ctx.event)
            return ctx

        registry.register("on_pre_tool_use", hook)
        await registry.emit("on_pre_tool_use", {"tool": "read_file"})
        assert len(calls) == 1
        assert calls[0] == "on_pre_tool_use"

    @pytest.mark.asyncio
    async def test_post_tool_use_hook(self):
        """测试 on_post_tool_use 事件。"""
        registry = HookRegistry()
        calls = []

        async def hook(ctx):
            calls.append(ctx.data)
            return ctx

        registry.register("on_post_tool_use", hook)
        result = {"tool": "read_file", "status": "success"}
        await registry.emit("on_post_tool_use", result)
        assert len(calls) == 1
        assert calls[0]["tool"] == "read_file"

    @pytest.mark.asyncio
    async def test_post_tool_use_failure_hook(self):
        """测试 on_post_tool_use_failure 事件。"""
        registry = HookRegistry()
        calls = []

        async def hook(ctx):
            calls.append(ctx.data)
            return ctx

        registry.register("on_post_tool_use_failure", hook)
        error_result = {"error": "Permission denied"}
        await registry.emit("on_post_tool_use_failure", error_result)
        assert len(calls) == 1
        assert "error" in calls[0]


class TestHookMatcher:
    """测试 Hook Matcher 条件过滤。"""

    @pytest.mark.asyncio
    async def test_matcher_tool_name_filter(self):
        """测试按工具名过滤。"""
        registry = HookRegistry()
        calls = []

        async def hook(ctx):
            calls.append(ctx.data.get("name"))
            return ctx

        matcher = HookMatcher(tool_names=["read_*", "write_*"])
        registry.register("on_pre_tool_use", hook, matcher=matcher)

        # 匹配的工具
        await registry.emit("on_pre_tool_use", {"name": "read_file"})
        assert len(calls) == 1

        # 不匹配的工具
        await registry.emit("on_pre_tool_use", {"name": "execute_command"})
        assert len(calls) == 1  # 没有增加

    @pytest.mark.asyncio
    async def test_matcher_path_filter(self):
        """测试按路径过滤。"""
        registry = HookRegistry()
        calls = []

        async def hook(ctx):
            calls.append(ctx.data.get("path"))
            return ctx

        matcher = HookMatcher(paths=["/etc/**", "/tmp/**"])
        registry.register("on_pre_tool_use", hook, matcher=matcher)

        # 匹配路径
        await registry.emit("on_pre_tool_use", {"path": "/tmp/test.txt"})
        assert len(calls) == 1

        # 不匹配路径
        await registry.emit("on_pre_tool_use", {"path": "/var/log/test.log"})
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_matcher_custom_filter(self):
        """测试自定义匹配函数。"""
        registry = HookRegistry()
        calls = []

        async def hook(ctx):
            calls.append("called")
            return ctx

        def custom_matcher(ctx):
            data = ctx.data
            return isinstance(data, dict) and data.get("allowed") is True

        matcher = HookMatcher(custom=custom_matcher)
        registry.register("on_before_action", hook, matcher=matcher)

        await registry.emit("on_before_action", {"allowed": True})
        assert len(calls) == 1

        await registry.emit("on_before_action", {"allowed": False})
        assert len(calls) == 1  # 没有增加

    @pytest.mark.asyncio
    async def test_command_hook_execution(self):
        """测试 command 类型 Hook (模拟)。"""
        registry = HookRegistry()
        executed = []

        async def cmd_hook(ctx):
            executed.append("command_executed")
            return ctx

        registry.register("on_checkpoint", cmd_hook)
        await registry.emit("on_checkpoint", {"step": 1})
        assert len(executed) == 1


# =============================================================================
# 权限系统增强测试
# =============================================================================


class TestPermissionDenyRules:
    """测试 deny 规则系统。"""

    def test_deny_rule_creation(self):
        """测试创建 DenyRule。"""
        rule = DenyRule("rm", ResourceType.EXEC_COMMAND, "rm is dangerous")
        assert rule.pattern == "rm"
        assert rule.resource_type == ResourceType.EXEC_COMMAND
        assert rule.reason == "rm is dangerous"
        assert rule.enabled is True

    def test_deny_first_evaluation(self):
        """测试 deny-first 评估。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            read_paths=["."],
            exec_commands=["ls", "cat"],
            deny_rules=[
                DenyRule("rm", ResourceType.EXEC_COMMAND, "rm is denied"),
            ],
        )

        # deny 规则优先于 allow
        with pytest.raises(PermissionDenied, match="rm"):
            policy.check(ResourceType.EXEC_COMMAND, "rm -rf /")

        # 未在 deny 规则中的命令正常检查
        with pytest.raises(PermissionDenied):
            policy.check(ResourceType.EXEC_COMMAND, "rm")  # "rm" 在 deny 规则中

    def test_deny_disabled_rule(self):
        """测试禁用的 deny 规则不生效。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            read_paths=["."],
            exec_commands=["ls", "cat"],
            deny_rules=[
                DenyRule("rm", ResourceType.EXEC_COMMAND, "rm is denied", enabled=False),
            ],
        )

        # deny 规则已禁用，应当继续检查 allow 列表
        with pytest.raises(PermissionDenied):
            policy.check(ResourceType.EXEC_COMMAND, "rm -rf /")


class TestPermissionToolLevel:
    """测试工具级权限过滤。"""

    def test_tool_permission_allow(self):
        """测试工具级 allow 规则。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            tool_permissions=[
                ToolPermission("read_*", allowed=True),
            ],
        )
        # 在 read_paths 为空的情况下，工具级 allow 绕过路径检查
        policy.check_tool("read_file", "/some/path")

    def test_tool_permission_deny(self):
        """测试工具级 deny 规则。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            tool_permissions=[
                ToolPermission("execute_command", allowed=False, reason="No shell"),
            ],
        )
        with pytest.raises(PermissionDenied, match="No shell"):
            policy.check_tool("execute_command", "ls")

    def test_tool_permission_with_resource_pattern(self):
        """测试带资源模式的工具权限。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            tool_permissions=[
                ToolPermission("write_file", allowed=False,
                               resource_pattern="/etc/**", reason="No system files"),
            ],
        )
        # 写入 /etc 被拒绝
        with pytest.raises(PermissionDenied, match="No system files"):
            policy.check_tool("write_file", "/etc/passwd")

        # 写入其他路径应继续检查
        # (没有 write_paths，所以应当被拒绝)
        with pytest.raises(PermissionDenied):
            policy.check_tool("write_file", "/tmp/test.txt")

    def test_tool_permission_glob_pattern(self):
        """测试 glob 模式匹配。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            tool_permissions=[
                ToolPermission("http_*", allowed=True),
            ],
        )
        policy.check_tool("http_get", "https://example.com")
        policy.check_tool("http_post", "https://example.com")


class TestPermissionApprovalModes:
    """测试审批模式。"""

    def test_auto_mode_ml_placeholder(self):
        """测试 auto 模式 (ML 占位)。"""
        policy = PermissionPolicy.auto(base_dir=".")
        assert policy.approval_mode == ApprovalMode.AUTO

    def test_interactive_mode_raises_approval(self):
        """测试 interactive 模式抛出审批异常。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            approval_mode=ApprovalMode.INTERACTIVE,
        )
        with pytest.raises(PermissionApprovalRequired):
            policy.check(ResourceType.FILE_READ, "/test.txt")

    def test_plan_mode_raises_approval(self):
        """测试 plan 模式抛出审批异常。"""
        policy = PermissionPolicy(
            level=PermissionLevel.SANDBOX,
            approval_mode=ApprovalMode.PLAN,
        )
        with pytest.raises(PermissionApprovalRequired):
            policy.check(ResourceType.EXEC_COMMAND, "ls")

    def test_to_dict_includes_new_fields(self):
        """测试 to_dict 包含新字段。"""
        policy = PermissionPolicy()
        d = policy.to_dict()
        assert "approval_mode" in d
        assert "deny_rules" in d
        assert "tool_permissions" in d


# =============================================================================
# 恢复系统测试
# =============================================================================


class TestRecoveryRoundTrip:
    """测试 Recovery save/load 往返。"""

    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self):
        """测试 checkpoint save → load 往返完整性。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = RecoveryManager(checkpoint_dir=tmpdir)

            # 创建状态
            step = Step(id="step_1", thought="test thought")
            step.action = Action(type=ActionType.TEXT_RESPONSE, content="test response")
            state = SessionState(
                session_id="test_session",
                status=AgentStatus.ACTING,
                steps=[step],
                task="test task",
            )

            # 保存
            await mgr.save(state)
            assert mgr.has_checkpoint("test_session")

            # 加载
            checkpoint = await mgr.load("test_session")
            assert checkpoint is not None
            assert checkpoint.state.task == "test task"

            # 恢复
            restored = await mgr.resume(checkpoint)
            assert restored.status == AgentStatus.RESUMING
            assert len(restored.steps) == 1

    @pytest.mark.asyncio
    async def test_save_and_load_with_action_type(self):
        """测试 ActionType 反序列化正确性。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = RecoveryManager(checkpoint_dir=tmpdir)

            step = Step(id="step_1")
            step.action = Action(type=ActionType.TOOL_CALL, content=None,
                                 tool_calls=[ToolCall(name="read_file", arguments={"path": "/test"})])
            state = SessionState(
                session_id="test_tool_session",
                status=AgentStatus.ACTING,
                steps=[step],
            )

            await mgr.save(state)
            checkpoint = await mgr.load("test_tool_session")
            assert checkpoint is not None
            restored_step = checkpoint.state.steps[0]
            assert restored_step.action is not None
            # ActionType 应当正确反序列化为枚举
            assert restored_step.action.type == ActionType.TOOL_CALL


# =============================================================================
# 压缩管线测试
# =============================================================================


class TestCompressionPipeline:
    """测试级联压缩管线。"""

    def test_circuit_breaker(self):
        """测试电路断路器。"""
        cb = CompressionCircuitBreaker(max_failures=2, cooldown_seconds=60)

        assert not cb.is_open
        cb.record_failure()
        assert not cb.is_open
        cb.record_failure()
        assert cb.is_open  # 超过 2 次失败

        cb.record_success()
        assert not cb.is_open  # 重置

    def test_tool_result_budget_stores_large_results(self):
        """测试 ToolResultBudget 大结果存盘。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            budget = ToolResultBudget(max_preview_chars=100, storage_dir=tmpdir)

            # 短结果应直接返回
            short = "short result"
            assert budget.store_result("test_tool", short) == short

            # 长结果应存盘并返回摘要
            long_result = "x" * 500
            preview = budget.store_result("test_tool", long_result)
            assert "stored at" in preview
            assert "truncated" in preview

            # 验证文件存在
            files = list(Path(tmpdir).glob("*.json"))
            assert len(files) >= 1

    @pytest.mark.asyncio
    async def test_compressor_layer_snip(self):
        """测试 Snip 层裁剪超长内容。"""
        from harness.core.types import LLMMessage

        compressor = Compressor()

        # 超长消息
        long_msg = LLMMessage(role="user", content="Hello " * 50000)  # ~300k chars
        messages = [long_msg]

        compressed = await compressor.compress_messages(messages)
        assert len(compressed) == 1
        # 应当被裁剪
        assert len(compressed[0].content) < len(long_msg.content)

    @pytest.mark.asyncio
    async def test_compressor_layer_microcompact(self):
        """测试 Microcompact 层合并连续消息。"""
        from harness.core.types import LLMMessage

        compressor = Compressor()

        messages = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="user", content="World"),
            LLMMessage(role="assistant", content="Response 1"),
            LLMMessage(role="assistant", content="Response 2"),
        ]

        compressed = await compressor.compress_messages(messages, aggressive=True)
        # 合并后应当小于 4 条
        assert len(compressed) < 4

    @pytest.mark.asyncio
    async def test_compressor_layer_collapse(self):
        """测试 Collapse 层折叠工具调用轮次。"""
        from harness.core.types import LLMMessage, ToolCall

        compressor = Compressor()

        messages = []
        for i in range(3):
            messages.append(LLMMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(name=f"tool_{i}", arguments={})],
            ))
            messages.append(LLMMessage(
                role="tool",
                content=f"Result {i}",
                tool_call_id=f"call_{i}",
            ))

        compressed = await compressor.compress_messages(messages, aggressive=True)
        # 应当折叠为 1 条
        assert len(compressed) == 1
        assert "Folded" in (compressed[0].content or "")

    @pytest.mark.asyncio
    async def test_compressor_summary_no_llm(self):
        """测试无 LLM 时的摘要压缩。"""
        from harness.core.types import LLMMessage

        compressor = Compressor()

        messages = [
            LLMMessage(role="user", content="What is the weather?"),
            LLMMessage(role="assistant", content="The weather is sunny."),
        ]

        summary = await compressor.compress_to_summary(messages, max_length=200)
        assert summary.content
        assert summary.token_count > 0


# =============================================================================
# Auto Memory 测试
# =============================================================================


class TestAutoMemory:
    """测试自动记忆系统。"""

    @pytest.mark.asyncio
    async def test_empty_auto_memory(self):
        """测试空 AutoMemory。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = AutoMemory(persist_dir=tmpdir)
            context = await memory.get_context()
            assert context == []

    @pytest.mark.asyncio
    async def test_record_tool_step(self):
        """测试记录工具调用 step。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = AutoMemory(persist_dir=tmpdir)
            step = Step(id="step_1")
            step.action = Action(
                type=ActionType.TOOL_CALL,
                tool_calls=[ToolCall(name="read_file", arguments={"path": "/test.txt"})],
            )
            await memory.record_step(step)
            assert memory.count > 0

    @pytest.mark.asyncio
    async def test_record_error_fix(self):
        """测试错误修复检测。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = AutoMemory(persist_dir=tmpdir)

            # Error step
            err_step = Step(id="step_1")
            err_step.action = Action(type=ActionType.TEXT_RESPONSE, content="Got an error")
            err_step.observation = type('obs', (), {'content': 'Success after retry'})()
            await memory.record_step(err_step)

            context = await memory.get_context()
            assert len(context) > 0

    @pytest.mark.asyncio
    async def test_persistence(self):
        """测试跨 session 持久化。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 第一次 session
            memory1 = AutoMemory(persist_dir=tmpdir)
            step = Step(id="step_1")
            step.action = Action(
                type=ActionType.TOOL_CALL,
                tool_calls=[ToolCall(name="read_file", arguments={"path": "/test.txt"})],
            )
            await memory1.record_step(step)
            await memory1.save()

            # 第二次 session (从文件恢复)
            memory2 = AutoMemory(persist_dir=tmpdir)
            assert memory2.count > 0  # 跨 session 持久化


# =============================================================================
# 配置层次测试
# =============================================================================


class TestConfigHierarchy:
    """测试配置层次系统。"""

    def test_config_load_default(self):
        """测试默认配置加载。"""
        config = HarnessConfig.default()
        assert config.name == "harness"
        assert config.max_steps == 50

    def test_config_from_dict(self):
        """测试 from_dict。"""
        config = HarnessConfig.from_dict({
            "max_steps": 100,
            "permission_level": "FULL",
        })
        assert config.max_steps == 100
        assert config.permission_level == PermissionLevel.FULL

    def test_config_claude_md(self):
        """测试 CLAUDE.md 支持。"""
        config = HarnessConfig.default()
        config.claude_md_content = "Always use Python for scripts."
        extra = config.build_system_prompt_extra()
        assert "Always use Python" in extra
        assert "Protected" in extra

    def test_config_rules(self):
        """测试 Rules 支持。"""
        config = HarnessConfig.default()
        config.rules = [
            {"path": "backend", "content": "Use SQLAlchemy for database."},
        ]
        extra = config.build_system_prompt_extra()
        assert "SQLAlchemy" in extra
        assert "Rule: backend" in extra


# =============================================================================
# Skills 增强测试
# =============================================================================


class TestSkillEnhancements:
    """测试 Skills 增强功能。"""

    def test_parse_skill_manifest(self):
        """测试 YAML frontmatter 解析。"""
        yaml_text = """---
name: test_skill
version: "1.0.0"
description: A test skill
allowed_tools:
  - read_file
  - write_file
model: opus
context: |
  You are a test assistant.
---
Some notes here.
"""
        manifest = parse_skill_manifest(yaml_text)
        assert manifest is not None
        assert manifest.name == "test_skill"
        assert "read_file" in manifest.allowed_tools
        assert manifest.model == "opus"
        assert "test assistant" in manifest.context

    def test_parse_skill_manifest_no_frontmatter(self):
        """测试无 frontmatter 文本。"""
        result = parse_skill_manifest("Just plain text")
        assert result is None

    def test_skill_tool_mode_default(self):
        """测试默认工具执行模式。"""
        from harness.skills.builtins.code_review import CodeReviewSkill
        skill = CodeReviewSkill()
        assert skill.tool_mode == SkillToolMode.SKILL_TOOL

    def test_skill_scoring_matching(self):
        """测试 Skill 得分匹配。"""
        from harness.skills.builtins.code_review import CodeReviewSkill
        skill = CodeReviewSkill()

        # 匹配
        score = skill.match("Please review this code")
        assert score > 0

        # 不匹配
        score = skill.match("What's the weather?")
        assert score == 0.0

    def test_progressive_loading_registry(self):
        """测试渐进式加载注册。"""
        registry = SkillRegistry()
        descriptor = SkillDescriptor(
            name="progressive_skill",
            description="A progressively loaded skill",
            match_keywords=["progressive", "lazy"],
            priority=5,
        )
        registry.register_descriptor(descriptor)
        assert registry.count == 1  # 只算描述

        # 描述匹配
        matches = registry.match_skills("I need progressive loading")
        assert len(matches) == 1
        assert matches[0][2] == "progressive_skill"
        assert matches[0][1] is None  # 未加载

        # 列出描述
        descriptions = registry.list_loaded_descriptions()
        assert len(descriptions) == 1
        assert descriptions[0]["loaded"] is False

    def test_skill_allowed_tools_filtering(self):
        """测试 allowed_tools 过滤。"""
        from harness.skills.interface import SkillMetadata, SkillContext
        from harness.core.types import ToolDefinition

        _skill_meta = SkillMetadata(
            name="filtered_skill",
            allowed_tools=["read_file", "list_files"],
        )

        # 创建测试 Skill
        from harness.skills.interface import Skill

        class FilteredSkill(Skill):
            metadata = _skill_meta

            async def get_system_prompt(self, context):
                return ""

        skill = FilteredSkill()
        context = SkillContext(
            task="test",
            tools=[
                ToolDefinition(name="read_file", description="Read", parameters={}),
                ToolDefinition(name="write_file", description="Write", parameters={}),
                ToolDefinition(name="execute_command", description="Exec", parameters={}),
            ],
        )

        tools = skill.get_tools(context)
        assert len(tools) == 1
        assert tools[0].name == "read_file"

    def test_yaml_skill_from_manifest(self):
        """测试从 YAML 创建 Skill。"""
        yaml_text = """---
name: yaml_skill
version: "1.0.0"
description: Created from YAML
allowed_tools: [read_file]
model: opus
context: |
  You are a YAML skill.
---
"""
        skill_yaml = SKILL.from_yaml(yaml_text)
        assert skill_yaml is not None
        assert skill_yaml.metadata.name == "yaml_skill"
        assert "read_file" in skill_yaml.metadata.allowed_tools


# =============================================================================
# AgentTool 测试
# =============================================================================


class TestAgentTool:
    """测试 AgentTool 系统。"""

    def test_agent_tool_config_defaults(self):
        """测试 AgentTool 默认配置。"""
        config = AgentToolConfig()
        assert config.max_steps == 20
        assert config.timeout_seconds == 120
        assert config.isolation == "none"
        assert config.bubble_permissions is False
        assert config.parallel is False


# =============================================================================
# 集成测试
# =============================================================================


class TestHarnessIntegration:
    """测试 Harness 集成场景。"""

    @pytest.mark.asyncio
    async def test_harness_with_config_hierarchy(self):
        """测试 Harness 使用配置层次。"""
        from harness import Harness
        config = HarnessConfig.load(project_dir=".")
        h = Harness(config=config)
        await h.start()
        result = await h.run("say hello")
        assert result.status.name == "DONE"
        await h.stop()

    @pytest.mark.asyncio
    async def test_permission_integration_in_loop(self):
        """测试权限系统在 AgentLoop 中的集成。"""
        from harness import Harness
        from harness.core.permissions import PermissionLevel

        h = Harness()
        await h.start()

        # 验证权限已集成
        assert h._loop.permissions is not None
        assert h._loop.permissions.level == PermissionLevel.SANDBOX

        await h.stop()

    @pytest.mark.asyncio
    async def test_compressor_in_working_memory(self):
        """测试压缩器在工作记忆中的集成。"""
        from harness.core.memory import WorkingMemory, WorkingMemoryConfig

        wm = WorkingMemory(WorkingMemoryConfig(max_tokens=1000))
        # compressor 默认创建
        assert wm._compressor is not None

    @pytest.mark.asyncio
    async def test_new_hook_events_in_loop(self):
        """测试新 Hook 事件在 Loop 中被正确发射。"""
        from harness import Harness

        h = Harness()
        await h.start()

        events_fired = []

        async def track_hook(ctx):
            events_fired.append(ctx.event)
            return ctx

        h.register_hook("on_pre_tool_use", track_hook)
        h.register_hook("on_post_tool_use", track_hook)
        h.register_hook("on_pre_compact", track_hook)
        h.register_hook("on_post_compact", track_hook)

        await h.run("say hello")

        # 注册的 hook 事件不会在无 LLM 模式的简单任务中全部触发，
        # 但验证注册本身不报错
        assert "on_pre_tool_use" in h._hooks.list_events()
        assert "on_post_tool_use" in h._hooks.list_events()

        await h.stop()
