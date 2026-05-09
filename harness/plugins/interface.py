"""Plugin 接口定义 — 原子能力单元。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from harness.core.types import ToolDefinition


class CapabilityType(str, Enum):
    """Plugin 能力类型。"""
    TOOL = "tool"          # 执行操作 (exec git, write file)
    SENSOR = "sensor"      # 感知信息 (read file, search web)
    PROCESSOR = "proc"     # 数据处理 (transform, validate)


@dataclass
class PluginMetadata:
    """Plugin 元数据。"""
    name: str
    version: str = "0.1.0"
    description: str = ""
    capabilities: list[CapabilityType] = field(default_factory=list)
    author: str = ""
    homepage: str = ""


class Plugin(ABC):
    """Plugin 基类 — 所有 Plugin 必须实现此接口。

    生命周期:
        discover → load(config) → init(harness) → start() → stop() → unload()
    """

    metadata: PluginMetadata

    @abstractmethod
    async def load(self, config: dict[str, Any]) -> None:
        """加载配置。"""
        ...

    @abstractmethod
    async def init(self, harness: Any) -> None:
        """初始化，获取 Harness 引用并注册 Hook。"""
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动 Plugin，开始服务。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止 Plugin，释放资源。"""
        ...

    def get_tools(self) -> list[ToolDefinition]:
        """返回此 Plugin 提供的工具定义列表。"""
        return []

    def get_hooks(self) -> dict[str, list]:
        """返回此 Plugin 要注册的 Hook 映射。"""
        return {}


class PluginLoadError(Exception):
    """Plugin 加载异常。"""


class PluginInitError(Exception):
    """Plugin 初始化异常。"""
