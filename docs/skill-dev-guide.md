# Skill 开发指南

## Skill 是什么

Skill 是面向业务场景的**组合能力**。一个 Skill = Prompt 模板 + Tool 编排 + 规则配置。

常见 Skill：代码审查、部署上线、数据分析、单元测试生成、文档编写、Bug 修复等。

## Skill 的工作方式

Skill **不直接调用 Plugin**，而是通过 4 个 Hook 切入 Agent 的执行流程：

```
Skill 注册
    │
    ├── on_before_think  → 注入领域 System Prompt
    │                       告诉 LLM "在这个场景下你应该怎么思考"
    │
    ├── on_before_action → 校验动作安全
    │                       阻止危险操作
    │
    ├── on_after_action  → 校验输出质量
    │                       确保输出符合业务规则
    │
    └── on_step_end      → 场景后处理
                            汇总结果、触发下一步
```

## 创建 Skill

### 最小 Skill

```python
from harness.skills import Skill, SkillMetadata, SkillContext
from harness.core.types import ToolDefinition

class HelloSkill(Skill):
    metadata = SkillMetadata(
        name="hello",
        description="Say hello in a specific way",
        match_keywords=["hello", "hi", "打招呼"],
    )

    async def get_system_prompt(self, context: SkillContext) -> str:
        return "You are a friendly assistant. Always greet users warmly."

    async def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        # 通过 PluginRegistry 获取工具
        if context.plugin_registry:
            return context.plugin_registry.collect_tools()
        return []
```

### 完整 Skill

```python
from harness.skills import Skill, SkillMetadata, SkillContext
from harness.core.hooks import HookContext
from harness.core.types import ToolDefinition

class TestGenerationSkill(Skill):
    metadata = SkillMetadata(
        name="test_generation",
        version="0.1.0",
        description="为代码自动生成单元测试",
        match_keywords=["test", "测试", "unit test", "单元测试", "UT"],
        plugin_deps=["file", "shell"],
    )

    # ----- Hook 1: 注入 System Prompt -----

    async def get_system_prompt(self, context: SkillContext) -> str:
        return (
            "You are a senior QA engineer specializing in unit testing.\n\n"
            "Process:\n"
            "1. Read the source file to understand the code\n"
            "2. Identify testable units (functions, methods)\n"
            "3. Generate comprehensive test cases including:\n"
            "   - Normal cases\n"
            "   - Edge cases\n"
            "   - Error cases\n"
            "4. Write the test file\n"
            "5. Run the tests to verify\n\n"
            "Test coverage guidelines:\n"
            "- Aim for 80%+ line coverage\n"
            "- Test both success and failure paths\n"
            "- Use descriptive test names\n"
            "- Mock external dependencies"
        )

    # ----- Hook 2: 提供 Tools -----

    async def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        if context.plugin_registry:
            return context.plugin_registry.collect_tools()
        return []

    # ----- Hook 3: 自定义 Hook 方法 -----

    async def on_before_action(self, ctx: HookContext) -> HookContext | None:
        """阻止在测试生成场景中删除文件。"""
        action = ctx.data
        if hasattr(action, 'content') and action.content:
            if "rm" in str(action.content):
                ctx.abort = True
                ctx.abort_reason = (
                    "Deleting files is not allowed in test generation mode"
                )
        return ctx

    async def on_after_action(self, ctx: HookContext) -> HookContext | None:
        """校验测试输出格式。"""
        observation = ctx.data
        if hasattr(observation, 'content') and observation.content:
            content = str(observation.content)
            # 检查是否包含测试关键字
            test_keywords = ["test_", "def test", "import pytest", "assert"]
            if "test" in content and not any(kw in content.lower() for kw in test_keywords):
                ctx.set_modified("warning", "Output may not contain valid tests")
        return ctx
```

## Skill 匹配

### 关键词匹配 (默认)

`match_keywords` 列表中的关键词，命中任意一个即匹配：

```python
class MySkill(Skill):
    metadata = SkillMetadata(
        name="deploy",
        match_keywords=["deploy", "部署", "上线", "发布", "release"],
    )
```

匹配逻辑：`task.lower()` 中包含任一关键词（不区分大小写）。

### 自定义匹配 (重写 match)

```python
class AdvancedSkill(Skill):
    def match(self, task: str) -> bool:
        """自定义匹配逻辑。"""
        # 可基于长度、内容模式、正则等
        if "#skill:deploy" in task:
            return True
        if task.count(" ") > 50:  # 长文本
            return True
        return False
```

## Skill 与 Plugin 的关系

```
Skill 定义了什么场景下做什么
    │
    ├── match_keywords → 什么任务触发
    ├── get_system_prompt → 如何思考
    └── get_tools → 用什么工具
           │
           ▼
Plugin 提供了具体怎么做
    │
    ├── get_tools → 工具定义 (名称、参数、描述)
    └── execute_tool → 工具执行逻辑
```

**关键原则**：
- Skill 知道"要审查代码"，但不知道"怎么读文件"
- Plugin 知道"怎么读文件"，但不知道"读文件是为了审查代码"
- 两者通过 Hook 和 ToolDefinition 松耦合通信

## 内置 Skill 示例

### CodeReviewSkill

```python
class CodeReviewSkill(Skill):
    metadata = SkillMetadata(
        name="code_review",
        description="审查代码质量，发现潜在问题",
        match_keywords=["review", "审查", "code review", "代码审查"],
        plugin_deps=["file", "shell"],
    )

    async def get_system_prompt(self, context):
        return (
            "You are a senior code reviewer. ..."
            # 注入代码审查专家提示
        )
```

## 最佳实践

1. **Prompt 即代码**：System Prompt 是 Skill 的核心，要像对待代码一样对待它
2. **明确匹配范围**：匹配关键词要精确，避免误触（"测试"可能命中很多场景）
3. **按需暴露 Tool**：一个做"代码审查"的 Skill 不需要暴露"写文件"的 Tool
4. **轻量校验**：`on_before_action` 做安全检查，`on_after_action` 做输出校验，不要做重逻辑
5. **声明依赖**：`plugin_deps` 声明依赖哪些 Plugin，方便部署时检查环境和依赖完整性
