"""Phase 2 测试: Plugin 系统 + Skill 系统 + 端到端集成。"""

import pytest

from harness.plugins import PluginRegistry
from harness.plugins.builtins.file import FilePlugin
from harness.plugins.builtins.shell import ShellPlugin
from harness.skills import SkillRegistry
from harness.skills.builtins.code_review import CodeReviewSkill
from harness import Harness


@pytest.mark.asyncio
async def test_plugin_registry():
    """测试 Plugin 注册和工具收集。"""
    registry = PluginRegistry()

    file_plugin = FilePlugin()
    shell_plugin = ShellPlugin()

    registry.register(file_plugin)
    registry.register(shell_plugin)

    assert registry.count == 2

    tools = registry.collect_tools()
    tool_names = [t.name for t in tools]
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "execute_command" in tool_names


@pytest.mark.asyncio
async def test_file_plugin_execute_tool(tmp_path):
    """测试 FilePlugin 的工具执行。"""
    plugin = FilePlugin()
    await plugin.load({"workdir": str(tmp_path)})
    await plugin.init(None)
    await plugin.start()

    # Test write_file
    result = await plugin.execute_tool("write_file", {
        "path": "test.txt",
        "content": "Hello, Harness!",
    })
    assert "Successfully wrote" in result

    # Test read_file
    result = await plugin.execute_tool("read_file", {"path": "test.txt"})
    assert "Hello, Harness!" in result

    # Test list_files
    result = await plugin.execute_tool("list_files", {
        "path": ".",
        "pattern": "*.txt",
    })
    assert "test.txt" in result


@pytest.mark.asyncio
async def test_skill_registration_and_matching():
    """测试 Skill 注册和关键词匹配。"""
    registry = SkillRegistry()

    skill = CodeReviewSkill()
    registry.register(skill)
    assert registry.count == 1

    # 匹配关键词
    matched = registry.match_skills("请帮我 review 这段代码")
    assert len(matched) == 1
    score, skill, name = matched[0]
    assert name == "code_review"  # tuple format: (score, skill|None, name)

    # 不匹配
    matched = registry.match_skills("今天天气怎么样")
    assert len(matched) == 0

    # select_skill 测试
    selected = registry.select_skill("帮我 review 代码")
    assert selected is not None
    assert selected.metadata.name == "code_review"

    selected = registry.select_skill("帮我写一首诗")
    assert selected is None


@pytest.mark.asyncio
async def test_harness_skill_integration():
    """测试 Harness 与 Skill 的集成。"""
    h = Harness()
    await h.start()

    # 注册 Skill
    skill = CodeReviewSkill()
    h.register_skill(skill)
    assert h.skills.count == 1

    # 运行匹配 Skill 的任务 (无 LLM provider, 走文本模式)
    result = await h.run("帮我 review 一下代码")
    assert result.status.name == "DONE"

    # 运行不匹配的任务
    result = await h.run("天气怎么样")
    assert result.status.name == "DONE"

    await h.stop()


@pytest.mark.asyncio
async def test_harness_plugin_tools_injected():
    """测试 Plugin 工具被正确注入到 Loop。"""
    h = Harness()
    await h.start()

    # 验证 Loop 有 PluginRegistry 引用
    assert h._loop.plugin_registry is not None

    # 验证工具已收集
    tools = h.plugins.collect_tools()
    assert len(tools) >= 3  # file + shell + web

    await h.stop()
