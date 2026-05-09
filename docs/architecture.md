# 架构总览

## 核心理念

Harness Agent 是一个**通用 Agent 运行时框架**，设计哲学是"三明治架构"：

1. **底层** — 通用的运行骨架，让 Agent 能跑起来
2. **中间层** — 场景能力扩展，让 Agent 干好活
3. **顶层** — 反馈进化闭环，让 Agent 持续优化

## 三维架构图

```
                    ┌──────────────────────────────────┐
                    │          用户 / 外部系统            │
                    └──────────────┬───────────────────┘
                                   │ task
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Harness (顶层入口)                                                │
│                                                                  │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌───────────────┐ │
│  │ HookReg │   │ Perm     │   │ PluginReg│   │  SkillReg     │ │
│  │ istry   │   │ Policy   │   │ istry    │   │  istry        │ │
│  └────┬────┘   └──────────┘   └────┬─────┘   └──────┬────────┘ │
│       │                             │                │          │
│       ▼                             ▼                ▼          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Agent Loop (状态机)                          │  │
│  │  INIT → IDLE → THINK → ACT → OBSERVE → CHECKPOINT → DONE│  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  Memory Manager                                   │  │  │
│  │  │  ┌──────────┐  ┌───────────┐  ┌──────────────┐   │  │  │
│  │  │  │ Working  │  │ Episodic  │  │  Semantic    │   │  │  │
│  │  │  │ Memory   │  │ Memory    │  │  Memory      │   │  │  │
│  │  │  └──────────┘  └───────────┘  └──────────────┘   │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │  Recovery Manager (Checkpoint + Resume)            │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                           │                     │
│  ┌──────────────────────────────────────┐ │                     │
│  │  Feedback Integrator                  │ │                     │
│  │  Tracing → Attribution → Abstraction  │ │                     │
│  │  → Optimization → Eval                │ │                     │
│  └──────────────────────────────────────┘ │                     │
└──────────────────────────────────────────────────────────────────┘
```

## 模块依赖关系

```
types.py ← 所有模块依赖基础类型
    │
    ├── hooks.py ← HookRegistry
    │       │
    │       ├── permissions.py ← PermissionPolicy
    │       │
    │       ├── memory/
    │       │   ├── base.py ← Memory 基类
    │       │   ├── working.py ← WorkingMemory
    │       │   ├── episodic.py ← EpisodicMemory
    │       │   ├── semantic.py ← SemanticMemory
    │       │   └── summarizer.py ← Summarizer
    │       │
    │       ├── llm.py ← LLMProvider 抽象
    │       │
    │       ├── recovery.py ← RecoveryManager
    │       │
    │       ├── sandbox.py ← Sandbox
    │       │
    │       ├── loop.py ← AgentLoop (依赖以上所有)
    │       │
    │       ├── plugins/ ← Plugin 系统
    │       │   ├── interface.py ← Plugin 基类
    │       │   ├── registry.py ← PluginRegistry
    │       │   └── builtins/ ← 内置 Plugin
    │       │
    │       ├── skills/ ← Skill 系统
    │       │   ├── interface.py ← Skill 基类
    │       │   ├── registry.py ← SkillRegistry
    │       │   └── builtins/ ← 内置 Skill
    │       │
    │       └── feedback/ ← 反馈闭环
    │           ├── tracing/ ← Tracer
    │           ├── eval/ ← EvalRunner
    │           ├── attribution/ ← AttributionAnalyzer
    │           ├── abstraction/ ← PatternExtractor
    │           ├── optimization/ ← Optimizer
    │           └── integration.py ← FeedbackIntegrator
    │
    └── harness.py ← Harness (组装所有子系统)
```

## 数据流

### 一次完整的任务执行

```
用户输入 "帮我审查代码"
        │
        ▼
Harness.run()
        │
        ├── SkillRegistry.select_skill("审查代码")
        │   └── 匹配到 CodeReviewSkill
        │
        ├── CodeReviewSkill 注册 Hook
        │   ├── on_before_think → 注入代码审查 System Prompt
        │   ├── on_before_action → 校验操作安全
        │   └── on_after_action → 后处理
        │
        ├── PluginRegistry.collect_tools()
        │   └── 收集 FilePlugin, ShellPlugin 的 tools
        │
        └── AgentLoop.execute(task)
            │
            ├── [Step 1] THINK → LLM 思考 "需要先读文件"
            ├── [Step 1] ACT → 调用 read_file
            ├── [Step 1] OBSERVE → 得到文件内容
            │
            ├── [Step 2] THINK → "分析代码问题"
            ├── [Step 2] ACT → 输出审查结果
            ├── [Step 2] OBSERVE → 完成
            │
            └── [Checkpoint] 保存状态
```

### 反馈闭环数据流

```
Agent 运行完成
    │
    ▼
Tracer 记录所有 Span
    │
    ▼
AttributionAnalyzer 分析错误根因
    │
    ▼
PatternExtractor 归纳为 FailurePattern
    │
    ▼
Optimizer 生成优化建议
    │
    ▼
EvalRunner 运行回归测试
    │
    ▼
部署新版本
```

## 关键设计决策

1. **Plugin 和 Skill 分离**：Plugin 是原子能力（技术视角），Skill 是场景组合（业务视角），两者松耦合通过 Hook 通信

2. **状态机驱动**：Agent Loop 使用显式状态机（7 个状态），每个状态的转换清晰可控

3. **三层记忆**：Working Memory 解决 Context Window 限制，Episodic Memory 保障长任务可追溯，Semantic Memory 实现跨 Session 学习

4. **Hook 优先扩展**：通过 12 个生命周期事件提供扩展点，Plugin/Skill 通过 Hook 介入而非直接修改运行时

5. **反馈闭环原生集成**：Tracing、Eval、归因、优化是运行时的一等公民，不是外挂
