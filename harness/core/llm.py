"""LLM 调用抽象 — 让 Harness 不绑定具体 LLM 提供商。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from harness.core.types import LLMMessage, LLMResponse, ToolDefinition


class LLMProvider(ABC):
    """LLM 提供商抽象接口。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """发送对话请求并返回响应。"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ):
        """流式对话请求。"""
        ...


class TokenCounter(Protocol):
    """Token 计数协议。"""
    def count(self, text: str) -> int: ...


class LLMConfig:
    """LLM 配置。"""
    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        max_context_tokens: int = 128_000,
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_context_tokens = max_context_tokens
