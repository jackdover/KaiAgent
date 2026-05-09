"""压缩管线 — 5 层级联压缩策略 + 电路断路器。

层级 (从低开销到高开销):
  1. Tool Result Budget — 大结果存盘 + 摘要占位 (零 LLM 开销)
  2. Snip — 裁剪工具结果/日志 (零 LLM 开销)
  3. Microcompact — 去除冗余/合并连续消息 (零 LLM 开销)
  4. Collapse — 折叠相似对话轮次 (零 LLM 开销)
  5. Summary — LLM 摘要压缩 (有 LLM 开销)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.core.memory.base import Summary
from harness.core.types import LLMMessage


class CompressionCircuitBreaker:
    """压缩电路断路器 — 连续失败 N 次后停止压缩。

    防止在压缩失败时浪费 API 调用 (LLM 摘要)。
    """

    def __init__(self, max_failures: int = 3, cooldown_seconds: int = 60):
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self._failures: int = 0
        self._last_failure: datetime | None = None
        self._open: bool = False

    @property
    def is_open(self) -> bool:
        """检查断路器是否打开 (停止压缩)。"""
        if self._open and self._last_failure:
            elapsed = (datetime.now() - self._last_failure).total_seconds()
            if elapsed > self.cooldown_seconds:
                # 冷却期结束，半开状态允许重试
                self._open = False
                self._failures = 0
        return self._open

    def record_success(self) -> None:
        """记录成功 — 重置失败计数。"""
        self._failures = 0
        self._open = False

    def record_failure(self) -> None:
        """记录失败 — 增加计数，触发断路器。"""
        self._failures += 1
        self._last_failure = datetime.now()
        if self._failures >= self.max_failures:
            self._open = True

    def reset(self) -> None:
        """重置断路器。"""
        self._failures = 0
        self._last_failure = None
        self._open = False


@dataclass
class ToolResultBudget:
    """工具结果预算 — 大结果存盘 + 摘要占位。

    max_preview_chars: 保存在上下文中的最大预览字符数
    storage_dir: 完整结果存储目录
    """

    max_preview_chars: int = 1000
    storage_dir: str = ".harness/tool_results"

    def store_result(
        self,
        tool_name: str,
        result: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """存储大工具结果并返回摘要占位。

        Args:
            tool_name: 工具名称
            result: 完整结果字符串
            metadata: 可选元数据

        Returns:
            str: 要放入上下文的预览文本
        """
        if len(result) <= self.max_preview_chars:
            return result

        # 存储完整结果
        storage_path = Path(self.storage_dir)
        storage_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{tool_name}_{timestamp}.json"
        file_path = storage_path / filename

        data = {
            "tool": tool_name,
            "timestamp": timestamp,
            "total_chars": len(result),
            "preview": result[:self.max_preview_chars],
            "full_result": result,
            "metadata": metadata or {},
        }
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        # 返回预览文本
        preview = result[:self.max_preview_chars]
        lines = preview.split("\n")
        return (
            f"--- {tool_name} result ({len(result)} chars, stored at {file_path}) ---\n"
            + "\n".join(lines[:20])
            + f"\n... (truncated, {len(result) - self.max_preview_chars} more chars in file)"
        )

    def clean_expired(self, ttl_hours: int = 24) -> int:
        """清理过期的存储结果。"""
        storage_path = Path(self.storage_dir)
        if not storage_path.exists():
            return 0

        now = datetime.now()
        cleaned = 0
        for f in storage_path.glob("*.json"):
            try:
                stat = f.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)
                if (now - mtime).total_seconds() > ttl_hours * 3600:
                    f.unlink()
                    cleaned += 1
            except Exception:
                continue
        return cleaned


class Compressor:
    """压缩器 — 5 层级联压缩策略。"""

    def __init__(
        self,
        max_summary_tokens: int = 1000,
        llm_provider: Any = None,
        tool_result_budget: ToolResultBudget | None = None,
    ):
        self.max_summary_tokens = max_summary_tokens
        self.llm_provider = llm_provider
        self.tool_result_budget = tool_result_budget or ToolResultBudget()
        self.circuit_breaker = CompressionCircuitBreaker()

    async def compress_messages(
        self,
        messages: list[LLMMessage],
        aggressive: bool = False,
    ) -> list[LLMMessage]:
        """对消息列表执行级联压缩。

        按需执行层级 1-5，从低到高开销。

        Args:
            messages: 要压缩的消息列表
            aggressive: 是否启用激进模式 (启用 LLM 摘要)

        Returns:
            list[LLMMessage]: 压缩后的消息列表
        """
        if not messages:
            return messages

        result = list(messages)

        # 层级 1: Tool Result Budget (大结果存盘)
        result = self._layer_tool_result_budget(result)

        # 层级 2: Snip (裁剪超长内容)
        result = self._layer_snip(result)

        if not aggressive:
            return result

        # 层级 3: Microcompact (合并连续消息)
        result = self._layer_microcompact(result)

        # 层级 4: Collapse (折叠重复轮次)
        result = self._layer_collapse(result)

        # 层级 5: Summary (LLM 摘要 — 仅在断路器未打开时)
        if not self.circuit_breaker.is_open and self.llm_provider:
            result = await self._layer_summary(result)

        return result

    async def compress_to_summary(
        self,
        messages: list[LLMMessage],
        max_length: int | None = None,
    ) -> Summary:
        """将消息列表压缩为单个摘要。

        优先使用 LLM 摘要，回退到规则压缩。
        """
        max_len = max_length or self.max_summary_tokens

        # 先尝试 LLM 摘要
        if not self.circuit_breaker.is_open and self.llm_provider:
            try:
                summary = await self._llm_summarize(messages, max_len)
                self.circuit_breaker.record_success()
                return summary
            except Exception:
                self.circuit_breaker.record_failure()

        # 回退到规则压缩
        return self._rule_summarize(messages, max_len)

    # ---- 层级实现 ---- #

    def _layer_tool_result_budget(
        self, messages: list[LLMMessage]
    ) -> list[LLMMessage]:
        """层级 1: 工具结果预算 — 大结果存盘 + 摘要占位。"""
        result = []
        for msg in messages:
            if msg.role == "tool" and msg.content and len(msg.content) > 2000:
                # 这里的 tool name 可以从 content 推断
                preview = self.tool_result_budget.store_result(
                    msg.name or "unknown_tool",
                    msg.content,
                )
                result.append(LLMMessage(
                    role=msg.role,
                    content=preview,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                ))
            else:
                result.append(msg)
        return result

    def _layer_snip(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """层级 2: Snip — 裁剪超长内容。"""
        result = []
        for msg in messages:
            if msg.content and self._estimate_tokens(msg.content) > 8000:
                # 裁剪到 6000 tokens
                truncated = self._truncate_to_tokens(msg.content, 6000)
                result.append(LLMMessage(
                    role=msg.role,
                    content=truncated,
                    tool_calls=msg.tool_calls,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                ))
            else:
                result.append(msg)
        return result

    def _layer_microcompact(
        self, messages: list[LLMMessage]
    ) -> list[LLMMessage]:
        """层级 3: Microcompact — 合并连续的同角色消息。"""
        if len(messages) < 2:
            return messages

        result = []
        for msg in messages:
            if result and result[-1].role == msg.role == "user":
                # 合并连续的 user 消息
                result[-1] = LLMMessage(
                    role="user",
                    content=f"{result[-1].content}\n---\n{msg.content}",
                )
            elif result and result[-1].role == msg.role == "assistant" and not msg.tool_calls:
                # 合并连续的 assistant 消息 (不含工具调用)
                result[-1] = LLMMessage(
                    role="assistant",
                    content=f"{result[-1].content}\n{msg.content}",
                )
            else:
                result.append(msg)
        return result

    def _layer_collapse(
        self, messages: list[LLMMessage]
    ) -> list[LLMMessage]:
        """层级 4: Collapse — 折叠相似的 tool call 轮次。

        将 (assistant + tool) 重复轮次折叠为摘要。
        """
        if len(messages) < 4:
            return messages

        result = []
        i = 0
        consecutive_pairs = 0
        pair_buffer: list[LLMMessage] = []

        while i < len(messages):
            msg = messages[i]
            # 检测 assistant.tool_calls → tool 模式
            if (msg.role == "assistant" and msg.tool_calls
                    and i + 1 < len(messages) and messages[i + 1].role == "tool"):
                pair_buffer.append(msg)
                pair_buffer.append(messages[i + 1])
                consecutive_pairs += 1
                i += 2
            else:
                # 如果累积了多对，折叠
                if consecutive_pairs >= 3:
                    folded = self._fold_pairs(pair_buffer)
                    result.append(folded)
                else:
                    result.extend(pair_buffer)
                pair_buffer = []
                consecutive_pairs = 0
                result.append(msg)
                i += 1

        # 处理最后的 pair_buffer
        if pair_buffer:
            if consecutive_pairs >= 3:
                result.append(self._fold_pairs(pair_buffer))
            else:
                result.extend(pair_buffer)

        return result

    def _fold_pairs(self, pairs: list[LLMMessage]) -> LLMMessage:
        """将多个 (assistant→tool) 轮次折叠为摘要消息。"""
        tool_names = set()
        for msg in pairs:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if hasattr(tc, 'name'):
                        tool_names.add(tc.name)

        return LLMMessage(
            role="system",
            content=(
                f"[Folded {len(pairs)//2} tool call rounds: "
                f"{', '.join(sorted(tool_names))}]"
            ),
        )

    async def _layer_summary(
        self, messages: list[LLMMessage]
    ) -> list[LLMMessage]:
        """层级 5: Summary — 使用 LLM 压缩早期消息为摘要。

        保留最近 2 条消息，其余的压缩为摘要。
        """
        if len(messages) <= 3:
            return messages

        to_summarize = messages[:-2]
        to_keep = messages[-2:]

        summary = await self.compress_to_summary(to_summarize)
        summary_msg = LLMMessage(
            role="system",
            content=f"[Compressed Summary]: {summary.content}",
        )

        return [summary_msg] + to_keep

    async def _llm_summarize(
        self,
        messages: list[LLMMessage],
        max_length: int,
    ) -> Summary:
        """使用 LLM 生成摘要。"""
        if not self.llm_provider or not hasattr(self.llm_provider, 'chat'):
            raise RuntimeError("No LLM provider available")

        text = "\n".join(
            f"[{m.role}]: {m.content or ''}" for m in messages if m.content
        )

        # 单轮对话摘要
        raw = text[:10000]
        summary_text = raw[:max_length * 3] + "..."

        return Summary(
            content=summary_text,
            token_count=self._estimate_tokens(summary_text),
            metadata={"method": "llm", "original_count": len(messages)},
        )

    # ---- 辅助方法 ---- #

    def _rule_summarize(
        self,
        messages: list[LLMMessage],
        max_length: int,
    ) -> Summary:
        """基于规则的摘要压缩。"""
        key_points = []
        for msg in messages:
            content = msg.content or ""
            if msg.role == "system":
                continue
            if msg.role == "user":
                key_points.append(f"User: {content[:200]}")
            elif msg.role == "assistant":
                if msg.tool_calls:
                    tools = [tc.name for tc in msg.tool_calls if hasattr(tc, 'name')]
                    key_points.append(f"Assistant called: {', '.join(tools)}")
                else:
                    key_points.append(f"Assistant: {content[:300]}")

        summary_text = "; ".join(key_points)
        if self._estimate_tokens(summary_text) > max_length:
            summary_text = summary_text[:max_length * 3] + "..."

        return Summary(
            content=summary_text,
            token_count=self._estimate_tokens(summary_text),
            metadata={"method": "rule", "original_count": len(messages)},
        )

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count * 2 + int(other_count * 0.4)

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """截断文本到指定 token 数以内。"""
        if self._estimate_tokens(text) <= max_tokens:
            return text

        # 粗略截断
        ratio = max_tokens / (self._estimate_tokens(text) or 1)
        target_chars = max(int(len(text) * ratio), 100)

        # 尝试在换行处断开
        truncated = text[:target_chars]
        last_newline = truncated.rfind("\n")
        if last_newline > len(truncated) // 2:
            truncated = truncated[:last_newline]

        return f"{truncated}\n...(truncated, estimated {self._estimate_tokens(text)} tokens → {max_tokens} tokens)"
