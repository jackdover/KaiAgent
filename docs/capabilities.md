# Dimension 2: 场景化能力 (Plugins + Skills)

Plugin 和 Skill 构成 Harness Agent 的场景化能力层。两者是分层关系，不是平级关系。

## Plugin vs Skill

| | Plugin | Skill |
|--|--------|-------|
| **视角** | 技术视角 | 业务视角 |
| **粒度** | 原子能力 (read_file, exec_command) | 场景组合 (代码审查, 部署上线) |
| **包含** | Tools + Hooks | Prompt 模板 + Tool 编排 + 规则配置 |
| **依赖** | 无 | 依赖一个或多个 Plugin |
| **生命周期** | 独立 (load→init→start→stop) | 由 Harness 按需激活 |

**关键原则**：Plugin 和 Skill 不直接通信。Skill 通过 Hook 注入 System Prompt，通过 PluginRegistry 获取 Tools，两者在 Agent Loop 中交汇。

## Plugin 系统

### Plugin 生命周期

```
discover → load(config) → init(harness) → start() → stop() → unload()
```

### 创建自定义 Plugin

```python
from harness.plugins import Plugin, PluginMetadata, CapabilityType
from harness.core.types import ToolDefinition

class MyPlugin(Plugin):
    metadata = PluginMetadata(
        name="my_plugin",
        version="0.1.0",
        description="My custom plugin",
        capabilities=[CapabilityType.TOOL],
    )

    async def load(self, config: dict):
        self.config = config

    async def init(self, harness):
        self.harness = harness

    async def start(self):
        pass

    async def stop(self):
        pass

    def get_tools(self):
        return [
            ToolDefinition(
                name="my_tool",
                description="My custom tool",
                parameters={
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"},
                    },
                    "required": ["input"],
                },
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict) -> str:
        if name == "my_tool":
            return f"Processed: {arguments['input']}"
        return f"Unknown tool: {name}"
```

### Plugin 注册

```python
# 手动注册
registry.register(MyPlugin())

# 自动发现 (扫描包内所有模块)
discovered = registry.discover("my_plugins_package")
for plugin in discovered:
    registry.register(plugin)

# 按能力类型查询
tools_plugins = registry.get_plugins_by_capability(CapabilityType.TOOL)
```

### 内置 Plugin

| Plugin | 工具 | 说明 |
|--------|------|------|
| **FilePlugin** | `read_file`, `write_file`, `list_files` | 文件系统操作 |
| **ShellPlugin** | `execute_command` | Shell 命令执行 |
| **WebPlugin** | `http_get`, `http_post` | HTTP 网络请求 |
| **LLMProviderPlugin** | — | LLM Provider 封装 (需外部注册 Provider) |

## Skill 系统

### Skill 的工作方式

Skill 不直接调用 Plugin，而是通过 4 个 Hook 切入 Agent 的执行流程：

1. **on_before_think** — 注入领域 System Prompt，指导 LLM 在特定场景下如何思考
2. **on_before_action** — 校验即将执行的动作是否安全/合规
3. **on_after_action** — 校验输出是否符合业务规则
4. **on_step_end** — 场景特定的后处理

### 创建自定义 Skill

```python
from harness.skills import Skill, SkillMetadata, SkillContext
from harness.core.types import ToolDefinition

class DeploySkill(Skill):
    metadata = SkillMetadata(
        name="deploy",
        description="部署代码到服务器",
        match_keywords=["deploy", "部署", "上线", "发布"],
        plugin_deps=["file", "shell", "git"],  # 语义声明，非强制绑定
    )

    async def get_system_prompt(self, context: SkillContext) -> str:
        return (
            "You are a deployment engineer. Follow these steps:\n"
            "1. Review the code changes\n"
            "2. Run tests\n"
            "3. Build the project\n"
            "4. Deploy to the target environment\n"
            "Always confirm the target environment before deploying."
        )

    async def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        # 从 PluginRegistry 收集所有工具
        if context.plugin_registry:
            return context.plugin_registry.collect_tools()
        return []

    async def on_before_action(self, ctx):
        """部署前校验目标环境安全。"""
        action = ctx.data
        if action and "rm -rf" in str(getattr(action, 'content', '')):
            ctx.abort = True
            ctx.abort_reason = "Dangerous command blocked in deploy context"
        return ctx
```

### Skill 匹配机制

Skill 通过关键词匹配自动激活。用户输入任务后，`SkillRegistry.select_skill()` 根据 `match_keywords` 选择最合适的 Skill：

```python
skill_reg = SkillRegistry()
skill_reg.register(CodeReviewSkill())
skill_reg.register(DeploySkill())

# "帮我 review 代码" → 匹配 CodeReviewSkill
# "部署到测试环境" → 匹配 DeploySkill
# "今天天气怎么样" → 无匹配，使用默认行为
```

### 自定义匹配逻辑

子类可以重写 `match()` 方法实现更复杂的匹配：

```python
class MySkill(Skill):
    def match(self, task: str) -> bool:
        # 自定义匹配逻辑
        return len(task) > 100  # 长文本任务自动匹配
```

## Plugin 和 Skill 的集成流程

```
用户: "审查代码质量"
    │
    ▼
Harness.run()
    │
    ├── skill_registry.select_skill("审查代码质量")
    │   └── → 匹配 CodeReviewSkill
    │
    ├── CodeReviewSkill.register_hooks()
    │   ├── on_before_think → 注入代码审查 prompt
    │   └── on_after_action → 校验输出格式
    │
    ├── CodeReviewSkill.get_tools(context)
    │   └── → 从 PluginRegistry 收集 FilePlugin、ShellPlugin 的工具
    │
    └── AgentLoop.set_tools(tools)
        └── → 将工具传给 LLM

Agent Loop 执行:
    THINK: 先读文件
    ACT: read_file("main.py")          ← FilePlugin 执行
    OBSERVE: 得到文件内容

    THINK: 分析代码问题
    ACT: 输出审查结果
    OBSERVE: 完成
```
