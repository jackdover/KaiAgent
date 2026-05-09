# 配置参考

## HarnessConfig

全局配置对象，控制 Harness 的所有行为。

### 默认配置

```python
from harness.config.schema import HarnessConfig

config = HarnessConfig.default()
print(config)
```

或通过 CLI 查看：

```bash
python -m harness config
```

### 配置字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `"harness"` | 实例名称 |
| `max_steps` | `int` | `50` | 最大循环步数 |
| `permission_level` | `PermissionLevel` | `SANDBOX` | 权限级别 |
| `permission` | `dict` | `{}` | 自定义权限策略 |

### LLM 配置

```python
config.llm.provider   # "openai"
config.llm.model      # "gpt-4o"
config.llm.api_key    # None
config.llm.base_url   # None
config.llm.max_tokens # 4096
config.llm.temperature # 0.7
```

### 记忆配置

```python
config.memory.working_max_tokens    # 128000
config.memory.episodic_persist_dir  # ".harness/memory/episodic"
config.memory.semantic_enabled      # False
```

### 恢复配置

```python
config.recovery.checkpoint_dir      # ".harness/checkpoints"
config.recovery.checkpoint_interval # 3 (每N步保存一次)
config.recovery.checkpoint_ttl_days # 7 (过期天数)
```

### Plugin 配置

```python
config.plugins.auto_discover  # True
config.plugins.builtin_enabled # True
config.plugins.extra_paths    # []
```

### Eval 配置

```python
config.eval.enabled       # False
config.eval.suites_dir    # ".harness/eval/suites"
config.eval.results_dir   # ".harness/eval/results"
```

## YAML 配置

`config/defaults.yaml` 中定义了默认配置，可以创建自定义配置覆盖：

```yaml
# my_config.yaml
name: "production"
max_steps: 100
permission_level: "SANDBOX"

llm:
  provider: "openai"
  model: "gpt-4o"
  temperature: 0.3

memory:
  working_max_tokens: 64000
```

## 编程方式配置

```python
from harness.config.schema import HarnessConfig
from harness.core.permissions import PermissionLevel

config = HarnessConfig.default()
config.max_steps = 20
config.permission_level = PermissionLevel.SANDBOX
config.permission = {
    "read_paths": ["/workspace/src"],
    "write_paths": ["/workspace/output"],
    "exec_commands": ["python", "pytest"],
}

from harness import Harness
h = Harness(config=config)
await h.start()
```
