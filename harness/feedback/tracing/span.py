"""Span 定义 — 全链路追踪的最小单元。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

SpanType = Literal["step", "think", "action", "observation", "hook", "skill", "plugin"]
SpanStatus = Literal["ok", "error", "cancelled"]


@dataclass
class Span:
    """追踪跨度 — 记录一个可观测的操作单元。

    整个 Session 形成一棵 Span 树:
        session (root)
        ├── step_1
        │   ├── think
        │   ├── action
        │   │   ├── tool_call_1 (plugin)
        │   │   └── tool_call_2 (plugin)
        │   └── observation
        ├── step_2
        │   └── ...
        └── hook_events
    """

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    span_type: SpanType
    started_at: datetime
    ended_at: datetime | None = None
    status: SpanStatus = "ok"
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        trace_id: str,
        name: str,
        span_type: SpanType,
        parent_id: str | None = None,
        payload: dict | None = None,
    ) -> Span:
        """创建一个新的 Span。"""
        return cls(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:12],
            parent_id=parent_id,
            name=name,
            span_type=span_type,
            started_at=datetime.now(),
            payload=payload or {},
        )

    def end(self, status: SpanStatus = "ok", error: str | None = None) -> None:
        """结束 Span。"""
        self.ended_at = datetime.now()
        self.status = status
        self.error = error

    @property
    def duration_ms(self) -> float:
        """返回持续时间(毫秒)。"""
        if self.ended_at is None:
            return 0.0
        return (self.ended_at - self.started_at).total_seconds() * 1000

    @property
    def is_completed(self) -> bool:
        return self.ended_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "span_type": self.span_type,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "payload": self.payload,
        }
