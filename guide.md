# Harness — 通用 Agent 运行时框架

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-103%20passed-brightgreen.svg)](tests/)

**Harness** 是一个通用的 Agent 运行时框架，为智能体提供标准化的运行、扩展和进化能力。不绑定任何特定 LLM 或场景，提供一套通用的骨架，让开发者专注于构建智能体的业务能力。

---

## 目录

- [架构概览](#架构概览)
- [快速开始](#快速开始)
- [核心运行时](#核心运行时)
  - [Agent Loop](#agent-loop)
  - [权限系统](#权限系统)
  - [Hook 系统](#hook-系统)
  - [记忆系统](#记忆系统)
  - [中断恢复](#中断恢复)
- [能力层](#能力层)
  - [Plugin 插件](#plugin-插件)
  - [Skill 技能](#skill-技能)
- [高级功能](#高级功能)
  - [配置层次](#配置层次)
  - [CLAUDE.md](#claudemd)
  - [Rules 规则](#rules-规则)
  - [压缩管线](#压缩管线)
  - [自动记忆](#自动记忆)
  - [子代理 (AgentTool)](#子代理-agenttool)
- [反馈闭环](#反馈闭环)
- [CLI 参考](#cli-参考)
- [完整示例](#完整示例)
- [测试](#测试)
- [技术栈](#技术栈)

---

## 架构概览

```
┌────────────────────────────────────────────────────────┐
│                   反馈闭环 (Feedback Loop)                │
│   [Tracing] ← [Attribution] ← [Abstraction] → [Optimize] │
│                          + [Eval]                       │
└──────────────────────────┬─────────────────────────────┘
                           │ feeds into
┌──────────────────────────▼─────────────────────────────┐
│                  场景化能力层 (Capabilities)               │
│    [Skills (场景组合)] ──使用──► [Plugins (原子能力)]       │
│     SKILL.md / YAML frontmatter    File / Shell / Web    │
│     渐进式加载                      LLM Provider          │
└──────────────────────────┬─────────────────────────────┘
                           │ runs on
┌──────────────────────────▼─────────────────────────────┐
│                   通用底座 (Runtime Base)                 │
│  ┌──────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Loop │ │Permissions│ │  Hooks   │ │   Memory     │  │
│  │7-state│ │deny-first │ │ 17+ event│ │ Working      │  │
│  │think→ │ │tool-level │ │ matcher  │ │ Episodic     │  │
│  │act→obs│ │approval   │ │cmd/http  │ │ Semantic     │  │
│  └──────┘ └───────────┘ └──────────┘ │ AutoMemory   │  │
│  ┌──────────┐                        │ Compressor   │  │
│  │ Recovery │                        └──────────────┘  │
│  │checkpoint│  ┌──────────┐  ┌──────────────────┐     │
│  │resume    │  │ Sandbox  │  │   AgentTool      │     │
│  └──────────┘  └──────────┘  │  sub-agents      │     │
│                              └──────────────────┘     │
└────────────────────────────────────────────────────────┘
```

### 三维设计

| 维度 | 说明 | 核心组件 |
|------|------|---------|
| **Runtime Base** | Agent 的运行时骨架 | Loop, Permissions, Hooks, Memory, Recovery, Sandbox |
| **Capabilities** | 场景化能力层 | Plugins (原子能力), Skills (场景组合) |
| **Feedback Loop** | 持续优化进化 | Tracing, Eval, Attribution, Abstraction, Optimization |

---

## 快速开始

### 安装

```bash
pip install -e .
```

### 三行代码跑一个 Agent

```python
import asyncio
from harness import Harness

async def main():
    h = Harness()
    await h.start()
    result = await h.run("列出当前目录的文件")
    print(f"输出: {result.output}")
    await h.stop()

asyncio.run(main())
```

### CLI 运行

```bash
# 运行任务
python -m harness run "帮我读 README.md"

# 显示配置
python -m harness config

# 显示系统信息
python -m harness info

# 运行评估套件
python -m harness eval ./eval_suite.json --output report.json
```

---

## 核心运行时

### Agent Loop

7 状态状态机，驱动 `think → act → observe` 循环：

```
INIT → IDLE → THINKING → ACTING → OBSERVING → (→THINKING / →DONE)
```

```python
from harness import Harness

h = Harness()
await h.start()

result = await h.run("你的任务")
print(f"状态: {result.status.name}")   # DONE / ERROR
print(f"步数: {len(result.steps)}")     # 总共执行了多少步
print(f"输出: {result.output}")         # 最终输出
print(f"耗时: {result.total_duration:.2f}s")

await h.stop()
```

**SessionResult 结构：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | str | 会话 ID |
| `status` | AgentStatus | DONE / ERROR |
| `steps` | list[Step] | 所有执行步骤 |
| `output` | str \| None | 最终输出 |
| `error` | str \| None | 错误信息 |
| `total_duration` | float | 总耗时(秒) |

---

### 权限系统

4 级权限 + deny-first 评估 + 工具级过滤 + 交互式审批。

#### 权限等级

| 等级 | 值 | 说明 |
|------|-----|------|
| `NONE` | 0 | 完全无权限，只能输出文本 |
| `READ_ONLY` | 1 | 只读文件，受限网络 |
| `SANDBOX` | 2 | 限定目录/命令/网络白名单 |
| `FULL` | 3 | 完全信任，无限制 |

#### 基本使用

```python
from harness import Harness
from harness.core.permissions import PermissionLevel

# 默认 SANDBOX 模式
h = Harness()
await h.start()

# 通过配置指定权限
from harness.config.schema import HarnessConfig

config = HarnessConfig.default()
config.permission_level = PermissionLevel.READ_ONLY
config.permission = {
    "read_paths": ["."],
    "exec_commands": ["ls", "cat", "pwd"],
}
h2 = Harness(config=config)
```

#### Deny 规则 (deny-first)

拒绝规则优先于允许规则 — 即使路径在白名单中，被 deny 规则的命令也会被拒绝：

```python
from harness.core.permissions import (
    PermissionPolicy, DenyRule, ResourceType,
)

policy = PermissionPolicy.sandbox(base_dir=".")
policy.add_deny_rule(
    pattern="rm",
    resource_type=ResourceType.EXEC_COMMAND,
    reason="rm is disabled in sandbox",
)
policy.add_deny_rule(
    pattern="shutdown*",
    resource_type=ResourceType.EXEC_COMMAND,
    reason="System commands not allowed",
)

# 测试
policy.check(ResourceType.EXEC_COMMAND, "ls")       # ✅ 允许
policy.check(ResourceType.EXEC_COMMAND, "rm -rf /")  # ❌ PermissionDenied
```

#### 工具级权限

按工具名称 glob 匹配，支持按资源路径过滤：

```python
from harness.core.permissions import PermissionPolicy, ToolPermission

policy = PermissionPolicy(
    level=PermissionLevel.SANDBOX,
    tool_permissions=[
        # 允许所有 read_* 工具
        ToolPermission("read_*", allowed=True),
        # 禁止写入 /etc
        ToolPermission("write_file", allowed=False,
                       resource_pattern="/etc/**",
                       reason="No system file writes"),
    ],
)

policy.check_tool("read_file", "/tmp/test.txt")       # ✅ 允许
policy.check_tool("write_file", "/etc/passwd")         # ❌ PermissionDenied
```

#### 审批模式

```python
from harness.core.permissions import (
    PermissionPolicy, ApprovalMode,
    PermissionApprovalRequired,
)

# Auto 模式 — ML classifier 占位 (默认)
policy_auto = PermissionPolicy.auto()

# Interactive 模式 — 需要审批
policy_interactive = PermissionPolicy(
    level=PermissionLevel.SANDBOX,
    approval_mode=ApprovalMode.INTERACTIVE,
)
try:
    policy_interactive.check("FILE_READ", "/secret.txt")
except PermissionApprovalRequired as e:
    print(f"需要审批: {e}")

# Plan 模式 — 仅计划，不执行
policy_plan = PermissionPolicy(
    level=PermissionLevel.SANDBOX,
    approval_mode=ApprovalMode.PLAN,
)
```

---

### Hook 系统

17+ 个生命周期事件，支持 `observe / modify / abort` 三种模式，带条件过滤。

#### 全部事件列表

| 事件 | 触发时机 | 数据 |
|------|---------|------|
| `on_harness_start` | Harness 启动完成 | Harness 实例 |
| `on_harness_stop` | Harness 停止 | Harness 实例 |
| `on_session_start` | 会话开始 | SessionState |
| `on_session_end` | 会话结束 | SessionState |
| `on_step_start` | 每个 step 开始 | Step |
| `on_step_end` | 每个 step 结束 | Step |
| `on_before_think` | Think 开始前 | task + step_number |
| `on_after_think` | Think 结束后 | thought |
| `on_before_action` | Action 执行前 | Action |
| `on_after_action` | Action 执行后 | Step (含 observation) |
| `on_pre_tool_use` | 工具调用前 | ToolCall |
| `on_post_tool_use` | 工具调用成功 | result dict |
| `on_post_tool_use_failure` | 工具调用失败 | error result |
| `on_pre_compact` | 记忆压缩前 | SessionState |
| `on_post_compact` | 记忆压缩后 | SessionState |
| `on_user_prompt_submit` | 用户提交输入 | user input |
| `on_checkpoint` | Checkpoint 保存 | SessionState |
| `on_error` | 发生错误 | error info |

#### 基本 Hook

```python
from harness.core.hooks import HookContext
from harness import Harness

async def log_hook(ctx: HookContext):
    print(f"[{ctx.event}] 数据: {ctx.data}")
    return ctx

h = Harness()
await h.start()

h.register_hook("on_step_start", log_hook)
h.register_hook("on_step_end", log_hook)

await h.run("测试任务")
```

#### 三种 Hook 模式

```python
from harness.core.types import HookMode

# OBSERVE — 仅观察，不修改数据 (默认)
async def observe_hook(ctx):
    print(f"观察到: {ctx.event}")
    return ctx

# MODIFY — 可以修改上下文数据
async def modify_hook(ctx):
    ctx.set_modified("extra_info", "注入的内容")
    return ctx

# ABORT — 可以中止当前流程
async def abort_hook(ctx):
    if "dangerous" in str(ctx.data):
        ctx.abort = True
        ctx.abort_reason = "检测到危险操作"
    return ctx

h.register_hook("on_step_start", observe_hook, mode=HookMode.OBSERVE)
h.register_hook("on_before_action", modify_hook, mode=HookMode.MODIFY)
h.register_hook("on_pre_tool_use", abort_hook, mode=HookMode.ABORT)
```

#### 带条件过滤的 Hook (HookMatcher)

```python
from harness.core.hooks import HookMatcher

# 只对 read_file / write_file 工具生效
matcher = HookMatcher(tool_names=["read_file", "write_file"])

async def file_op_hook(ctx):
    print(f"文件操作: {ctx.data}")
    return ctx

h.register_hook("on_pre_tool_use", file_op_hook, matcher=matcher)
```

更多匹配器示例：

```python
# 按路径过滤
path_matcher = HookMatcher(paths=["/etc/**", "/var/**"])

# 按事件类型过滤
event_matcher = HookMatcher(event_types=["on_pre_tool_use", "on_post_tool_use"])

# 自定义过滤函数
def custom_matcher(ctx):
    data = ctx.data
    return isinstance(data, dict) and data.get("allowed") is True

custom_matcher = HookMatcher(custom=custom_matcher)
```

#### 命令行 Hook

事件触发时自动执行 shell 命令，不阻塞 Agent Loop：

```python
await h.hooks.register_command_hook(
    event="on_checkpoint",
    command="echo 'Checkpoint saved at $(date)' >> .harness/hook_log.txt",
    timeout=10,
)
```

#### HTTP Webhook Hook

事件触发时 POST JSON 到指定 URL：

```python
await h.hooks.register_http_hook(
    event="on_session_end",
    url="https://your-server.com/harness-events",
    timeout=5,
)
```

---

### 记忆系统

三层记忆 + 自动记忆 + 级联压缩管线。

#### 工作记忆 (WorkingMemory)

管理 LLM 上下文窗口，支持滑动窗口 + 级联压缩：

```python
from harness.core.memory import WorkingMemory, WorkingMemoryConfig
from harness.core.types import LLMMessage

wm = WorkingMemory(WorkingMemoryConfig(
    max_tokens=128_000,
    keep_recent_steps=5,        # 压缩时保留最近的步数
    aggressive_compress=False,   # 是否启用 LLM 摘要压缩
))

await wm.set_system(LLMMessage(role="system", content="你是助手"))
await wm.add(LLMMessage(role="user", content="你好"))
context = await wm.get_context()  # 获取完整上下文
```

#### 情景记忆 (EpisodicMemory)

会话级别的 step 历史记录，支持文件持久化和恢复：

```python
from harness.core.memory import EpisodicMemory, EpisodicMemoryConfig

em = EpisodicMemory(EpisodicMemoryConfig(
    persist_dir=".harness/memory/episodic",
    compress_threshold=100,  # 超过 100 step 自动摘要
))

await em.start_session("session_001")
await em.record_step(step)

# 持久化
await em.save()

# 从文件恢复
await em.load("session_001")
steps = em._steps  # 已恢复的 steps (含 action/observation)
```

#### 语义记忆 (SemanticMemory)

跨 session 的长期知识存储，基于 TF-IDF 检索，零外部依赖：

```python
from harness.core.memory import SemanticMemory

sm = SemanticMemory(persist_dir=".harness/memory/semantic")

# 存储知识
await sm.add_knowledge(
    content="项目使用 FastAPI 作为后端框架",
    source_session="session_001",
    tags=["backend", "fastapi"],
)

# 搜索
results = await sm.search("后端框架是什么？", top_k=5)
for entry in results:
    print(f"[{entry.access_count}次访问] {entry.content[:100]}")
```

#### 自动记忆 (AutoMemory)

跨 session 自动记录关键信息（工具调用模式、错误修复、关键发现）：

```python
from harness.core.memory import AutoMemory

am = AutoMemory(persist_dir=".harness/memory")

# 自动检测重要信息 (在 Hook 中调用)
async def record_hook(ctx):
    step = ctx.data
    if hasattr(step, 'action') and step.action:
        await am.record_step(step)
    return ctx

h.register_hook("on_step_end", record_hook)

# 获取历史记忆注入上下文
context = await am.get_context(limit=5)
# 返回 [LLMMessage(role="system", content="[Auto Memory - tool_pattern]: ...")]

# 持久化 (跨 session)
await am.save()
```

#### 压缩管线

5 层级联压缩，从零开销到 LLM 摘要：

| 层级 | 名称 | 开销 | 说明 |
|------|------|------|------|
| 1 | Tool Result Budget | 零 LLM | 大结果存盘 + 摘要占位 |
| 2 | Snip | 零 LLM | 裁剪超长内容 |
| 3 | Microcompact | 零 LLM | 合并连续相同角色消息 |
| 4 | Collapse | 零 LLM | 折叠相似 tool call 轮次 |
| 5 | Summary | 有 LLM | LLM 摘要压缩 |

```python
from harness.core.memory import Compressor

compressor = Compressor(
    max_summary_tokens=1000,
    # llm_provider=my_llm,  # 可选：提供 LLM 以启用第 5 层
)

# 直接压缩消息列表
compressed = await compressor.compress_messages(messages, aggressive=True)

# 或压缩为摘要
summary = await compressor.compress_to_summary(messages, max_length=500)
print(f"摘要: {summary.content}")
print(f"Token数: {summary.token_count}")
```

---

### 中断恢复

自动 Checkpoint + 中断恢复，长任务不怕中途失败：

```python
# Checkpoint 每 3 step 自动保存
# 恢复时指定 session_id
result = await h.run("长任务", session_id="my_session")

# 如果中途失败，下次运行相同 session_id 会自动恢复
result2 = await h.run("长任务", session_id="my_session")
```

```python
from harness.core.recovery import RecoveryManager

mgr = RecoveryManager(checkpoint_dir=".harness/checkpoints")

# 列出所有 checkpoints
checkpoints = mgr.list_checkpoints()

# 检查是否有 checkpoint
if mgr.has_checkpoint("session_001"):
    checkpoint = await mgr.load("session_001")
    state = await mgr.resume(checkpoint)

# 清理过期检查点 (默认 7 天)
cleaned = mgr.clean_expired()
```

---

## 能力层

### Plugin 插件

原子能力单元，一个 Plugin = 一组 Tool。

#### 内置 Plugin

| Plugin | 工具 | 说明 |
|--------|------|------|
| `FilePlugin` | `read_file`, `write_file`, `list_files` | 文件系统操作 |
| `ShellPlugin` | `execute_command` | Shell 命令执行 |
| `WebPlugin` | `http_get`, `http_post` | HTTP 网络请求 |
| `LLMProviderPlugin` | — | LLM 调用封装 |

#### 使用内置 Plugin

```python
from harness import Harness

h = Harness()
await h.start()

# 内置 Plugin 默认已注册
tools = h.plugins.collect_tools()
for t in tools:
    print(f"工具: {t.name} — {t.description}")
```

#### 自定义 Plugin

```python
from harness.plugins.interface import Plugin, PluginMetadata, CapabilityType
from harness.core.types import ToolDefinition
from typing import Any

class MyToolPlugin(Plugin):
    metadata = PluginMetadata(
        name="my_tools",
        version="0.1.0",
        description="My custom tools",
        capabilities=[CapabilityType.TOOL],
    )

    async def load(self, config: dict[str, Any]) -> None:
        pass

    async def init(self, harness: Any) -> None:
        self._harness = harness

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="hello",
                description="Say hello to someone",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name to greet",
                        },
                    },
                    "required": ["name"],
                },
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict) -> str:
        if name == "hello":
            return f"Hello, {arguments.get('name', 'world')}!"
        return f"Unknown tool: {name}"

# 注册
h.register_plugin(MyToolPlugin())
```

---

### Skill 技能

场景组合能力 = Prompt 模板 + Tool 编排 + 规则配置。

#### 使用内置 Skill

```python
from harness.skills.builtins.code_review import CodeReviewSkill
from harness import Harness

h = Harness()
await h.start()

h.register_skill(CodeReviewSkill())

# 自动匹配关键词 "review", "审查", "code review" 等
result = await h.run("帮我 review 这段 Python 代码")
print(result.output)
```

#### 编写自定义 Skill (Python class)

```python
from harness.skills.interface import Skill, SkillMetadata, SkillContext
from harness.core.types import ToolDefinition

class DocWriterSkill(Skill):
    metadata = SkillMetadata(
        name="doc_writer",
        version="0.1.0",
        description="文档编写助手",
        match_keywords=["文档", "doc", "documentation", "docs"],
        allowed_tools=["read_file", "write_file", "list_files"],
        priority=10,  # 优先级越高越优先匹配
    )

    async def get_system_prompt(self, context: SkillContext) -> str:
        return (
            "You are a technical documentation writer. "
            "Follow these guidelines:\n"
            "1. Read existing code and comments before writing\n"
            "2. Write clear, concise documentation in Chinese\n"
            "3. Include code examples where appropriate\n"
            "4. Follow Google-style docstring format"
        )

    def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        # 只返回 read/write 工具 (由 allowed_tools 自动过滤)
        return super().get_tools(context)
```

#### SKILL.md — YAML Frontmatter 格式

最简单的方式，用 YAML frontmatter 声明 Skill：

```python
from harness.skills.interface import SKILL

skill = SKILL.from_yaml("""---
name: translator
version: "1.0.0"
description: 翻译助手
allowed_tools:
  - read_file
  - write_file
model: opus
context: |
  You are a professional translator.
  Translate the user's text to the target language.
  Keep the original formatting and code blocks intact.
---

Additional notes or content here.
""")

if skill:
    h.register_skill(skill)
```

#### 得分匹配机制

Skill 匹配得分 = 关键词命中数 + 短语加分 + 优先级权重：

```python
# match() 返回 float 得分
score = skill.match("请帮我写文档")
# score = 1.0 (关键词 "文档" 命中) + 0.0 + priority * 0.1

# 多个匹配时按得分降序选择
selected = registry.select_skill("帮我 review 代码")
```

#### 渐进式加载

先注册轻量级描述，命中后才加载完整 Skill，减少上下文开销：

```python
from harness.skills.registry import SkillRegistry, SkillDescriptor

registry = SkillRegistry()

# 先注册描述（轻量级）
descriptor = SkillDescriptor(
    name="heavy_skill",
    description="A large skill that should be lazily loaded",
    match_keywords=["heavy", "complex"],
    priority=20,
    loader=lambda: HeavySkill(),  # 命中后才调用
)
registry.register_descriptor(descriptor)

# 匹配只使用描述，不会触发加载
matches = registry.match_skills("我需要 complex 分析")
assert matches[0][1] is None  # 未加载

# 选中时自动加载
skill = registry.select_skill("我需要 complex 分析")
# 此时 HeavySkill() 被调用

# 列出所有已注册 Skill (不触发加载)
descriptions = registry.list_loaded_descriptions()
for d in descriptions:
    print(f"{d['name']}: {'已加载' if d['loaded'] else '未加载'}")
```

---

## 高级功能

### 配置层次

5 级配置覆盖链，优先级从低到高：

| 层级 | 文件位置 | 说明 |
|------|---------|------|
| 1. 企业/共享 | `.harness/settings.json` | 项目级共享配置 |
| 2. 用户级 | `~/.harness/settings.json` | 用户全局配置 |
| 3. 本地覆盖 | `.harness/settings.local.json` | 个人覆盖 (不提交) |
| 4. CLI 指定 | `--config path/to/config.yaml` | 命令行指定 |

配置自动发现和合并：

```python
from harness.config.schema import HarnessConfig

# 一键加载配置层次
config = HarnessConfig.load(project_dir=".")

# 或使用 CLI 指定配置文件
config = HarnessConfig.load(
    project_dir=".",
    cli_config_path="./custom_config.yaml",
)
```

配置文件示例 (JSON)：

```json
{
  "max_steps": 100,
  "permission_level": "SANDBOX",
  "permission": {
    "read_paths": ["."],
    "write_paths": ["./output"],
    "exec_commands": ["ls", "cat", "python", "node"]
  },
  "llm": {
    "provider": "openai",
    "model": "gpt-4o",
    "max_tokens": 4096
  },
  "memory": {
    "working_max_tokens": 128000,
    "semantic_enabled": true
  },
  "recovery": {
    "checkpoint_dir": ".harness/checkpoints",
    "checkpoint_interval": 3
  }
}
```

YAML 格式：

```yaml
max_steps: 100
permission_level: SANDBOX
llm:
  provider: openai
  model: gpt-4o
memory:
  semantic_enabled: true
```

### CLAUDE.md

类似 Claude Code 的 `CLAUDE.md`，内容自动注入到 System Prompt，标记为"抗压缩"：

将 `CLAUDE.md` 放在项目根目录或 `.claude/CLAUDE.md`：

```markdown
# CLAUDE.md — 项目指南

## 技术栈
- Python 3.11+ asyncio
- FastAPI 后端
- PostgreSQL 数据库

## 开发规范
- 使用 ruff 进行代码检查
- 所有函数必须有类型注解
- 使用 pytest 编写测试
```

Harness 自动加载并注入：

```python
config = HarnessConfig.load()
print(config.claude_md_content)  # 自动读取 CLAUDE.md
extra_prompt = config.build_system_prompt_extra()
# 内容包含 "=== CLAUDE.md (Protected — do not compress) ===" 标记
```

### Rules 规则

路径作用域的模块化规则文件 — `rules/<scope>.md`：

```
project/
├── rules/
│   ├── backend.md     # 作用于 backend/ 目录
│   ├── frontend.md    # 作用于 frontend/ 目录
│   └── database.md    # 作用于数据库操作
```

示例 `rules/backend.md`：

```markdown
# Backend Rules

- Use SQLAlchemy for all database operations
- All API endpoints must have input validation
- Use dependency injection for services
```

自动加载：

```python
config = HarnessConfig.load()
# config.rules = [{"path": "backend", "content": "..."}, ...]
prompt = config.build_system_prompt_extra()
# 自动包含所有 rule 内容
```

### 子代理 (AgentTool)

在隔离的 Harness 实例中运行子 Agent：

```python
from harness.core.agent_tool import AgentTool, AgentToolConfig

agent_tool = AgentTool()

# 运行单个子 Agent
result = await agent_tool.run_sub_agent(
    task="阅读 README.md 并总结",
    config=AgentToolConfig(max_steps=10, timeout_seconds=60),
)
print(f"完成: {result.success}")
print(f"输出: {result.output}")
print(f"步数: {result.steps}")
print(f"耗时: {result.duration:.2f}s")

# 并行运行多个子 Agent
results = await agent_tool.run_sub_agents_parallel(
    tasks=[
        "分析 src/main.py",
        "分析 src/utils.py",
        "分析 tests/test_main.py",
    ],
    max_concurrent=3,  # 最大并行数
)
for r in results:
    print(f"[{'✓' if r.success else '✗'}] {r.task}: {r.duration:.1f}s")
```

Bubble 权限模式 — 子 Agent 的权限冒泡到父级审批：

```python
from harness.core.agent_tool import create_bubble_policy
from harness.core.permissions import PermissionPolicy

# 创建 bubble 模式权限
bubble_policy = create_bubble_policy(PermissionPolicy.sandbox())

result = await agent_tool.run_sub_agent(
    task="需要审批的操作",
    permissions=bubble_policy,
)
```

---

## 反馈闭环

Tracing → Attribution → Abstraction → Optimization：

```python
from harness.feedback.integration import FeedbackIntegrator

h = Harness()
await h.start()

feedback = FeedbackIntegrator()
trace_id = feedback.start_trace()

try:
    result = await h.run("分析项目代码结构")

    # 反馈分析
    analysis = feedback.end_trace_and_analyze()
    if analysis.get("status") == "analyzed":
        attr = analysis["attribution"]
        print(f"根因: {attr.root_cause}")
        print(f"建议: {attr.suggestion}")

        sug = analysis["suggestion"]
        if sug["auto_applicable"]:
            print(f"可自动修复: {sug['target']}")
finally:
    await h.stop()
```

### Eval 评估

```python
from harness.feedback.eval import EvalCase, EvalSuite, EvalRunner

suite = EvalSuite(name="code_review_test")
suite.add_case(EvalCase(
    id="cr_01",
    name="should detect division by zero",
    input="review this: x = 10 / 0",
    expected="division by zero",
    judge="substring",
))

runner = EvalRunner(harness=h)
report = await runner.run_suite(suite)
print(f"通过率: {report.pass_rate:.1%}")
```

---

## CLI 参考

```bash
# 运行任务
python -m harness run <task> [options]
  -s, --session <id>    指定 Session ID (用于恢复)
  -n, --steps <n>       最大步数 (默认: 50)
  -c, --config <path>   配置文件路径 (.json / .yaml)
  -v, --verbose         详细输出

# 运行评估
python -m harness eval <suite_file> [options]
  -o, --output <path>   报告输出路径

# 显示当前配置
python -m harness config

# 显示系统信息
python -m harness info
```

示例：

```bash
# 使用配置文件运行
python -m harness run "分析代码" --config ./my_config.yaml --verbose

# 恢复中断的任务
python -m harness run "长任务" --session my_session_001

# 限制步数
python -m harness run "快速检查" --steps 5
```

---

## 完整示例

### 带权限、Hook、Skill 的生产级使用

```python
import asyncio
from harness import Harness
from harness.core.hooks import HookContext, HookMatcher
from harness.core.types import HookMode
from harness.config.schema import HarnessConfig
from harness.skills.builtins.code_review import CodeReviewSkill

async def main():
    # 1. 从配置层次加载
    config = HarnessConfig.load(project_dir=".")

    # 2. 创建 Harness
    h = Harness(config=config)
    await h.start()

    # 3. 注册 Skill
    h.register_skill(CodeReviewSkill())

    # 4. 注册日志 Hook
    async def log_hook(ctx: HookContext):
        print(f"[{ctx.event}] 触发")
        return ctx
    h.register_hook("on_step_start", log_hook)
    h.register_hook("on_step_end", log_hook)

    # 5. 注册文件操作追踪 Hook
    file_matcher = HookMatcher(tool_names=["read_file", "write_file"])
    async def track_file_ops(ctx: HookContext):
        print(f"  文件操作: {ctx.data}")
        return ctx
    h.register_hook("on_pre_tool_use", track_file_ops, matcher=file_matcher)

    # 6. 注册错误捕获 Hook (ABORT 模式)
    async def catch_errors(ctx: HookContext):
        result = ctx.data
        if isinstance(result, dict) and "Error" in str(result.get("result", "")):
            print(f"  工具出错: {result}")
        return ctx
    h.register_hook("on_post_tool_use_failure", catch_errors)

    # 7. 运行任务
    result = await h.run("帮我 review 当前项目代码")

    # 8. 输出结果
    print(f"\n=== 结果 ===")
    print(f"状态: {result.status.name}")
    print(f"步数: {len(result.steps)}")
    print(f"耗时: {result.total_duration:.2f}s")
    print(f"输出: {result.output}")

    await h.stop()

asyncio.run(main())
```

### 使用子代理并行分析

```python
import asyncio
from harness import Harness
from harness.core.agent_tool import AgentTool, AgentToolConfig

async def main():
    h = Harness()
    await h.start()

    agent_tool = AgentTool()

    # 并行分析多个文件
    files = ["harness/core/loop.py", "harness/core/hooks.py", "harness/core/permissions.py"]
    tasks = [f"分析文件 {f} 的结构和功能" for f in files]

    results = await agent_tool.run_sub_agents_parallel(
        tasks,
        config=AgentToolConfig(max_steps=5, timeout_seconds=30),
        max_concurrent=3,
    )

    for f, r in zip(files, results):
        status = "✓" if r.success else "✗"
        print(f"[{status}] {f}: {r.duration:.1f}s, {r.steps}步")

    await h.stop()

asyncio.run(main())
```

---

## 测试

```bash
# 运行所有 103 个测试
pytest tests/

# 按测试文件
pytest tests/test_core/test_harness.py -v      # 核心底座
pytest tests/test_core/test_phase2.py -v       # Plugin + Skill
pytest tests/test_core/test_edge_cases.py -v   # 边界情况
pytest tests/test_core/test_enhancements.py -v # 增强功能 (48 tests)
pytest tests/test_feedback/test_phase3.py -v   # 反馈闭环
```

---

## 技术栈

- **Python 3.11+** — asyncio, dataclasses
- **零外部依赖** — 核心运行时无需第三方库
- **可选依赖** — `httpx` (WebPlugin), `PyYAML` (YAML 配置), `pytest-asyncio` (测试)

---

## 模块结构

```
harness/
├── harness.py                    # 顶层入口
├── __main__.py                   # CLI 入口
├── config/
│   └── schema.py                 # 配置管理 (5层层次 + CLAUDE.md + Rules)
├── core/
│   ├── loop.py                   # Agent Loop 状态机 (7状态)
│   ├── hooks.py                  # Hook 系统 (17+事件, Matcher, Cmd/HTTP)
│   ├── permissions.py            # 权限系统 (Deny-first, 工具级, 审批模式)
│   ├── recovery.py               # Checkpoint + 中断恢复
│   ├── sandbox.py                # 沙箱环境
│   ├── types.py                  # 核心类型定义
│   ├── llm.py                    # LLM 抽象
│   ├── agent_tool.py             # 子代理 (AgentTool)
│   └── memory/
│       ├── working.py            # 工作记忆 (+ Compressor 集成)
│       ├── episodic.py           # 情景记忆 (完整序列化/反序列化)
│       ├── semantic.py           # 语义记忆 (TF-IDF)
│       ├── summarizer.py         # 摘要器
│       ├── compressor.py         # 5层压缩管线
│       └── auto_memory.py        # 自动记忆 (跨 Session)
├── plugins/
│   ├── interface.py              # Plugin 接口
│   ├── registry.py               # Plugin 注册中心
│   └── builtins/
│       ├── file.py               # 文件操作 Plugin
│       ├── shell.py              # Shell 命令 Plugin
│       ├── web.py                # HTTP 网络 Plugin
│       └── llm_provider.py       # LLM Provider Plugin
├── skills/
│   ├── interface.py              # Skill 接口 (YAML Frontmatter, 得分匹配)
│   ├── registry.py               # Skill 注册中心 (渐进式加载)
│   └── builtins/
│       └── code_review.py        # 代码审查 Skill (示例)
└── feedback/
    ├── integration.py            # 反馈闭环集成器
    ├── tracing/                  # 全链路追踪
    ├── eval/                     # 评估框架 (EvalCase/Suite/Runner)
    ├── attribution/              # 在线归因
    ├── abstraction/              # 问题抽象
    └── optimization/             # 迭代优化
tests/
├── test_core/
│   ├── test_harness.py           # 核心底座测试
│   ├── test_phase2.py            # Plugin + Skill 测试
│   ├── test_edge_cases.py        # 边界情况测试
│   └── test_enhancements.py      # 增强功能测试 (48 tests)
└── test_feedback/
    └── test_phase3.py            # 反馈闭环测试
```
