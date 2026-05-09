"""反馈闭环与 Runtime 集成 — 自动追踪、评估和优化。"""

from __future__ import annotations

from typing import Any

from harness.feedback.tracing import Tracer
from harness.feedback.eval import EvalRunner, EvalSuite, EvalReport
from harness.feedback.attribution import AttributionAnalyzer, Attribution
from harness.feedback.abstraction import PatternExtractor, FailurePattern
from harness.feedback.optimization import Optimizer, OptimizationSuggestion


class FeedbackIntegrator:
    """反馈闭环集成器 — 将反馈系统自动接入 Harness Runtime。

    在每个 Session 执行完毕后自动:
    1. 收集 Trace 数据
    2. 归因分析 (如有错误)
    3. 模式提取
    4. 生成优化建议
    5. (可选) 运行 Eval 回归
    """

    def __init__(self, persist_dir: str = ".harness"):
        self.tracer = Tracer(persist_dir=f"{persist_dir}/traces")
        self.eval_runner = EvalRunner()
        self.attribution = AttributionAnalyzer()
        self.pattern_extractor = PatternExtractor(
            persist_dir=f"{persist_dir}/patterns"
        )
        self.optimizer = Optimizer()
        self._last_trace_id: str | None = None

    def start_trace(self) -> str:
        """开始一个新的追踪。"""
        trace_id = self.tracer.start_trace()
        self._last_trace_id = trace_id
        return trace_id

    def end_trace_and_analyze(self) -> dict[str, Any]:
        """结束追踪并运行完整的反馈分析。

        Returns:
            dict: 包含归因、模式和建议的分析报告
        """
        self.tracer.save()

        error_spans = self.tracer.get_error_spans()
        if not error_spans:
            return {"status": "ok", "trace_id": self.tracer.trace_id}

        # 归因分析
        attr = self.attribution.analyze(self.tracer)

        # 模式提取
        pattern = self.pattern_extractor.extract(attr)
        self.pattern_extractor.save()

        # 优化建议
        suggestion = self.optimizer.analyze_pattern(pattern)

        return {
            "status": "analyzed",
            "trace_id": self.tracer.trace_id,
            "attribution": attr,
            "pattern": pattern.to_dict(),
            "suggestion": {
                "target": suggestion.target,
                "description": suggestion.description,
                "action_items": suggestion.action_items,
                "auto_applicable": suggestion.auto_applicable,
            },
        }

    async def run_eval(
        self,
        suite: EvalSuite,
        harness: Any | None = None,
    ) -> EvalReport:
        """运行评估套件。

        Args:
            suite: 评估套件
            harness: 可选的 Harness 实例

        Returns:
            EvalReport: 评估报告
        """
        self.eval_runner.harness = harness
        report = await self.eval_runner.run_suite(suite)

        # 分析失败的用例
        for result in report.results:
            if not result.passed and result.trace_id:
                # 尝试加载 trace 并归因
                if self.tracer.load(result.trace_id):
                    attr = self.attribution.analyze(self.tracer)
                    pattern = self.pattern_extractor.extract(attr)
                    self.optimizer.analyze_pattern(pattern)

        self.pattern_extractor.save()
        return report

    def get_summary(self) -> dict[str, Any]:
        """获取反馈系统摘要。"""
        return {
            "total_traces": len(
                list(self.tracer.persist_dir.glob("*.json"))
            ) if self.tracer.persist_dir.exists() else 0,
            "patterns": self.pattern_extractor.list_patterns()[:5],
            "top_suggestions": [
                {
                    "target": s.target,
                    "description": s.description,
                    "priority": s.priority,
                }
                for s in self.optimizer.get_top_suggestions(5)
            ],
        }
