"""在线归因 — 定位失败根源。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from harness.feedback.tracing.tracer import Tracer

RootCause = Literal[
    "llm_reasoning",
    "tool_error",
    "permission",
    "timeout",
    "skill_config",
    "plugin_bug",
    "unknown",
]


@dataclass
class Attribution:
    """归因结果 — 定位到问题根源。"""
    trace_id: str = ""
    root_cause: RootCause = "unknown"
    failed_component: str = ""
    failed_step: str = ""
    error_detail: str = ""
    suggestion: str = ""
    confidence: float = 0.0  # 0.0 ~ 1.0
    spans: list[dict] = field(default_factory=list)


class AttributionAnalyzer:
    """归因分析器 — 根据 Trace 数据定位失败原因。"""

    def analyze(self, tracer: Tracer) -> Attribution:
        """对一次追踪进行归因分析。

        分析流程:
        1. 找到所有 error 状态的 Span
        2. 分析错误层次 (step → action → plugin)
        3. 定位最低层级的错误作为 root cause
        4. 生成修复建议

        Args:
            tracer: 已完成追踪的 Tracer 实例

        Returns:
            Attribution: 归因结果
        """
        trace_id = tracer.trace_id or ""
        error_spans = tracer.get_error_spans()

        if not error_spans:
            return Attribution(
                trace_id=trace_id,
                root_cause="unknown",
                suggestion="No errors found in trace.",
            )

        # 按层级分析错误
        # 从最深的 Span 开始 (没有子 Span 的 error span)
        span_ids = {s.span_id for s in error_spans}
        span_children: dict[str, list] = {}
        for s in tracer._spans:
            pid = s.parent_id or ""
            if pid not in span_ids and s.status == "error":
                span_children.setdefault(pid, []).append(s)

        # 找到最深层的 error span
        deepest_error = self._find_deepest_error(tracer, error_spans)

        attribution = self._classify_error(deepest_error)
        attribution.trace_id = trace_id
        attribution.spans = [s.to_dict() for s in error_spans]

        return attribution

    def analyze_step(self, tracer: Tracer, step_id: str) -> Attribution | None:
        """分析单个 Step 的归因。"""
        for s in tracer._spans:
            if s.span_id == step_id or s.name == step_id:
                if s.status == "error":
                    attribution = self._classify_error(s)
                    attribution.trace_id = tracer.trace_id or ""
                    attribution.failed_step = step_id
                    return attribution
        return None

    def _find_deepest_error(self, tracer: Tracer, error_spans: list) -> Any:
        """找到最深层的错误 Span。"""
        if not error_spans:
            return None

        # 构建 parent→children 映射
        children_map: dict[str, list] = {}
        for s in tracer._spans:
            pid = s.parent_id or ""
            children_map.setdefault(pid, []).append(s)

        def depth(s) -> int:
            d = 0
            pid = s.parent_id
            while pid:
                d += 1
                parent = next(
                    (x for x in tracer._spans if x.span_id == pid), None
                )
                pid = parent.parent_id if parent else None
            return d

        return max(error_spans, key=depth)

    def _classify_error(self, error_span) -> Attribution:
        """根据错误 Span 分类 root cause。"""
        if error_span is None:
            return Attribution(root_cause="unknown")

        name = error_span.name.lower()
        error_msg = (error_span.error or "").lower()
        span_type = error_span.span_type

        # 权限错误 (优先级最高)
        if "permission" in error_msg or "denied" in error_msg:
            return Attribution(
                root_cause="permission",
                failed_component=name,
                error_detail=error_span.error or "",
                suggestion="检查权限配置，确认需要放行的资源",
                confidence=0.9,
            )

        # 超时错误
        if "timeout" in error_msg:
            return Attribution(
                root_cause="timeout",
                failed_component=name,
                error_detail=error_span.error or "",
                suggestion="增加 timeout 或将大任务拆分为小步骤",
                confidence=0.8,
            )

        # 工具/插件错误
        if span_type in ("plugin", "action") or name.startswith("tool_"):
            return Attribution(
                root_cause="tool_error",
                failed_component=name,
                error_detail=error_span.error or "",
                suggestion="检查工具参数和 API 状态",
                confidence=0.7,
            )

        # LLM 推理错误
        if span_type in ("think", "step"):
            return Attribution(
                root_cause="llm_reasoning",
                failed_component=name,
                error_detail=error_span.error or "",
                suggestion="优化 system prompt，补充更多上下文或示例",
                confidence=0.6,
            )

        return Attribution(
            root_cause="unknown",
            failed_component=name,
            error_detail=error_span.error or "",
            suggestion="请手动检查错误详情",
            confidence=0.3,
        )
