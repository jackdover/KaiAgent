"""内置 Plugin: LLM Provider — 将 LLM 调用封装为 Plugin。"""

from __future__ import annotations

from typing import Any

from harness.plugins.interface import CapabilityType, Plugin, PluginMetadata
from harness.core.llm import LLMConfig
from harness.core.types import LLMMessage, LLMResponse, ToolDefinition


class LLMProviderPlugin(Plugin):
    """LLM Provider Plugin — 不绑定具体 LLM 的 Provider 封装。"""

    metadata = PluginMetadata(
        name="llm_provider",
        version="0.1.0",
        description="LLM provider abstraction: chat completion with configurable backends",
        capabilities=[CapabilityType.PROCESSOR],
    )

    def __init__(self):
        self._llm: Any = None  # LLMProvider instance
        self._config: LLMConfig | None = None
        self._harness: Any = None

    async def load(self, config: dict[str, Any]) -> None:
        self._config = LLMConfig(
            provider=config.get("provider", "openai"),
            model=config.get("model", "gpt-4o"),
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            max_tokens=config.get("max_tokens", 4096),
            temperature=config.get("temperature", 0.7),
        )

    async def init(self, harness: Any) -> None:
        self._harness = harness
        # 在 init 中设置 LLM 到 Agent Loop
        if hasattr(harness, '_loop') and harness._loop:
            # 设置 LLM Provider (需要外部注册，见 set_provider)
            pass

    def set_provider(self, provider: Any) -> None:
        """设置 LLM Provider 实现。"""
        self._llm = provider

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        """代理调用到实际的 LLM Provider。"""
        if self._llm is None:
            return LLMResponse(
                content="No LLM provider configured. "
                        "Use set_provider() to register one.",
                finish_reason="stop",
            )
        return await self._llm.chat(messages=messages, tools=tools)

    def get_hooks(self) -> dict[str, list]:
        return {}
