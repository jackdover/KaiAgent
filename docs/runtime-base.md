# Dimension 1: 通用底座 (Runtime Base)

通用底座是 Harness Agent 的运行时骨架，包含 5 个核心子系统。

## 1.1 Agent Loop — 状态机

Agent Loop 是一个 7 状态的显式状态机，驱动 Agent 的 think→act→observe 循环。

### 状态流转图

```
        ┌──────────┐
        │  INIT    │ ← 初始化完成
        └────┬─────┘
             ▼
        ┌──────────┐   收到恢复请求     ┌───────────┐
        │  IDLE    │◄──────────────────│  RESUMING │
        └────┬─────┘                   └───────────┘
             ▼ (收到任务)                     ▲
        ┌──────────┐                     ┌───────────┐
        │ THINKING │                     │ CHECKPOINT│
        └────┬─────┘                     └─────┬─────┘
             ▼ (产出 Action)                   │
        ┌──────────┐                     ┌───────────┐
        │  ACTING  │──on_error──►│   ERROR   │
        └────┬─────┘                     └───────────┘
             ▼ (执行完成)
        ┌───────────┐
        │ OBSERVING │── 任务完成 ──► DONE
        └─────┬─────┘
              │ (继续循环)
              └──► THINKING
```

### 核心接口

```python
class AgentLoop:
    async def execute(self, task: str, session_id: str | None = None) -> SessionResult:
        """执行一个完整任务，包含多个 step。"""

    async def _run_one_step(self, task: str, step_number: int) -> Step:
        """执行一个完整的 step: think → act → observe。"""

    def set_tools(self, tools: list[ToolDefinition]) -> None:
        """设置 LLM 可用的工具列表。"""
```

### 循环控制

- `max_steps`：最大循环步数（默认 50），防止无限循环
- `_is_finished()`：检测 ActionType.FINISH 终止循环
- Checkpoint：每 3 步自动保存一次状态

## 1.2 权限系统 (Permissions)

4 级权限模型控制 Agent 的行为边界：

| 级别 | 读文件 | 写文件 | 执行命令 | 网络请求 | 环境变量 |
|------|--------|--------|----------|----------|----------|
| NONE | ✗ | ✗ | ✗ | ✗ | ✗ |
| READ_ONLY | ✓ | ✗ | 白名单 | 白名单 | 白名单 |
| SANDBOX | 限定目录 | 限定目录 | 白名单 | 白名单 | 白名单 |
| FULL | ✓ | ✓ | ✓ | ✓ | ✓ |

### 使用方式

```python
from harness.core.permissions import PermissionPolicy, PermissionLevel, ResourceType

# 完全开放
policy = PermissionPolicy.full()

# 沙箱模式
policy = PermissionPolicy.sandbox(base_dir="/workspace")

# 只读模式
policy = PermissionPolicy.read_only(base_dir="/workspace")

# 自定义
policy = PermissionPolicy(
    level=PermissionLevel.SANDBOX,
    read_paths=["/workspace"],
    write_paths=["/workspace/output"],
    exec_commands=["python", "node", "ls"],
    network_hosts=["api.openai.com"],
    env_vars=["PATH", "HOME"],
)
```

## 1.3 Hooks 系统

12 个生命周期事件贯穿 Agent 的整个执行周期。

### 事件列表

| 事件名 | 触发时机 | 典型用途 |
|--------|----------|----------|
| `on_harness_start` | Harness 启动时 | 初始化资源 |
| `on_harness_stop` | Harness 停止时 | 清理资源 |
| `on_session_start` | 每个 Session 开始 | 记录 Session 元数据 |
| `on_session_end` | 每个 Session 结束 | 汇总结果 |
| `on_step_start` | 每个 Step 开始 | 注入额外上下文 |
| `on_step_end` | 每个 Step 结束 | 后处理 |
| `on_before_think` | LLM 思考前 | 注入 System Prompt |
| `on_after_think` | LLM 思考后 | 修正推理结果 |
| `on_before_action` | 执行 Action 前 | 拦截危险操作 (abort) |
| `on_after_action` | 执行 Action 后 | 修正执行结果 |
| `on_checkpoint` | 保存检查点 | 同步外部状态 |
| `on_error` | 发生错误 | 错误告警/兜底 |

### Hook 三种模式

```python
from harness.core.hooks import HookMode

# OBSERVE — 只观察不修改
hooks.register("on_step_start", my_observer, mode=HookMode.OBSERVE)

# MODIFY — 可以修改上下文数据
hooks.register("on_before_think", my_modifier, mode=HookMode.MODIFY)

# ABORT — 可以终止当前流程
hooks.register("on_before_action", my_guard, mode=HookMode.ABORT)
```

### Hook 优先级

```python
from harness.core.hooks import HookPriority

HookPriority.SYSTEM = 0   # 系统级 (权限检查)
HookPriority.PLUGIN = 50  # 插件级
HookPriority.SKILL = 75   # 技能级
HookPriority.NORMAL = 100 # 普通级
HookPriority.LATE = 200   # 用户级
```

优先级越小越先执行，同一优先级的按注册顺序执行。

## 1.4 Memory 管理

三层记忆架构：

```
Working Memory (当前Step)
    ↓ 自动摘要压缩
Episodic Memory (整个Session)
    ↓ 知识提炼
Semantic Memory (跨Session)
```

### Working Memory

管理 LLM Context Window，支持滑动窗口和自动摘要压缩：

```python
from harness.core.memory import WorkingMemory, WorkingMemoryConfig

config = WorkingMemoryConfig(
    max_tokens=128_000,       # Context window 上限
    compression_ratio=0.7,    # 触发压缩的阈值
    keep_recent_steps=5,      # 压缩时保留的最近步骤数
)
wm = WorkingMemory(config)
```

当 Token 数接近上限时自动压缩：对早期内容做摘要 → 摘要放入 System Prompt → 滑动窗口只保留最近 K 步。

### Episodic Memory

记录每个 Step 的完整历史，支持文件持久化和恢复：

```python
from harness.core.memory import EpisodicMemory

em = EpisodicMemory()
await em.start_session("session_123")
await em.record_step(step)
await em.save()  # 持久化到文件
```

### Semantic Memory

跨 Session 的知识存储，基于 TF-IDF 关键词检索：

```python
from harness.core.memory import SemanticMemory

sm = SemanticMemory()
await sm.add_knowledge("Agent loop uses 7 states", tags=["architecture"])
results = await sm.search("state machine")
```

## 1.5 Recovery (中断恢复)

Checkpoint 机制让长任务不怕中断：

```python
from harness.core.recovery import RecoveryManager

rm = RecoveryManager(checkpoint_dir=".harness/checkpoints")

# 保存 checkpoint
await rm.save(state)

# 恢复
checkpoint = await rm.load("session_123")
state = await rm.resume(checkpoint)

# 清理过期 checkpoint (默认 7 天)
rm.clean_expired()
```

恢复流程：加载 checkpoint → 重建 SessionState → 通过 Hook 注入恢复提示 → 从头开始 Loop（已知信息已注入，不会重复工作）。

## 1.6 沙箱环境 (Sandbox)

为 SANDBOX 权限级别提供隔离执行环境：

```python
from harness.core.sandbox import Sandbox

async with Sandbox() as sandbox:
    work_dir = sandbox.work_dir
    # 在沙箱内工作
    resolved = sandbox.resolve_path("test.txt")
    # /tmp/harness_sandbox_xxx/test.txt

# 沙箱退出后自动清理
```
