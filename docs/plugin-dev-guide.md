# Plugin 开发指南

## Plugin 是什么

Plugin 是技术层面的**原子能力单元**。一个 Plugin = 一组 Tool 定义 + 生命周期管理。

常见 Plugin：文件操作、Shell 命令、网络请求、数据库查询、搜索引擎、图像处理等。

## Plugin 生命周期

```
discover → load(config) → init(harness) → start() → stop() → unload()
```

| 阶段 | 方法 | 说明 |
|------|------|------|
| discover | `__init__` | Plugin 实例化 |
| load | `load(config)` | 注入配置 |
| init | `init(harness)` | 获取 Harness 引用，注册 Hook |
| start | `start()` | 启动服务（如建立连接池） |
| stop | `stop()` | 停止服务，释放资源 |
| unload | (隐式) | 销毁实例 |

## 完整 Plugin 示例

```python
from harness.plugins import Plugin, PluginMetadata, CapabilityType
from harness.core.types import ToolDefinition

class SearchPlugin(Plugin):
    metadata = PluginMetadata(
        name="search",
        version="0.1.0",
        description="搜索引擎查询",
        capabilities=[CapabilityType.TOOL, CapabilityType.SENSOR],
    )

    def __init__(self):
        self._api_key = ""
        self._harness = None

    async def load(self, config: dict):
        self._api_key = config.get("api_key", "")

    async def init(self, harness):
        self._harness = harness
        # 可选：注册权限检查 Hook
        async def check_search(ctx):
            # 实现自定义逻辑
            return ctx
        harness.register_hook("on_before_action", check_search)

    async def start(self):
        # 初始化连接池等
        pass

    async def stop(self):
        # 清理资源
        pass

    def get_tools(self) -> list[ToolDefinition]:
        """返回此 Plugin 提供的工具定义。"""
        return [
            ToolDefinition(
                name="web_search",
                description="Search the web for information",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return",
                        },
                    },
                    "required": ["query"],
                },
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict) -> str:
        """执行工具调用。"""
        if name == "web_search":
            return await self._search(arguments["query"])
        return f"Unknown tool: {name}"

    async def _search(self, query: str) -> str:
        # 实现实际的搜索逻辑
        return f"Search results for: {query}"
```

## 能力类型 (CapabilityType)

```python
class CapabilityType(str, Enum):
    TOOL = "tool"       # 执行操作 (exec git, write file)
    SENSOR = "sensor"   # 感知信息 (read file, search web)
    PROCESSOR = "proc"  # 数据处理 (transform, validate)
```

能力类型用于按类别筛选 Plugin：

```python
# 获取所有可执行操作的 Plugin
tool_plugins = registry.get_plugins_by_capability(CapabilityType.TOOL)

# 获取所有可感知信息的 Plugin
sensor_plugins = registry.get_plugins_by_capability(CapabilityType.SENSOR)
```

## Plugin 注册和发现

### 手动注册

```python
registry.register(MyPlugin())
```

### 自动发现

```python
# 扫描指定包下所有模块
discovered = registry.discover("my_plugins_package")
for plugin in discovered:
    registry.register(plugin)
```

自动发现会扫描包内所有模块，查找 `Plugin` 的非抽象子类并自动实例化。

## 最佳实践

1. **单一职责**：一个 Plugin 只做一件事（文件、Shell、网络各一个 Plugin）
2. **错误处理**：`execute_tool` 方法需捕获所有异常，返回友好的错误信息，不要抛出异常
3. **配置注入**：所有配置通过 `load(config)` 注入，不要硬编码
4. **资源管理**：`start()` 中申请资源，`stop()` 中释放资源
5. **权限感知**：在 `execute_tool` 中调用 `harness.permissions.check()` 做权限检查
6. **无状态优先**：Plugin 尽量无状态，有状态场景使用 memory 系统存储
