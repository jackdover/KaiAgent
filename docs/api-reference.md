# API 参考

## Harness (顶层入口)

### `Harness(config=None)`

创建 Harness 实例。

- **config**: `HarnessConfig | None` — 配置对象，默认使用 `HarnessConfig.default()`

### 生命周期方法

#### `async start()`

启动 Harness，初始化所有子系统。包括：
1. Hook 系统
2. 权限系统
3. Plugin 系统（加载内置 Plugin + 自动发现）
4. 记忆系统（Working + Episodic）
5. 恢复管理器
6. Agent Loop

#### `async stop()`

停止 Harness，清理资源。包括：
1. 发射 `on_harness_stop` 事件
2. 停止所有 Plugin

#### `async run(task, session_id=None) -> SessionResult`

运行一个任务。

- **task**: `str` — 用户任务描述
- **session_id**: `str | None` — 可选的 Session ID（用于恢复中断的任务）
- **返回**: `SessionResult` — 执行结果

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `hooks` | `HookRegistry` | Hook 注册中心 |
| `permissions` | `PermissionPolicy` | 权限策略 |
| `loop` | `AgentLoop` | Agent 循环 |
| `plugins` | `PluginRegistry` | Plugin 注册中心 |
| `skills` | `SkillRegistry` | Skill 注册中心 |

### 注册方法

#### `register_hook(event, fn, priority=100)`

注册一个 Hook。

- **event**: `str` — 事件名（必须是 HOOK_EVENTS 中的值）
- **fn**: `async (HookContext) -> HookContext` — 回调函数
- **priority**: `int` — 执行优先级

#### `register_plugin(plugin)`

注册一个 Plugin 实例。

- **plugin**: `Plugin` — Plugin 实例

#### `register_skill(skill)`

注册一个 Skill。

- **skill**: `Skill` — Skill 实例

### 其他方法

#### `is_running() -> bool`

检查 Harness 是否正在运行。

---

## core.types — 核心类型

### `AgentStatus`

Agent 会话生命周期状态枚举。

| 值 | 说明 |
|------|------|
| `INIT` | 初始化 |
| `IDLE` | 空闲 |
| `THINKING` | 推理中 |
| `ACTING` | 执行中 |
| `OBSERVING` | 观察中 |
| `CHECKPOINT` | 保存检查点 |
| `RESUMING` | 恢复中 |
| `ERROR` | 错误 |
| `DONE` | 完成 |

### `Action`

Agent 产出的动作。

- `type`: `ActionType` — 动作类型 (TOOL_CALL / TEXT_RESPONSE / FINISH)
- `content`: `str | None` — 文本内容
- `tool_calls`: `list[ToolCall]` — 工具调用列表

### `Step`

一个完整的 think→act→observe 步骤。

- `id`: `str` — Step ID
- `thought`: `str | None` — 推理内容
- `action`: `Action | None` — 执行的动作
- `observation`: `Observation | None` — 观察结果

### `SessionResult`

会话执行结果。

- `session_id`: `str`
- `status`: `AgentStatus`
- `steps`: `list[Step]`
- `output`: `str | None`
- `error`: `str | None`
- `total_duration`: `float`

### `ToolDefinition`

工具定义 (OpenAI Function Calling 格式兼容)。

- `name`: `str` — 工具名
- `description`: `str` — 描述
- `parameters`: `dict` — JSON Schema 参数定义

---

## core.hooks — Hooks 系统

### `HookRegistry`

#### `register(event, fn, priority, mode) -> None`

注册 Hook。

- **event**: `str` — 必须是 `HOOK_EVENTS` 中的值
- **fn**: `async (HookContext) -> HookContext | None`
- **priority**: `int` — 默认 `HookPriority.NORMAL` (100)
- **mode**: `HookMode` — 默认 `HookMode.OBSERVE`

#### `async emit(event, data) -> HookContext`

发射事件。

- **event**: `str`
- **data**: `Any`
- **返回**: `HookContext` — 经过所有 Hook 处理后的上下文
- **抛出**: `HookAbortError` — 如果有 ABORT 模式 Hook 中止流程

#### `unregister(event, fn) -> None`

取消注册。

---

## core.permissions — 权限系统

### `PermissionPolicy`

#### `check(resource_type, resource) -> None`

检查权限。

- **resource_type**: `ResourceType | str` — 资源类型枚举或字符串
- **resource**: `str` — 资源标识
- **抛出**: `PermissionDenied`

#### 工厂方法

- `PermissionPolicy.full()` — 完全信任
- `PermissionPolicy.sandbox(base_dir)` — 沙箱模式
- `PermissionPolicy.read_only(base_dir)` — 只读模式

---

## plugins — Plugin 系统

### `PluginRegistry`

#### `register(plugin, config) -> None`

注册 Plugin。

#### `discover(*plugin_packages) -> list[Plugin]`

自动发现 Plugin。

#### `collect_tools() -> list[ToolDefinition]`

收集所有 Plugin 的 Tool。

#### `get_plugins_by_capability(cap) -> list[Plugin]`

按能力类型查询。

#### `lifecycle: load_all() → init_all(harness) → start_all() → stop_all()`

批量生命周期管理。

---

## skills — Skill 系统

### `SkillRegistry`

#### `register(skill) -> None`

注册 Skill。

#### `select_skill(task) -> Skill | None`

选择匹配的 Skill。

#### `match_skills(task) -> list[Skill]`

返回所有匹配的 Skill。

---

## feedback.eval — 评估框架

### `EvalCase`

- `id`: `str`
- `name`: `str`
- `input`: `str` — 输入
- `expected`: `Any` — 期望输出
- `judge`: `str` — Judge 类型: "exact" | "substring" | "keyword" | "llm"

### `EvalRunner`

- `async run_suite(suite) -> EvalReport`
- `async run_single(case, output) -> EvalResult`

---

## feedback.tracing — 全链路追踪

### `Tracer`

- `start_trace(trace_id) -> str`
- `start_span(name, span_type, payload) -> Span`
- `end_span(span, status, error)`
- `span(name, span_type)` — 上下文管理器
- `export() -> dict`
- `save()` — 持久化
- `build_tree() -> list`

---

## feedback.attribution — 在线归因

### `AttributionAnalyzer`

- `analyze(tracer) -> Attribution`

---

## feedback.optimization — 迭代优化

### `Optimizer`

- `analyze_pattern(pattern) -> OptimizationSuggestion`
- `get_top_suggestions(limit) -> list`
