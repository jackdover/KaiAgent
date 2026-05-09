"""Auto Memory — 自动记录跨 Session 的关键信息。

功能:
  1. 自动检测 session 中的重要信息 (工具使用模式、关键发现、错误修复)
  2. 持久化到文件 (.harness/memory/auto_memory.json)
  3. 跨 session 持久化
  4. 在上下文中注入相关的历史记忆
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.core.types import LLMMessage, Step


@dataclass
class AutoMemoryEntry:
    """自动记忆条目。"""
    id: str
    content: str
    category: str  # "tool_pattern", "key_finding", "error_fix", "user_preference"
    created_at: str = ""
    access_count: int = 0
    tags: list[str] = field(default_factory=list)


class AutoMemory:
    """自动记忆 — 自动记录跨 Session 的关键信息。

    使用方式:
        memory = AutoMemory()
        await memory.record_step(step)  # 自动检测重要信息
        context = await memory.get_context()  # 获取相关记忆
    """

    def __init__(self, persist_dir: str = ".harness/memory"):
        self.persist_dir = Path(persist_dir)
        self._entries: list[AutoMemoryEntry] = []
        self._session_entries: list[str] = []  # 当前 session 添加的条目 ID
        self._id_counter = 0
        self._load()

    async def record_step(self, step: Step) -> None:
        """记录一个 step，自动检测重要信息。

        检测范围:
        - 工具调用模式 (如 "always uses read_file before write_file")
        - 错误修复 (发现 Error 然后成功)
        - 关键发现 (content > 200 chars 且有重要信息)
        """
        if not step.action:
            return

        # 检测: 错误修复
        if step.action.content and "error" in step.action.content.lower():
            # 寻找后续的修复尝试
            if step.observation and step.observation.content:
                if "success" in step.observation.content.lower() or "complete" in step.observation.content.lower():
                    entry_id = f"auto_{self._id_counter}"
                    self._id_counter += 1
                    entry = AutoMemoryEntry(
                        id=entry_id,
                        content=f"Error fix: {step.action.content[:200]}",
                        category="error_fix",
                        created_at=datetime.now().isoformat(),
                        tags=["error_fix"],
                    )
                    self._entries.append(entry)
                    self._session_entries.append(entry_id)

        # 检测: 工具调用模式
        if step.action.tool_calls:
            for tc in step.action.tool_calls:
                if tc.name in ("read_file", "write_file", "execute_command"):
                    entry_id = f"auto_{self._id_counter}"
                    self._id_counter += 1
                    args_summary = ", ".join(f"{k}={v}" for k, v in list(tc.arguments.items())[:3])
                    entry = AutoMemoryEntry(
                        id=entry_id,
                        content=f"Used {tc.name}({args_summary})",
                        category="tool_pattern",
                        created_at=datetime.now().isoformat(),
                        tags=[tc.name],
                    )
                    self._entries.append(entry)
                    self._session_entries.append(entry_id)

        # 检测: 关键发现
        if step.thought and len(step.thought) > 200:
            key_indicators = ["key takeaway", "important", "remember", "note:",
                             "发现", "关键", "注意", "总结"]
            thought_lower = step.thought.lower()
            if any(ind in thought_lower for ind in key_indicators):
                entry_id = f"auto_{self._id_counter}"
                self._id_counter += 1
                # 提取包含关键字的句子
                sentences = re.split(r'[.。!！?？\n]', step.thought)
                key_sentences = [s for s in sentences if any(ind in s.lower() for ind in key_indicators)]
                content = key_sentences[0][:300] if key_sentences else step.thought[:300]
                entry = AutoMemoryEntry(
                    id=entry_id,
                    content=content,
                    category="key_finding",
                    created_at=datetime.now().isoformat(),
                    tags=["finding"],
                )
                self._entries.append(entry)
                self._session_entries.append(entry_id)

    async def get_context(self, limit: int = 5) -> list[LLMMessage]:
        """获取最近记忆作为 LLM 上下文。"""
        if not self._entries:
            return []

        # 按访问次数降序，取最近 limit 条
        sorted_entries = sorted(
            self._entries,
            key=lambda e: e.access_count,
            reverse=True,
        )

        messages = []
        for entry in sorted_entries[:limit]:
            entry.access_count += 1
            messages.append(LLMMessage(
                role="system",
                content=f"[Auto Memory - {entry.category}]: {entry.content[:500]}",
            ))

        return messages

    async def save(self) -> None:
        """持久化记忆。"""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.persist_dir / "auto_memory.json"

        data = {
            "id_counter": self._id_counter,
            "entries": [
                {
                    "id": e.id,
                    "content": e.content,
                    "category": e.category,
                    "created_at": e.created_at,
                    "access_count": e.access_count,
                    "tags": e.tags,
                }
                for e in self._entries
            ],
        }
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self) -> None:
        """从文件加载记忆。"""
        file_path = self.persist_dir / "auto_memory.json"
        if not file_path.exists():
            return
        try:
            data = json.loads(file_path.read_text())
            self._id_counter = data.get("id_counter", 0)
            self._entries = [
                AutoMemoryEntry(
                    id=e["id"],
                    content=e["content"],
                    category=e.get("category", "unknown"),
                    created_at=e.get("created_at", ""),
                    access_count=e.get("access_count", 0),
                    tags=e.get("tags", []),
                )
                for e in data.get("entries", [])
            ]
        except (json.JSONDecodeError, KeyError):
            self._entries = []
            self._id_counter = 0

    @property
    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """清除所有记忆。"""
        self._entries.clear()
        self._session_entries.clear()
        self._id_counter = 0
