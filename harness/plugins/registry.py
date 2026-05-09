"""Plugin 注册中心 — 发现、加载、生命周期管理。"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

from harness.plugins.interface import CapabilityType, Plugin, PluginLoadError


class PluginRegistry:
    """Plugin 注册中心 — 管理所有 Plugin 的发现、加载和生命周期。"""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._configs: dict[str, dict[str, Any]] = {}

    # ---- 注册与发现 ----

    def register(self, plugin: Plugin, config: dict[str, Any] | None = None) -> None:
        """注册一个 Plugin 实例。"""
        name = plugin.metadata.name
        self._plugins[name] = plugin
        self._configs[name] = config or {}

    def unregister(self, name: str) -> None:
        """取消注册一个 Plugin。"""
        self._plugins.pop(name, None)
        self._configs.pop(name, None)

    def discover(self, *plugin_packages: str) -> list[Plugin]:
        """自动发现 Plugin 类。

        通过遍历指定包下的所有模块，自动实例化 Plugin 子类。

        Args:
            *plugin_packages: 要扫描的包名列表

        Returns:
            list[Plugin]: 发现并实例化的 Plugin 列表
        """
        discovered = []
        for package_name in plugin_packages:
            try:
                package = importlib.import_module(package_name)
                package_path = Path(package.__file__).parent if package.__file__ else None
                if not package_path or not package_path.is_dir():
                    continue

                # 遍历包内所有模块
                for importer, modname, ispkg in pkgutil.iter_modules([str(package_path)]):
                    if ispkg:
                        continue
                    try:
                        module = importlib.import_module(f"{package_name}.{modname}")
                        for _, obj in inspect.getmembers(module, inspect.isclass):
                            if (
                                obj is not Plugin
                                and issubclass(obj, Plugin)
                                and not inspect.isabstract(obj)
                            ):
                                plugin = obj()
                                discovered.append(plugin)
                    except Exception as e:
                        raise PluginLoadError(
                            f"Failed to load plugin module '{modname}': {e}"
                        ) from e
            except ImportError:
                continue

        return discovered

    def get_plugins_by_capability(self, cap: CapabilityType) -> list[Plugin]:
        """根据能力类型查找 Plugin。"""
        return [
            p for p in self._plugins.values()
            if cap in p.metadata.capabilities
        ]

    def get_plugin(self, name: str) -> Plugin | None:
        """根据名称获取 Plugin。"""
        return self._plugins.get(name)

    # ---- 生命周期管理 ----

    async def load_all(self) -> None:
        """加载所有已注册的 Plugin。"""
        for name, plugin in self._plugins.items():
            config = self._configs.get(name, {})
            await plugin.load(config)

    async def init_all(self, harness: Any) -> None:
        """初始化所有 Plugin。"""
        for plugin in self._plugins.values():
            await plugin.init(harness)

    async def start_all(self) -> None:
        """启动所有 Plugin。"""
        for plugin in self._plugins.values():
            await plugin.start()

    async def stop_all(self) -> None:
        """停止所有 Plugin。"""
        for plugin in self._plugins.values():
            await plugin.stop()

    # ---- 工具收集 ----

    def collect_tools(self, filter_cap: CapabilityType | None = None) -> list:
        """收集所有 Plugin 的工具定义。

        Args:
            filter_cap: 可选，只返回指定能力类型的 Plugin 的工具

        Returns:
            list: 工具定义列表
        """
        tools = []
        for plugin in self._plugins.values():
            if filter_cap and filter_cap not in plugin.metadata.capabilities:
                continue
            tools.extend(plugin.get_tools())
        return tools

    def collect_hooks(self) -> dict[str, list]:
        """收集所有 Plugin 的 Hook 注册信息。"""
        hooks: dict[str, list] = {}
        for plugin in self._plugins.values():
            plugin_hooks = plugin.get_hooks()
            for event, handlers in plugin_hooks.items():
                hooks.setdefault(event, []).extend(handlers)
        return hooks

    # ---- 查询 ----

    def list_plugins(self) -> list[dict[str, Any]]:
        """列出所有已注册 Plugin 的元信息。"""
        return [
            {
                "name": p.metadata.name,
                "version": p.metadata.version,
                "description": p.metadata.description,
                "capabilities": [c.value for c in p.metadata.capabilities],
            }
            for p in self._plugins.values()
        ]

    @property
    def count(self) -> int:
        return len(self._plugins)

    def clear(self) -> None:
        """清除所有 Plugin。"""
        self._plugins.clear()
        self._configs.clear()
