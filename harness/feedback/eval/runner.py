"""Eval Runner — 评估运行器。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from harness.feedback.eval.case import EvalCase, EvalReport, EvalResult, EvalSuite
from harness.feedback.eval.judges.exact import ExactJudge, KeywordJudge, SubstringJudge
from harness.feedback.eval.judges.llm_judge import LLMJudge


class EvalRunner:
    """评估运行器 — 运行 EvalSuite 并生成报告。

    支持三种评判模式:
    - "exact": 精确匹配 (默认)
    - "substring": 子串匹配
    - "keyword": 关键词评分
    - "llm": LLM 评判
    """

    def __init__(self, harness: Any | None = None):
        self.harness = harness
        self._judges = {
            "exact": ExactJudge(),
            "substring": SubstringJudge(),
            "keyword": KeywordJudge(),
            "llm": LLMJudge(),
        }

    async def run_suite(self, suite: EvalSuite) -> EvalReport:
        """运行一个评估套件。

        Args:
            suite: 评估套件

        Returns:
            EvalReport: 评估报告
        """
        report = EvalReport(
            suite_name=suite.name,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        for case in suite.cases:
            result = await self._run_case(case)
            report.results.append(result)

            if result.passed:
                report.passed += 1
            else:
                report.failed += 1

            report.total_duration_ms += result.duration_ms

        report.total = report.total or len(report.results)
        report.pass_rate = report.passed / report.total if report.total > 0 else 0.0
        report.completed_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        return report

    async def run_single(
        self,
        case: EvalCase,
        output: str | None = None,
    ) -> EvalResult:
        """运行单个评估用例。

        Args:
            case: 评估用例
            output: 可选，直接传入输出来评判

        Returns:
            EvalResult: 评估结果
        """
        return await self._run_case(case, provided_output=output)

    async def _run_case(
        self,
        case: EvalCase,
        provided_output: str | None = None,
    ) -> EvalResult:
        """执行单个用例的内部方法。"""
        start = time.time()
        result = EvalResult(case_id=case.id)

        try:
            # 获取输出
            if provided_output is not None:
                output = provided_output
            elif self.harness is not None:
                session_result = await self.harness.run(case.input)
                output = session_result.output or ""
                result.trace_id = session_result.session_id
            else:
                output = ""

            result.output = output

            # 评判
            judge_fn = self._get_judge(case.judge)
            passed, score, detail = await judge_fn(output, case.expected)
            result.passed = passed
            result.score = score
            result.details = detail

        except Exception as e:
            result.passed = False
            result.score = 0.0
            result.error = str(e)
            result.details = f"Error running case: {e}"

        result.duration_ms = (time.time() - start) * 1000
        return result

    def _get_judge(self, judge_type: str) -> Any:
        """获取评判器。"""
        judge = self._judges.get(judge_type)
        if judge is None:
            raise ValueError(f"Unknown judge type: {judge_type}")

        if hasattr(judge, 'judge'):
            return judge.judge
        return judge

    def save_report(self, report: EvalReport, path: str) -> None:
        """保存评估报告到文件。"""
        Path(path).write_text(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2)
        )

    def print_report(self, report: EvalReport) -> None:
        """打印评估报告摘要。"""
        print(f"\n{'='*50}")
        print(f"Eval Report: {report.suite_name}")
        print(f"{'='*50}")
        print(f"Total: {report.total}  |  Passed: {report.passed}  |  "
              f"Failed: {report.failed}  |  Rate: {report.pass_rate:.1%}")
        print(f"Duration: {report.total_duration_ms:.0f}ms")
        print(f"{'='*50}")

        if report.failed > 0:
            print("\nFailed cases:")
            for r in report.results:
                if not r.passed:
                    print(f"  [FAIL] {r.case_id}: {r.details}")
