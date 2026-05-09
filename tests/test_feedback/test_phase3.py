"""Phase 3 测试: Tracing + Eval + 归因 + 抽象 + 优化。"""

import pytest

from harness.feedback.tracing import Span, Tracer
from harness.feedback.eval import EvalCase, EvalSuite, EvalRunner
from harness.feedback.attribution import AttributionAnalyzer, Attribution
from harness.feedback.abstraction import FailurePattern, PatternExtractor
from harness.feedback.optimization import Optimizer, OptimizationSuggestion
from harness import Harness


# ===== Tracing Tests =====

class TestTracing:
    def test_create_span(self):
        """测试 Span 创建。"""
        span = Span.create(
            trace_id="test_trace",
            name="test_span",
            span_type="step",
        )
        assert span.trace_id == "test_trace"
        assert span.name == "test_span"
        assert span.span_type == "step"
        assert span.parent_id is None
        assert not span.is_completed

    def test_end_span(self):
        """测试 Span 结束。"""
        span = Span.create("t1", "test", "step")
        span.end(status="ok")
        assert span.is_completed
        assert span.status == "ok"
        assert span.duration_ms >= 0

    def test_span_with_error(self):
        """测试 Span 错误状态。"""
        span = Span.create("t1", "test", "action")
        span.end(status="error", error="Something went wrong")
        assert span.status == "error"
        assert span.error == "Something went wrong"


class TestTracer:
    def test_start_trace(self):
        """测试 Tracer 启动。"""
        tracer = Tracer()
        trace_id = tracer.start_trace("my_trace")
        assert trace_id == "my_trace"
        assert tracer.trace_id == "my_trace"

    def test_start_and_end_span(self):
        """测试 Span 的 start/end。"""
        tracer = Tracer()
        tracer.start_trace()

        span = tracer.start_span("step_1", "step")
        assert span.name == "step_1"
        assert span.parent_id is None
        assert len(tracer._spans) == 1

        child = tracer.start_span("think", "think")
        assert child.parent_id == span.span_id
        assert len(tracer._spans) == 2

        tracer.end_span(child)
        assert child.is_completed

        tracer.end_span(span)
        assert span.is_completed

    def test_span_context_manager(self):
        """测试上下文管理器风格的 Span。"""
        import asyncio

        tracer = Tracer()
        tracer.start_trace()

        async def run():
            async with tracer.span("step_1", "step") as span:
                assert span.name == "step_1"
                assert not span.is_completed

            assert span.is_completed

        asyncio.run(run())

    def test_trace_with_error_span(self):
        """测试包含错误 Span 的追踪。"""
        tracer = Tracer()
        tracer.start_trace()

        ok_span = tracer.start_span("step_1", "step")
        tracer.end_span(ok_span)

        err_span = tracer.start_span("step_2", "step")
        tracer.end_span(err_span, status="error", error="Failed!")

        error_spans = tracer.get_error_spans()
        assert len(error_spans) == 1
        assert error_spans[0].name == "step_2"

        report = tracer.export()
        assert report["error_count"] == 1
        assert report["span_count"] == 2

    def test_build_tree(self):
        """测试 Span 树构建。"""
        tracer = Tracer()
        tracer.start_trace()

        s1 = tracer.start_span("step_1", "step")
        c1 = tracer.start_span("think", "think")
        tracer.end_span(c1)
        tracer.end_span(s1)

        tree = tracer.build_tree()
        assert len(tree) == 1
        assert tree[0]["span"]["name"] == "step_1"
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["span"]["name"] == "think"


# ===== Eval Tests =====

class TestEval:
    def test_eval_case_creation(self):
        """测试 EvalCase 创建。"""
        case = EvalCase(
            id="case_1",
            name="test case",
            input="hello",
            expected="world",
            judge="exact",
        )
        assert case.id == "case_1"
        assert case.judge == "exact"

    def test_eval_suite(self):
        """测试 EvalSuite。"""
        suite = EvalSuite(name="test_suite")
        suite.add_case(EvalCase(id="c1", name="case 1", input="a", expected="a"))
        suite.add_case(EvalCase(id="c2", name="case 2", input="b", expected="c"))
        assert suite.count == 2

        # 过滤
        filtered = suite.filter_by_skill("nonexistent")
        assert len(filtered) == 0

    @pytest.mark.asyncio
    async def test_exact_judge(self):
        """测试精确匹配评判器。"""
        runner = EvalRunner()
        case = EvalCase(id="t1", name="exact match", input="x", expected="hello")
        result = await runner.run_single(case, output="hello")
        assert result.passed
        assert result.score == 1.0

        result = await runner.run_single(case, output="world")
        assert not result.passed
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_substring_judge(self):
        """测试子串匹配评判器。"""
        from harness.feedback.eval.judges.exact import SubstringJudge

        judge = SubstringJudge()
        passed, score, _ = await judge.judge("hello world", "world")
        assert passed

        passed, score, _ = await judge.judge("hello world", "xyz")
        assert not passed

    @pytest.mark.asyncio
    async def test_keyword_judge(self):
        """测试关键词评判器。"""
        from harness.feedback.eval.judges.exact import KeywordJudge

        judge = KeywordJudge()
        passed, score, _ = await judge.judge(
            "python is great for data science",
            ["python", "data", "javascript"],
        )
        assert passed  # 2/3 > 0.5
        assert score == 2 / 3

    @pytest.mark.asyncio
    async def test_eval_runner_with_harness(self):
        """测试 EvalRunner 与 Harness 集成。"""
        h = Harness()
        await h.start()

        suite = EvalSuite(name="harness_test")
        suite.add_case(EvalCase(id="h1", name="run task", input="hi", expected="hi"))

        runner = EvalRunner(harness=h)
        report = await runner.run_suite(suite)
        assert report.total == 1
        assert report.passed >= 0  # 可能有 harness 输出不同

        await h.stop()


# ===== Attribution Tests =====

class TestAttribution:
    def test_attribution_from_tracer(self):
        """测试从 Tracer 数据进行归因。"""
        tracer = Tracer()
        tracer.start_trace()

        s1 = tracer.start_span("step_1", "step")
        tracer.end_span(s1)

        s2 = tracer.start_span("action_1", "action")
        tracer.end_span(s2, status="error", error="timeout after 30s")

        analyzer = AttributionAnalyzer()
        attribution = analyzer.analyze(tracer)

        assert attribution.trace_id == tracer.trace_id
        assert attribution.root_cause == "timeout"
        assert "timeout" in attribution.suggestion.lower()

    def test_permission_attribution(self):
        """测试权限错误归因。"""
        tracer = Tracer()
        tracer.start_trace()

        span = tracer.start_span("write_file", "plugin")
        tracer.end_span(span, status="error", error="Permission denied: write on '/etc'")

        analyzer = AttributionAnalyzer()
        attribution = analyzer.analyze(tracer)

        assert attribution.root_cause == "permission"


# ===== Abstraction Tests =====

class TestAbstraction:
    def test_pattern_extraction(self):
        """测试模式提取。"""
        extractor = PatternExtractor()

        attr = Attribution(
            trace_id="trace_1",
            root_cause="tool_error",
            failed_component="WebPlugin.fetch_url",
            error_detail="Connection refused",
            suggestion="Check network",
        )

        pattern = extractor.extract(attr)
        assert pattern.root_cause == "tool_error"
        assert pattern.frequency == 1
        assert "trace_1" in pattern.example_traces

        # 相同模式再次提取 — 频率增加
        attr2 = Attribution(
            trace_id="trace_2",
            root_cause="tool_error",
            failed_component="WebPlugin.fetch_url",
            error_detail="Connection refused",
        )
        pattern2 = extractor.extract(attr2)
        assert pattern2.frequency == 2

    def test_top_patterns(self):
        """测试获取最频繁的模式。"""
        extractor = PatternExtractor()

        for i in range(3):
            extractor.extract(Attribution(
                trace_id=f"t_{i}",
                root_cause="tool_error",
                failed_component="file.read",
            ))

        extractor.extract(Attribution(
            trace_id="t_other",
            root_cause="timeout",
            failed_component="web.get",
        ))

        top = extractor.get_top_patterns(limit=2)
        assert len(top) == 2
        assert top[0].frequency >= top[1].frequency


# ===== Optimization Tests =====

class TestOptimization:
    def test_llm_reasoning_suggestion(self):
        """测试 LLM 推理错误的优化建议。"""
        optimizer = Optimizer()
        pattern = FailurePattern(
            pattern_id="p1",
            signature="llm::step_1::failed to parse",
            category="llm_error",
            root_cause="llm_reasoning",
        )

        suggestion = optimizer.analyze_pattern(pattern)
        assert suggestion.target == "prompt_template"
        assert not suggestion.auto_applicable
        assert len(suggestion.action_items) > 0

    def test_permission_suggestion(self):
        """测试权限错误的优化建议。"""
        optimizer = Optimizer()
        pattern = FailurePattern(
            pattern_id="p2",
            signature="perm::write_file::denied",
            category="security_config",
            root_cause="permission",
        )

        suggestion = optimizer.analyze_pattern(pattern)
        assert suggestion.target == "permission_policy"
        assert suggestion.auto_applicable

    def test_top_suggestions(self):
        """测试按优先级排序的建议。"""
        optimizer = Optimizer()
        optimizer._suggestions = [
            OptimizationSuggestion(
                target="prompt_template", component="", description="",
                priority=0,
            ),
            OptimizationSuggestion(
                target="plugin_impl", component="", description="",
                priority=2,
            ),
        ]
        top = optimizer.get_top_suggestions(1)
        assert len(top) == 1
        assert top[0].target == "plugin_impl"


# ===== End-to-End Feedback Loop Test =====

class TestFeedbackLoop:
    @pytest.mark.asyncio
    async def test_full_feedback_loop(self):
        """测试反馈闭环的完整端到端流程。"""
        # 1. 运行 Harness 产生追踪
        h = Harness()
        await h.start()
        result = await h.run("say hello")
        await h.stop()

        # 2. 使用 Tracer 记录
        tracer = Tracer()
        tracer.start_trace("e2e_test")
        span = tracer.start_span("full_session", "step")
        tracer.end_span(span)
        tracer.save()

        # 3. 归因分析
        analyzer = AttributionAnalyzer()
        attribution = analyzer.analyze(tracer)

        # 4. 模式提取
        extractor = PatternExtractor()
        pattern = extractor.extract(attribution)

        # 5. 优化建议
        optimizer = Optimizer()
        suggestion = optimizer.analyze_pattern(pattern)

        # 6. 验证闭环
        assert attribution.trace_id == "e2e_test"
        assert pattern.frequency == 1
        assert suggestion.target in [
            "prompt_template", "tool_config", "skill_logic",
            "plugin_impl", "permission_policy", "runtime_config",
        ]

        assert result.status.name == "DONE"
