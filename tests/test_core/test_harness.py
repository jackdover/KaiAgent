"""Harness 功能测试。"""

import pytest

from harness import Harness
from harness.core.hooks import HookContext
from harness.core.types import AgentStatus


@pytest.fixture
async def harness():
    h = Harness()
    await h.start()
    yield h
    await h.stop()


@pytest.mark.asyncio
async def test_harness_start_stop():
    """测试 Harness 启动和停止。"""
    h = Harness()
    assert not h.is_running()

    await h.start()
    assert h.is_running()

    await h.stop()
    assert not h.is_running()


@pytest.mark.asyncio
async def test_harness_run_simple_task(harness):
    """测试运行一个简单任务 (无 LLM provider，使用文本模式)。"""
    result = await harness.run("Hello, what can you do?")
    assert result.status == AgentStatus.DONE
    assert result.session_id is not None


@pytest.mark.asyncio
async def test_hook_registration(harness):
    """测试 Hook 注册和事件发射。"""
    events_triggered = []

    async def test_hook(ctx: HookContext):
        events_triggered.append(ctx.event)

    harness.register_hook("on_session_start", test_hook)
    harness.register_hook("on_session_end", test_hook)

    await harness.run("test task")

    assert "on_session_start" in events_triggered
    assert "on_session_end" in events_triggered


@pytest.mark.asyncio
async def test_max_steps():
    """测试 max_steps 限制。"""
    h = Harness()
    h.config.max_steps = 3
    await h.start()

    result = await h.run("test task")
    assert len(result.steps) <= 3

    await h.stop()
