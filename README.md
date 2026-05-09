# Harness — 通用 Agent 运行时框架

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-55%20passed-brightgreen.svg)](tests/)

**Harness** 是一个通用的 Agent 运行时框架（Harness Agent），为智能体提供标准化的运行、扩展和进化能力。它不绑定任何特定 LLM 或场景，而是提供一套通用的骨架，让开发者可以专注于构建智能体的业务能力。

## 核心设计：三维架构

```
┌──────────────────────────────────────────────────┐
│              反馈闭环 (Feedback Loop)               │
│  [Eval] ← [Attribution] ← [Abstraction] → [Optimize]
└──────────────────────┬───────────────────────────┘
                       │ feeds into
┌──────────────────────▼───────────────────────────┐
│          场景化能力层 (Skills + Plugins)            │
│    [Skills (场景组合)] ──使用──► [Plugins (原子能力)]  │
└──────────────────────┬───────────────────────────┘
                       │ runs on
┌──────────────────────▼───────────────────────────┐
│              通用底座 (Runtime Base)                │
│  [Loop] [Permissions] [Hooks] [Memory] [Recovery]  │
└──────────────────────────────────────────────────┘
```

### Dimension 1: 通用底座

Agent 的运行时骨架，让 Agent 能跑起来：

| 组件 | 说明 |
|------|------|
| **Agent Loop** | 7 状态状态机 (`INIT→IDLE→THINK→ACT→OBSERVE→CHECKPOINT→DONE`)，驱动 think→act→observe 循环 |
| **Permissions** | 4 级权限控制 (`NONE → READ_ONLY → SANDBOX → FULL`)，防止 Agent 失控 |
| **Hooks** | 12 个生命周期事件，支持 `observe / modify / abort` 三种模式，在关键点介入扩展 |
| **Memory** | 三层记忆架构：Working Memory (Context窗口管理) + Episodic Memory (Step历史记录) + Semantic Memory (跨Session知识) |
| **Recovery** | Checkpoint 机制 + 中断恢复，长任务不崩 |

### Dimension 2: 场景化能力

Plugin + Skill 双层架构，让 Agent 干好活：

```
Skill Layer (面向场景的组合能力)
  [CodeReview]  [DataAnalysis]  [Deploy]
       │              │              │
       ▼              ▼              ▼
Plugin Layer (面向技术的原子能力)
  [File]  [Shell]  [Web]  [LLM]
```

- **Plugin**：原子能力单元（文件读写、Shell命令、HTTP请求等），一个 Plugin = 一组 Tool
- **Skill**：场景组合能力（代码审查、部署上线等），= Prompt 模板 + Tool 编排 + 规则配置

### Dimension 3: 反馈闭环

让 Harness 持续优化进化：

```
线上运行 → Tracing → 归因分析 → 问题抽象 → 优化建议 → Eval验证 → 部署上线
```

## 快速开始

### 安装

```bash
pip install -e .
```

### 基本使用

```python
import asyncio
from harness import Harness

async def main():
    # 创建并启动 Harness
    h = Harness()
    await h.start()

    # 运行任务
    result = await h.run("帮我列出当前目录的文件")
    print(f"状态: {result.status.name}")
    print(f"步数: {len(result.steps)}")
    print(f"输出: {result.output}")

    # 停止
    await h.stop()

asyncio.run(main())
```

### CLI 使用

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

### 注册 Hook

```python
from harness.core.hooks import HookContext

async def my_hook(ctx: HookContext):
    print(f"事件触发: {ctx.event}")
    # 可以修改上下文数据
    ctx.set_modified("key", "value")
    return ctx

h = Harness()
await h.start()
h.register_hook("on_step_start", my_hook)
```

### 注册 Plugin

```python
from harness.plugins.builtins.file import FilePlugin
from harness.plugins.builtins.shell import ShellPlugin

h = Harness()
await h.start()

# 注册自定义 Plugin
h.register_plugin(FilePlugin())
h.register_plugin(ShellPlugin())
```

### 注册 Skill

```python
from harness.skills.builtins.code_review import CodeReviewSkill

h = Harness()
await h.start()

# 注册自定义 Skill
h.register_skill(CodeReviewSkill())

# Harness 会自动匹配任务关键词，注入对应的 System Prompt 和 Tools
result = await h.run("帮我 review 这段代码")
```

## 完整示例

### 集成反馈闭环

```python
import asyncio
from harness import Harness
from harness.feedback.integration import FeedbackIntegrator

async def main():
    h = Harness()
    await h.start()

    # 集成反馈闭环
    feedback = FeedbackIntegrator()
    trace_id = feedback.start_trace()

    try:
        result = await h.run("分析项目代码结构")
        print(f"完成: {result.status.name}")

        # 反馈分析
        analysis = feedback.end_trace_and_analyze()
        if analysis.get("status") == "analyzed":
            attr = analysis["attribution"]
            print(f"根因: {attr.root_cause}")
            print(f"建议: {attr.suggestion}")
    finally:
        await h.stop()

asyncio.run(main())
```

### 使用 Eval 评估

```python
from harness.feedback.eval import EvalCase, EvalSuite, EvalRunner

# 定义评估用例
suite = EvalSuite(name="code_review_test")
suite.add_case(EvalCase(
    id="cr_01",
    name="should detect obvious bug",
    input="review this: x = 10 / 0",
    expected="division by zero",  # 期望输出包含
    judge="substring",
))

# 运行评估
runner = EvalRunner(harness=h)
report = await runner.run_suite(suite)
print(f"通过率: {report.pass_rate:.1%}")
```

## 模块结构

```
harness/
├── harness.py                    # 顶层入口
├── core/                         # Dimension 1: 通用底座
│   ├── loop.py                   # Agent Loop 状态机
│   ├── hooks.py                  # 钩子系统 (12事件)
│   ├── permissions.py            # 权限系统 (4级别)
│   ├── sandbox.py                # 沙箱环境
│   ├── llm.py                    # LLM 抽象
│   ├── recovery.py               # 中断恢复
│   ├── types.py                  # 核心类型
│   └── memory/                   # 三层记忆
├── plugins/                      # Dimension 2: 插件
│   ├── interface.py
│   ├── registry.py
│   └── builtins/                 # 内置插件
├── skills/                       # Dimension 2: 技能
│   ├── interface.py
│   ├── registry.py
│   └── builtins/                 # 内置技能(示例)
├── feedback/                     # Dimension 3: 反馈闭环
│   ├── tracing/                  # 全链路追踪
│   ├── eval/                     # 评估框架
│   ├── attribution/              # 在线归因
│   ├── abstraction/              # 问题抽象
│   ├── optimization/             # 迭代优化
│   └── integration.py           # Runtime集成器
└── config/                       # 配置管理
```

## 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行特定 Phase 测试
pytest tests/test_core/test_harness.py -v    # Phase 1: 核心底座
pytest tests/test_core/test_phase2.py -v     # Phase 2: Plugin+Skill
pytest tests/test_feedback/test_phase3.py -v # Phase 3: 反馈闭环
```

## 技术栈

- **Python 3.11+** — asyncio, dataclasses, pydantic
- **零外部依赖** — 核心运行时无需第三方库
- **可选依赖** — `httpx` (WebPlugin), `pytest-asyncio` (测试)
