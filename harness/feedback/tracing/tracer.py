"""Tracer 实现 — 全链路追踪管理器。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.feedback.tracing.span import Span, SpanType


class Tracer:
    """全链路追踪器 — 管理 Span 的创建、存储和导出。

    使用方式:
        tracer = Tracer()
        tracer.start_trace()
        with tracer.span("step_1", "step") as span:
            ...
        report = tracer.export()
    """

    def __init__(self, persist_dir: str = ".harness/traces"):
        self.persist_dir = Path(persist_dir)
        self._trace_id: str | None = None
        self._spans: list[Span] = []
        self._stack: list[str] = []  # parent_id stack

    # ---- 生命周期 ----

    def start_trace(self, trace_id: str | None = None) -> str:
        """开始一个新的追踪。

        Args:
            trace_id: 可选的 trace ID

        Returns:
            str: trace_id
        """
        self._trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        self._spans.clear()
        self._stack.clear()
        return self._trace_id

    @property
    def trace_id(self) -> str | None:
        return self._trace_id

    # ---- Span 管理 ----

    def start_span(
        self,
        name: str,
        span_type: SpanType,
        payload: dict | None = None,
    ) -> Span:
        """开始一个新的 Span。"""
        assert self._trace_id is not None, "No active trace. Call start_trace() first."

        parent_id = self._stack[-1] if self._stack else None
        span = Span.create(
            trace_id=self._trace_id,
            name=name,
            span_type=span_type,
            parent_id=parent_id,
            payload=payload,
        )
        self._spans.append(span)
        self._stack.append(span.span_id)
        return span

    def end_span(self, span: Span, status: str = "ok", error: str | None = None) -> None:
        """结束一个 Span。"""
        span.end(status=status, error=error)
        if self._stack and self._stack[-1] == span.span_id:
            self._stack.pop()

    def span(self, name: str, span_type: SpanType, payload: dict | None = None):
        """创建一个上下文管理器风格的 Span。"""
        return _SpanContext(self, name, span_type, payload)

    # ---- 查询 ----

    def get_spans(self, span_type: SpanType | None = None) -> list[Span]:
        """获取所有 Span, 可选按类型过滤。"""
        if span_type is None:
            return list(self._spans)
        return [s for s in self._spans if s.span_type == span_type]

    def get_spans_by_name(self, name: str) -> list[Span]:
        """按名称查找 Span。"""
        return [s for s in self._spans if s.name == name]

    def get_error_spans(self) -> list[Span]:
        """获取所有出错的 Span。"""
        return [s for s in self._spans if s.status == "error"]

    def build_tree(self) -> list[dict[str, Any]]:
        """构建 Span 树。"""
        children_map: dict[str, list[Span]] = {}
        for s in self._spans:
            pid = s.parent_id or ""
            children_map.setdefault(pid, []).append(s)

        def build_node(span_id: str) -> dict[str, Any] | None:
            if span_id == "":
                return None
            span = next((s for s in self._spans if s.span_id == span_id), None)
            if span is None:
                return None
            return {
                "span": span.to_dict(),
                "children": [
                    build_node(c.span_id) for c in children_map.get(span_id, [])
                ],
            }

        roots = children_map.get("", [])
        return [
            {
                "span": root.to_dict(),
                "children": [
                    build_node(c.span_id)
                    for c in children_map.get(root.span_id, [])
                ],
            }
            for root in roots
        ]

    # ---- 持久化 ----

    def save(self) -> Path:
        """保存追踪结果到文件。"""
        if not self._trace_id:
            raise ValueError("No trace to save")

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.persist_dir / f"{self._trace_id}.json"

        data = {
            "trace_id": self._trace_id,
            "span_count": len(self._spans),
            "spans": [s.to_dict() for s in self._spans],
        }
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return file_path

    def load(self, trace_id: str) -> bool:
        """从文件加载追踪数据。"""
        file_path = self.persist_dir / f"{trace_id}.json"
        if not file_path.exists():
            return False

        data = json.loads(file_path.read_text())
        self._trace_id = data["trace_id"]
        self._spans.clear()
        for s_data in data["spans"]:
            span = Span(
                trace_id=s_data["trace_id"],
                span_id=s_data["span_id"],
                parent_id=s_data.get("parent_id"),
                name=s_data["name"],
                span_type=s_data["span_type"],
                started_at=datetime.fromisoformat(s_data["started_at"]),
                ended_at=(
                    datetime.fromisoformat(s_data["ended_at"])
                    if s_data.get("ended_at")
                    else None
                ),
                status=s_data.get("status", "ok"),
                error=s_data.get("error"),
                payload=s_data.get("payload", {}),
            )
            self._spans.append(span)
        return True

    # ---- 导出 ----

    def export(self) -> dict[str, Any]:
        """导出完整追踪报告。"""
        error_spans = self.get_error_spans()
        return {
            "trace_id": self._trace_id,
            "span_count": len(self._spans),
            "error_count": len(error_spans),
            "total_duration_ms": sum(s.duration_ms for s in self._spans),
            "spans": [s.to_dict() for s in self._spans],
        }

    def clear(self) -> None:
        """清除所有 Span。"""
        self._spans.clear()
        self._stack.clear()
        self._trace_id = None


class _SpanContext:
    """上下文管理器风格的 Span。"""

    def __init__(self, tracer: Tracer, name: str, span_type: SpanType, payload: dict | None):
        self.tracer = tracer
        self.name = name
        self.span_type = span_type
        self.payload = payload

    async def __aenter__(self) -> Span:
        self.span = self.tracer.start_span(self.name, self.span_type, self.payload)
        return self.span

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.tracer.end_span(self.span, status="error", error=str(exc_val))
        else:
            self.tracer.end_span(self.span)
