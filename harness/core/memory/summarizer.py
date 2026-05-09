"""自动摘要压缩 — 利用 LLM 或规则算法压缩上下文。"""

from __future__ import annotations

from typing import Any

from harness.core.memory.base import Summary
from harness.core.types import LLMMessage, Step


class Summarizer:
    """摘要压缩器 — 将长历史压缩为简短摘要。"""

    def __init__(self, max_summary_tokens: int = 1000):
        self.max_summary_tokens = max_summary_tokens

    async def summarize_messages(
        self,
        messages: list[LLMMessage],
        max_length: int | None = None,
    ) -> Summary:
        """将消息列表压缩为摘要。

        当没有 LLM provider 时，使用基于规则的压缩。
        """
        max_len = max_length or self.max_summary_tokens

        # 规则压缩：提取关键信息
        key_points = []
        for msg in messages:
            content = msg.content or ""
            if msg.role == "system":
                continue
            if msg.role == "user":
                key_points.append(f"User: {content[:200]}")
            elif msg.role == "assistant":
                key_points.append(f"Assistant: {content[:300]}")

        summary_text = "; ".join(key_points)
        if self._estimate_tokens(summary_text) > max_len:
            summary_text = summary_text[:max_len * 3] + "..."

        return Summary(
            content=summary_text,
            token_count=self._estimate_tokens(summary_text),
        )

    async def summarize_steps(
        self,
        steps: list[Step],
        max_length: int | None = None,
    ) -> Summary:
        """将一系列 Steps 压缩为摘要。"""
        max_len = max_length or self.max_summary_tokens

        parts = []
        for s in steps:
            thought = (s.thought or "")[:200]
            action = (s.action.content or "")[:100] if s.action else ""
            result = (s.observation.content or "")[:100] if s.observation else ""
            parts.append(f"[{s.id}] Thought: {thought} | Act: {action} | Obs: {result}")

        summary_text = "\n".join(parts)
        if self._estimate_tokens(summary_text) > max_len:
            summary_text = summary_text[:max_len * 3] + "..."

        return Summary(
            content=summary_text,
            token_count=self._estimate_tokens(summary_text),
        )

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count * 2 + int(other_count * 0.4)
