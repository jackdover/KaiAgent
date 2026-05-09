"""边界情况测试 — 覆盖边缘场景。"""

from pathlib import Path

import pytest

from harness.core.hooks import HookRegistry, HookContext, HOOK_EVENTS, HookAbortError
from harness.core.permissions import PermissionPolicy, PermissionLevel, PermissionDenied
from harness.core.recovery import RecoveryManager
from harness.core.memory import SemanticMemory, WorkingMemory
from harness.core.sandbox import Sandbox
from harness import Harness


# ===== Hooks Edge Cases =====

class TestHooksEdgeCases:
    def test_register_invalid_event(self):
        """测试注册非法事件。"""
        hooks = HookRegistry()
        async def dummy(ctx: HookContext): pass
        with pytest.raises(ValueError, match="Unknown event"):
            hooks.register("nonexistent_event", dummy)

    def test_register_non_async(self):
        """测试注册非异步函数。"""
        hooks = HookRegistry()
        def sync_fn(ctx): pass
        with pytest.raises(TypeError):
            hooks.register("on_step_start", sync_fn)

    def test_unregister_nonexistent(self):
        """测试取消注册不存在的 Hook。"""
        hooks = HookRegistry()
        async def dummy(ctx: HookContext): pass
        hooks.unregister("on_step_start", dummy)  # 不应报错

    def test_abort_hook(self):
        """测试 ABORT 模式的 Hook。"""
        import asyncio
        from harness.core.hooks import HookMode
        hooks = HookRegistry()

        async def abort_hook(ctx: HookContext):
            ctx.abort = True
            ctx.abort_reason = "测试中止"
            return ctx

        hooks.register("on_before_action", abort_hook, mode=HookMode.ABORT)

        with pytest.raises(HookAbortError, match="测试中止"):
            asyncio.run(hooks.emit("on_before_action", "test"))


# ===== Permission Edge Cases =====

class TestPermissionEdgeCases:
    def test_none_level_denies_everything(self):
        """测试 NONE 级别拒绝所有操作。"""
        policy = PermissionPolicy(level=PermissionLevel.NONE)
        with pytest.raises(PermissionDenied):
            policy.check("FILE_READ", "/any/file")

    def test_read_only_denies_write(self):
        """测试 READ_ONLY 拒绝写操作。"""
        from harness.core.permissions import ResourceType
        policy = PermissionPolicy(
            level=PermissionLevel.READ_ONLY,
            read_paths=["/tmp"],
        )
        with pytest.raises(PermissionDenied, match="Read-only"):
            policy.check(ResourceType.FILE_WRITE, "/tmp/test.txt")

    def test_full_level_allows_everything(self):
        """测试 FULL 级别允许所有操作。"""
        policy = PermissionPolicy(level=PermissionLevel.FULL)
        policy.check("FILE_READ", "/any/path")  # 不应报错
        policy.check("FILE_WRITE", "/any/path")
        policy.check("EXEC_COMMAND", "rm -rf /")

    def test_sandbox_classmethod(self):
        """测试 sandbox 类方法创建策略。"""
        policy = PermissionPolicy.sandbox()
        assert policy.level == PermissionLevel.SANDBOX
        assert "." in policy.read_paths
        assert "python" in policy.exec_commands

    def test_read_only_classmethod(self):
        """测试 read_only 类方法创建策略。"""
        policy = PermissionPolicy.read_only()
        assert policy.level == PermissionLevel.READ_ONLY
        assert "cat" in policy.exec_commands

    def test_to_dict(self):
        """测试策略序列化。"""
        policy = PermissionPolicy.full()
        d = policy.to_dict()
        assert d["level"] == "FULL"


# ===== Recovery Edge Cases =====

class TestRecoveryEdgeCases:
    def test_list_checkpoints_empty(self):
        """测试空 checkpoint 目录。"""
        rm = RecoveryManager(checkpoint_dir="/tmp/nonexistent_checkpoints_xyz")
        assert rm.list_checkpoints() == []

    def test_clean_expired_nonexistent(self):
        """测试清理不存在的目录。"""
        rm = RecoveryManager(checkpoint_dir="/tmp/nonexistent_checkpoints_xyz")
        assert rm.clean_expired() == 0

    def test_load_nonexistent(self):
        """测试加载不存在的 checkpoint。"""
        import asyncio
        rm = RecoveryManager(checkpoint_dir="/tmp/nonexistent_checkpoints_xyz")
        result = asyncio.run(rm.load("nonexistent_session"))
        assert result is None

    def test_has_checkpoint_nonexistent(self):
        """测试检查不存在的 checkpoint。"""
        rm = RecoveryManager(checkpoint_dir="/tmp/nonexistent_checkpoints_xyz")
        assert not rm.has_checkpoint("nonexistent")

    def test_delete_nonexistent(self):
        """测试删除不存在的 checkpoint。"""
        rm = RecoveryManager(checkpoint_dir="/tmp/nonexistent_checkpoints_xyz")
        assert not rm.delete("nonexistent")


# ===== Semantic Memory Edge Cases =====

class TestSemanticMemory:
    @pytest.mark.asyncio
    async def test_empty_memory(self, tmp_path):
        """测试空语义记忆。"""
        sm = SemanticMemory(persist_dir=str(tmp_path / "semantic"))
        ctx = await sm.get_context()
        assert ctx == []

        results = await sm.search("anything")
        assert results == []

        stats = sm.get_stats()
        assert stats["count"] == 0

    @pytest.mark.asyncio
    async def test_add_and_search(self, tmp_path):
        """测试添加和搜索知识。"""
        sm = SemanticMemory(persist_dir=str(tmp_path / "semantic2"))
        await sm.add_knowledge(
            "The agent loop uses a state machine with 7 states: "
            "INIT, IDLE, THINKING, ACTING, OBSERVING, ERROR, DONE",
            tags=["architecture", "agent"],
        )
        await sm.add_knowledge(
            "Permissions have 4 levels: NONE, READ_ONLY, SANDBOX, FULL",
            tags=["security"],
        )

        # 搜索
        results = await sm.search("agent loop state machine")
        assert len(results) >= 1
        assert "state machine" in results[0].content

    @pytest.mark.asyncio
    async def test_clear(self, tmp_path):
        """测试清除语义记忆。"""
        sm = SemanticMemory(persist_dir=str(tmp_path / "semantic3"))
        await sm.add_knowledge("test knowledge")
        assert sm.count == 1
        await sm.clear()
        assert sm.count == 0


# ===== Sandbox Tests =====

@pytest.mark.asyncio
async def test_sandbox_create_and_cleanup():
    """测试沙箱创建和清理。"""
    async with Sandbox() as sandbox:
        work_dir = sandbox.work_dir
        assert work_dir.exists()
        # 创建测试文件
        test_file = work_dir / "test.txt"
        test_file.write_text("hello")
        assert test_file.exists()

    # 沙箱退出后目录应被清理
    assert not work_dir.exists()


@pytest.mark.asyncio
async def test_sandbox_path_resolution():
    """测试沙箱路径解析。"""
    async with Sandbox() as sandbox:
        resolved = sandbox.resolve_path("test.txt")
        assert str(resolved).startswith(str(sandbox.work_dir))

        # 路径逃逸应被阻止
        with pytest.raises(PermissionError):
            sandbox.resolve_path("../../etc/passwd")


@pytest.mark.asyncio
async def test_sandbox_copy(tmp_path):
    """测试沙箱文件复制。"""
    async with Sandbox() as sandbox:
        # 创建文件
        (sandbox.work_dir / "source.txt").write_text("data")
        # 复制出去
        dst = str(tmp_path / "copied.txt")
        sandbox.copy_out("source.txt", dst)
        assert Path(dst).read_text() == "data"


# ===== Harness Cleanup Tests =====

@pytest.mark.asyncio
async def test_harness_multiple_runs():
    """测试 Harness 多次运行。"""
    h = Harness()
    await h.start()

    for i in range(3):
        result = await h.run(f"task_{i}")
        assert result.status.name == "DONE"

    await h.stop()


@pytest.mark.asyncio
async def test_harness_start_twice():
    """测试重复启动。"""
    h = Harness()
    await h.start()
    await h.start()  # 第二次启动不应报错
    assert h.is_running()
    await h.stop()


@pytest.mark.asyncio
async def test_semantic_memory_with_harness(tmp_path):
    """测试语义记忆与 Harness 的集成。"""
    from harness.core.memory.semantic import SemanticMemory
    sm = SemanticMemory(persist_dir=str(tmp_path / "harness_sem"))
    await sm.add_knowledge(
        "Python is a programming language",
        tags=["python"],
    )
    results = await sm.search("python language")
    assert len(results) >= 1
