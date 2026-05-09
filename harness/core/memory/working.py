"""工作记忆 — 管理 LLM Context Window，支持级联压缩管线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.core.memory.base import BaseMemory, Summary
from harness.core.memory.compressor import Compressor
from harness.core.types import LLMMessage


@dataclass
class WorkingMemoryConfig:
    """工作记忆配置。"""
    max_tokens: int = 128_000       # Context window 上限
    compression_ratio: float = 0.7  # 触发压缩的阈值 (达到 max_tokens * ratio)
    reserved_tokens: int = 2000     # 为输出保留的 token 数
    keep_recent_steps: int = 5      # 压缩时保留的最近完整 step 数
    aggressive_compress: bool = False  # 是否启用激进压缩 (LLM 摘要)


class WorkingMemory(BaseMemory):
    """工作记忆 — 管理当前 step 的 LLM 上下文。"""

    def __init__(
        self,
        config: WorkingMemoryConfig | None = None,
        compressor: Compressor | None = None,
    ):
        self.config = config or WorkingMemoryConfig()
        self._system: LLMMessage | None = None
        self._messages: list[LLMMessage] = []
        self._summary: Summary | None = None
        self._compressor = compressor or Compressor()

    async def add(self, message: LLMMessage) -> None:
        self._messages.append(message)

    async def get_context(self) -> list[LLMMessage]:
        if self._system and self._summary:
            summary_msg = LLMMessage(
                role="system",
                content=f"[Earlier context summary]: {self._summary.content}",
            )
            return [self._system, summary_msg, *self._messages]
        if self._system:
            return [self._system, *self._messages]
        return list(self._messages)

    async def clear(self) -> None:
        self._messages.clear()
        self._summary = None

    async def count_tokens(self) -> int:
        """估算当前上下文的 token 数 (粗略: 中文字符≈2, 英文≈0.4)。"""
        total = 0
        msgs = await self.get_context()
        for msg in msgs:
            if msg.content:
                total += self._estimate_tokens(msg.content)
        return total

    async def needs_compression(self) -> bool:
        """判断是否需要压缩。"""
        tokens = await self.count_tokens()
        threshold = self.config.max_tokens - self.config.reserved_tokens
        return tokens >= threshold * self.config.compression_ratio

    async def compress(self) -> Summary:
        """压缩早期内容：使用级联压缩管线。

        1. 尝试级联压缩 (Tool Budget → Snip → Microcompact → Collapse → Summary)
        2. 保留最近 K 步的完整内容
        3. 对之前的内容做摘要
        """
        if len(self._messages) <= self.config.keep_recent_steps:
            return Summary(content="")

        # 分离 system prompt
        msg_list = list(self._messages)

        # 需要被压缩的消息 = 总消息数 - 保留的最近步数
        compress_count = len(msg_list) - self.config.keep_recent_steps
        to_compress = msg_list[:compress_count]
        to_keep = msg_list[compress_count:]

        # 使用级联压缩管线
        compressed_msgs = await self._compressor.compress_messages(
            to_compress,
            aggressive=self.config.aggressive_compress,
        )

        # 如果压缩后有摘要消息，提取它
        summary_content = ""
        if compressed_msgs:
            parts = []
            for m in compressed_msgs:
                if m.content:
                    parts.append(f"[{m.role}]: {m.content[:300]}")
            summary_content = "; ".join(parts)
        else:
            raw_text = "\n".join(
                f"[{m.role}]: {m.content or ''}" for m in to_compress if m.content
            )
            summary_content = (
                f"Previous {compress_count} messages summarized. "
                f"Key points: {raw_text[:500]}..."
            )

        summary = Summary(
            content=summary_content,
            token_count=self._estimate_tokens(summary_content),
            metadata={
                "compressed_count": compress_count,
                "kept_count": len(to_keep),
                "compressor_success": len(compressed_msgs) > 0,
            },
        )

        self._summary = summary
        self._messages = to_keep
        return summary

    def set_system(self, system_message: LLMMessage) -> None:
        """设置 system prompt。"""
        self._system = system_message

    async def get_system(self) -> LLMMessage | None:
        """获取 system prompt。"""
        return self._system

    def _estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数。"""
        if not text:
            return 0
        # 中文 + 全角字符 ≈ 2 tokens/字符
        # 英文 + 数字 ≈ 0.4 tokens/字符 (实际约 0.25-0.5)
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count * 2 + int(other_count * 0.4)
