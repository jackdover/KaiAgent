# Harness — 通用 Agent 运行时框架

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-103%20passed-brightgreen.svg)](tests/)

**Harness** 是一个通用的 Agent 运行时框架，为智能体提供标准化的运行、扩展和进化能力。

## 三维架构

```
┌──────────────────────────────────────────────────────┐
│                   反馈闭环 (Feedback Loop)               │
│  [Eval] ← [Attribution] ← [Abstraction] → [Optimize]   │
└──────────────────────┬───────────────────────────────┘
                       │ feeds into
┌──────────────────────▼───────────────────────────────┐
│             场景化能力层 (Skills + Plugins)              │
│    [Skills (场景组合)] ──使用──► [Plugins (原子能力)]      │
└──────────────────────┬───────────────────────────────┘
                       │ runs on
┌──────────────────────▼───────────────────────────────┐
│               通用底座 (Runtime Base)                    │
│  [Loop] [Permissions] [Hooks] [Memory] [Recovery]      │
└──────────────────────────────────────────────────────┘
```

| 维度 | 说明 |
|------|------|
| **Runtime Base** | Agent 运行时骨架 — Loop 状态机、Permissions、Hooks、Memory、Recovery |
| **Capabilities** | 能力层 — Plugins (原子能力) + Skills (场景组合) |
| **Feedback Loop** | 进化闭环 — Tracing → Eval → Attribution → Abstraction → Optimization |

## 快速开始

```bash
pip install -e .
```

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

```bash
python -m harness run "帮我读 README.md"
python -m harness config
python -m harness info
```

## 文档

完整使用指南参见 **[guide.md](guide.md)**，涵盖：

- 核心运行时详解 (Loop / Permissions / Hooks / Memory / Recovery)
- Plugin 与 Skill 开发指南
- 高级功能 (配置层次 / CLAUDE.md / Rules / 压缩管线 / 子代理)
- 反馈闭环与 Eval
- CLI 参考与完整示例

## 运行测试

```bash
pytest tests/          # 全部 103 个测试
```

## 技术栈

- **Python 3.11+** — asyncio, dataclasses
- **零外部依赖** — 核心运行时无需第三方库
- **可选依赖** — `httpx`, `PyYAML`, `pytest-asyncio`
