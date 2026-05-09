"""中断恢复 — Checkpoint 保存与恢复机制。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from harness.core.types import Action, AgentStatus, SessionState, Step


class CheckpointError(Exception):
    """Checkpoint 操作异常。"""


class Checkpoint:
    """会话检查点。"""

    def __init__(
        self,
        session_id: str,
        state: SessionState,
        pending_actions: list[Action] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.session_id = session_id
        self.timestamp = datetime.now()
        self.state = state
        self.pending_actions = pending_actions or []
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "status": self.state.status.name,
            "step_count": len(self.state.steps),
            "current_step_id": (
                self.state.current_step.id if self.state.current_step else None
            ),
            "pending_actions": [
                {"type": a.type.value, "content": a.content}
                for a in self.pending_actions
            ],
            "metadata": self.metadata,
        }


class RecoveryManager:
    """恢复管理器 — 处理 Checkpoint 的保存、加载和清理。"""

    def __init__(self, checkpoint_dir: str = ".harness/checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)

    async def save(self, state: SessionState) -> Path:
        """保存会话状态的 checkpoint。

        Args:
            state: 当前会话状态

        Returns:
            Path: checkpoint 文件路径
        """
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        file_path = self._get_path(state.session_id)
        checkpoint = Checkpoint(session_id=state.session_id, state=state)

        data = {
            "session_id": checkpoint.session_id,
            "timestamp": checkpoint.timestamp.isoformat(),
            "state": self._serialize_state(state),
            "pending_actions": [
                {"type": a.type.value, "content": a.content}
                for a in checkpoint.pending_actions
            ],
            "metadata": checkpoint.metadata,
        }

        tmp_path = file_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp_path, file_path)

        state.checkpoint_path = file_path
        return file_path

    async def load(self, session_id: str) -> Checkpoint | None:
        """加载指定会话的 checkpoint。

        Args:
            session_id: 会话 ID

        Returns:
            Checkpoint | None: checkpoint 对象，不存在时返回 None
        """
        file_path = self._get_path(session_id)
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text())
            state = self._deserialize_state(data["state"])
            checkpoint = Checkpoint(
                session_id=data["session_id"],
                state=state,
                pending_actions=[
                    Action(type=a["type"], content=a.get("content"))
                    for a in data.get("pending_actions", [])
                ],
                metadata=data.get("metadata", {}),
            )
            checkpoint.timestamp = datetime.fromisoformat(data["timestamp"])
            return checkpoint
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise CheckpointError(f"Failed to load checkpoint: {e}") from e

    async def resume(self, checkpoint: Checkpoint) -> SessionState:
        """从 checkpoint 恢复到可继续执行的状态。

        恢复策略：
        1. 标记状态为 RESUMING
        2. 已完成的 steps 保留
        3. 未完成的 current_step 标记为未完成

        Args:
            checkpoint: checkpoint 对象

        Returns:
            SessionState: 恢复后的会话状态
        """
        state = checkpoint.state
        state.status = AgentStatus.RESUMING
        state.updated_at = datetime.now()

        # 如果有未完成的 current_step，将其标记
        if state.current_step and state.current_step.completed_at is None:
            state.current_step.metadata["resumed"] = True

        return state

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """列出所有 checkpoint 的元信息。"""
        if not self.checkpoint_dir.exists():
            return []

        checkpoints = []
        for f in sorted(self.checkpoint_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                checkpoints.append({
                    "session_id": data["session_id"],
                    "timestamp": data["timestamp"],
                    "status": data["status"],
                    "step_count": data["step_count"],
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return checkpoints

    def clean_expired(self, ttl: timedelta = timedelta(days=7)) -> int:
        """清理过期的 checkpoint。

        Args:
            ttl: 过期时间，默认 7 天

        Returns:
            int: 清理的文件数
        """
        if not self.checkpoint_dir.exists():
            return 0

        now = datetime.now()
        cleaned = 0
        for f in self.checkpoint_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                ts = datetime.fromisoformat(data["timestamp"])
                if now - ts > ttl:
                    f.unlink()
                    cleaned += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                f.unlink()
                cleaned += 1
        return cleaned

    def has_checkpoint(self, session_id: str) -> bool:
        """检查指定会话是否有 checkpoint。"""
        return self._get_path(session_id).exists()

    def delete(self, session_id: str) -> bool:
        """删除指定会话的 checkpoint。"""
        path = self._get_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def _get_path(self, session_id: str) -> Path:
        return self.checkpoint_dir / f"{session_id}.json"

    def _serialize_state(self, state: SessionState) -> dict[str, Any]:
        return {
            "session_id": state.session_id,
            "status": state.status.name,
            "task": state.task,
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
                }
                for s in state.steps
            ],
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
            "metadata": state.metadata,
        }

    def _deserialize_state(self, data: dict[str, Any]) -> SessionState:
        steps = []
        for s_data in data.get("steps", []):
            step = Step(
                id=s_data["id"],
                thought=s_data.get("thought"),
                started_at=datetime.fromisoformat(s_data["started_at"]),
                completed_at=(
                    datetime.fromisoformat(s_data["completed_at"])
                    if s_data.get("completed_at")
                    else None
                ),
            )
            if s_data.get("action"):
                step.action = Action(
                    type=s_data["action"]["type"],
                    content=s_data["action"].get("content"),
                )
            steps.append(step)

        return SessionState(
            session_id=data["session_id"],
            status=AgentStatus[data["status"]],
            task=data.get("task"),
            steps=steps,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )
