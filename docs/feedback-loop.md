# Dimension 3: 反馈闭环 (Feedback Loop)

反馈闭环让 Harness Agent 持续优化进化。它由 5 个阶段组成：

```
线上运行 → Tracing → Attribution → Abstraction → Optimization → Eval → 部署上线
```

## 全链路数据流

```
线上运行 (Agent 执行任务)
    │
    ▼
┌──────────────┐      trace_id      ┌──────────────┐
│   Tracer     │──────────────────►│  Trace Store  │
│  (Span Tree) │                   │  (JSON文件)   │
└──────┬───────┘                   └──────┬────────┘
       │                                  │
       ▼                                  ▼
┌──────────────┐                  ┌──────────────┐
│ Attribution  │◄────────────────│  Trace Data   │
│  Analyzer    │                  │              │
└──────┬───────┘                  └──────────────┘
       │
       ▼
┌──────────────┐
│   Pattern    │
│  Extractor   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Optimizer   │
└──────┬───────┘
       │
       ▼
┌──────────────┐          ┌──────────────┐
│  EvalRunner  │◄────────│  Eval Suite   │
│              │          │  (TestCase)   │
└──────────────┘          └──────────────┘
       │
       ▼
   部署上线
```

## 5.1 全链路追踪 (Tracing)

每次 Session 产生一棵 Span 树，记录所有操作的完整链路。

### Span 树结构

```
session (root span)
├── step_1
│   ├── think
│   ├── action
│   │   ├── tool_call_1 (plugin: file.read_file)
│   │   └── tool_call_2 (plugin: shell.execute_command)
│   └── observation
├── step_2
│   └── ...
└── hook_events
```

### 使用方式

```python
from harness.feedback.tracing import Tracer

tracer = Tracer()
tracer.start_trace("my_session")

async with tracer.span("step_1", "step") as span:
    async with tracer.span("think_1", "think") as think_span:
        # LLM 思考...
        pass
    async with tracer.span("action_1", "action") as act_span:
        # 执行工具调用...
        pass

# 导出报告
report = tracer.export()
print(f"Total spans: {report['span_count']}")
print(f"Error count: {report['error_count']}")

# 保存到文件
tracer.save()

# 构建 Span 树
tree = tracer.build_tree()
```

## 5.2 评估框架 (Eval)

三层评估体系：

| 级别 | 对象 | 方法 | 指标 |
|------|------|------|------|
| 单元级 | 单个 Skill/Plugin | 单测 + LLM-as-Judge | 准确率 |
| 场景级 | 端到端 Skill 链路 | 场景测试集 | 成功率 |
| 全链路级 | 完整 Session | 完整任务测试 | 综合评分 |

### 定义测试用例

```python
from harness.feedback.eval import EvalCase, EvalSuite

suite = EvalSuite(name="code_review")
suite.add_case(EvalCase(
    id="cr_001",
    name="basic code review",
    input="review this: function add(a,b){return a+b}",
    expected="good",
    skill="code_review",
    judge="exact",
    tags=["basic", "code_review"],
))
```

### 4 种评判器

```python
from harness.feedback.eval.judges.exact import ExactJudge, SubstringJudge, KeywordJudge

await ExactJudge.judge("hello world", "hello world")   # True, 1.0
await SubstringJudge.judge("hello world", "world")      # True, 1.0
await KeywordJudge.judge("python is great",             # True, 0.67
    ["python", "data", "javascript"])
```

### 运行评估

```python
from harness.feedback.eval import EvalRunner

runner = EvalRunner(harness=h)
report = await runner.run_suite(suite)

runner.print_report(report)
# ==================================================
# Eval Report: code_review
# ==================================================
# Total: 10  |  Passed: 8  |  Failed: 2  |  Rate: 80.0%
# ==================================================
```

## 5.3 在线归因 (Attribution)

当任务失败时，自动定位故障根因。

### 7 种根因分类

| 根因 | 说明 | 置信度 |
|------|------|--------|
| `llm_reasoning` | LLM 推理错误 | 0.6 |
| `tool_error` | 工具调用失败 | 0.7 |
| `permission` | 权限不足 | 0.9 |
| `timeout` | 操作超时 | 0.8 |
| `skill_config` | Skill 配置问题 | 0.5 |
| `plugin_bug` | Plugin 实现缺陷 | 0.7 |
| `unknown` | 无法归类 | 0.3 |

### 归因分析

```python
from harness.feedback.attribution import AttributionAnalyzer

analyzer = AttributionAnalyzer()
attribution = analyzer.analyze(tracer)

print(f"根因: {attribution.root_cause}")
print(f"组件: {attribution.failed_component}")
print(f"建议: {attribution.suggestion}")
```

## 5.4 问题抽象 (Abstraction)

将相似的失败案例归纳为 Failure Pattern，自动去重和聚合。

```python
from harness.feedback.abstraction import PatternExtractor

extractor = PatternExtractor()
pattern = extractor.extract(attribution)
print(f"模式ID: {pattern.pattern_id}")
print(f"频率: {pattern.frequency}")  # 自动累加

top_patterns = extractor.get_top_patterns(limit=5)
```

## 5.5 迭代优化 (Optimization)

根据 Failure Pattern 自动生成改进方案。

### 6 类优化目标

| 目标 | 说明 | 可自动应用 |
|------|------|-----------|
| `prompt_template` | 优化 System Prompt | ✗ |
| `tool_config` | 调整工具配置 | ✗ |
| `skill_logic` | 修改 Skill 逻辑 | ✗ |
| `plugin_impl` | 修复 Plugin 实现 | ✗ |
| `permission_policy` | 调整权限策略 | ✓ |
| `runtime_config` | 修改运行时配置 | ✓ |

### 生成优化建议

```python
from harness.feedback.optimization import Optimizer

optimizer = Optimizer()
suggestion = optimizer.analyze_pattern(pattern)

print(f"目标: {suggestion.target}")
print(f"描述: {suggestion.description}")
print(f"行动项: {suggestion.action_items}")
print(f"优先级: {suggestion.priority}")
print(f"可自动应用: {suggestion.auto_applicable}")
```

## 5.6 集成使用

### FeedbackIntegrator

一键集成反馈闭环到 Harness：

```python
from harness.feedback.integration import FeedbackIntegrator

h = Harness()
await h.start()

feedback = FeedbackIntegrator()
trace_id = feedback.start_trace()

result = await h.run("some task")

analysis = feedback.end_trace_and_analyze()
if analysis["status"] == "analyzed":
    attr = analysis["attribution"]
    print(f"Root cause: {attr.root_cause}")
    print(f"Suggestion: {attr.suggestion}")

# 获取反馈系统摘要
summary = feedback.get_summary()
print(f"Patterns: {summary['patterns']}")

await h.stop()
```
