"""Memory 基类定义。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from harness.core.types import LLMMessage


@dataclass
class Summary:
    """记忆摘要。"""
    content: str
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseMemory(ABC):
    """记忆基类。"""

    @abstractmethod
    async def add(self, message: LLMMessage) -> None:
        """添加一条消息到记忆。"""
        ...

    @abstractmethod
    async def get_context(self) -> list[LLMMessage]:
        """获取当前上下文消息列表。"""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """清除记忆。"""
        ...

    @abstractmethod
    async def count_tokens(self) -> int:
        """统计当前记忆的 token 数。"""
        ...
