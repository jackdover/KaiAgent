"""情景记忆 — Session 级别的完整 Step 记录。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.core.memory.base import BaseMemory, Summary
from harness.core.types import LLMMessage, Step


@dataclass
class EpisodicMemoryConfig:
    """情景记忆配置。"""
    persist_dir: str = ".harness/memory/episodic"
    compress_threshold: int = 100  # 超过多少 step 触发摘要


class EpisodicMemory(BaseMemory):
    """情景记忆 — 存储 Step 级别的完整历史记录，支持文件持久化。"""

    def __init__(self, config: EpisodicMemoryConfig | None = None):
        self.config = config or EpisodicMemoryConfig()
        self._session_id: str | None = None
        self._steps: list[Step] = []
        self._summaries: list[Summary] = []

    async def start_session(self, session_id: str) -> None:
        """开始一个新的 session。"""
        self._session_id = session_id
        self._steps.clear()
        self._summaries.clear()

    async def record_step(self, step: Step) -> None:
        """记录一个完成的 step。"""
        self._steps.append(step)

    async def add(self, message: LLMMessage) -> None:
        """添加一条消息 (情景记忆中转为 step 的一部分，不直接使用)。"""
        pass

    async def get_context(self) -> list[LLMMessage]:
        """将情景记忆渲染为 LLM 可读的摘要上下文。

        如果 steps 过多，返回压缩后的摘要而非完整记录。
        """
        context = []
        for summary in self._summaries:
            context.append(LLMMessage(
                role="system",
                content=f"[Episode Summary]: {summary.content}",
            ))
        for step in self._steps:
            context.append(LLMMessage(
                role="assistant",
                content=step.thought or "",
            ))
            if step.observation:
                context.append(LLMMessage(
                    role="user",
                    content=step.observation.content,
                ))
        return context

    async def clear(self) -> None:
        self._steps.clear()
        self._summaries.clear()

    async def count_tokens(self) -> int:
        total = 0
        for step in self._steps:
            if step.thought:
                total += self._estimate_tokens(step.thought)
            if step.observation and step.observation.content:
                total += self._estimate_tokens(step.observation.content)
        return total

    async def needs_compression(self) -> bool:
        return len(self._steps) >= self.config.compress_threshold

    async def compress(self) -> Summary:
        """压缩情景记忆，将早期 steps 转为摘要。"""
        if not self._steps:
            return Summary(content="")

        compress_count = len(self._steps) // 2
        to_compress = self._steps[:compress_count]
        to_keep = self._steps[compress_count:]

        summary_text = self._generate_episode_summary(to_compress)
        summary = Summary(
            content=summary_text,
            token_count=self._estimate_tokens(summary_text),
            metadata={"step_count": len(to_compress)},
        )

        self._summaries.append(summary)
        self._steps = to_keep
        return summary

    async def save(self) -> None:
        """持久化情景记忆到文件。"""
        if not self._session_id:
            return

        persist_dir = Path(self.config.persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        file_path = persist_dir / f"{self._session_id}.json"

        data = {
            "session_id": self._session_id,
            "step_count": len(self._steps),
            "summaries": [{"content": s.content} for s in self._summaries],
            "steps": [
                {
                    "id": s.id,
                    "thought": s.thought,
                    "started_at": s.started_at.isoformat(),
                    "completed_at": (
                        s.completed_at.isoformat() if s.completed_at else None
                    ),
                    "action": (
                        {
                            "type": s.action.type.value,
                            "content": s.action.content,
                        }
                        if s.action
                        else None
                    ),
                    "observation": (
                        {
                            "content": s.observation.content,
                            "error": s.observation.error,
                        }
                        if s.observation
                        else None
                    ),
                }
                for s in self._steps
            ],
        }
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    async def load(self, session_id: str) -> bool:
        """从文件加载情景记忆。

        恢复保存的全部 steps (含 thought, action, observation)。
        """
        file_path = Path(self.config.persist_dir) / f"{session_id}.json"
        if not file_path.exists():
            return False

        from harness.core.types import Action, Observation

        data = json.loads(file_path.read_text())
        self._session_id = data["session_id"]
        self._summaries = [Summary(content=s["content"]) for s in data.get("summaries", [])]
        self._steps = []
        for s_data in data.get("steps", []):
            step = Step(
                id=s_data["id"],
                thought=s_data.get("thought"),
                started_at=(
                    datetime.fromisoformat(s_data["started_at"])
                    if s_data.get("started_at")
                    else datetime.now()
                ),
                completed_at=(
                    datetime.fromisoformat(s_data["completed_at"])
                    if s_data.get("completed_at")
                    else None
                ),
            )
            # 恢复 Action
            if s_data.get("action"):
                from harness.core.types import ActionType
                step.action = Action(
                    type=ActionType(s_data["action"].get("type", "text_response")),
                    content=s_data["action"].get("content"),
                )
            # 恢复 Observation
            if s_data.get("observation"):
                step.observation = Observation(
                    content=s_data["observation"].get("content", ""),
                    error=s_data["observation"].get("error"),
                )
            self._steps.append(step)
        return True

    def _generate_episode_summary(self, steps: list[Step]) -> str:
        """生成 episode 摘要。"""
        if not steps:
            return "No steps in this episode."

        thoughts = []
        for s in steps:
            thought = s.thought or ""
            truncated = thought[:200] + "..." if len(thought) > 200 else thought
            thoughts.append(f"Step {s.id}: {truncated}")
            if s.action and s.action.content:
                action_text = s.action.content[:100]
                thoughts.append(f"  Action: {action_text}")

        return "\n".join(thoughts)

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count * 2 + int(other_count * 0.4)
