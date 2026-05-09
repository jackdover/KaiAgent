"""迭代优化引擎 — 从 Pattern 自动生成改进方案。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from harness.feedback.abstraction.pattern import FailurePattern

OptimizationTarget = Literal[
    "prompt_template",
    "tool_config",
    "skill_logic",
    "plugin_impl",
    "permission_policy",
    "runtime_config",
]


@dataclass
class OptimizationSuggestion:
    """优化建议。"""
    target: OptimizationTarget
    component: str
    description: str
    action_items: list[str] = field(default_factory=list)
    priority: int = 0  # 0=low, 1=medium, 2=high
    auto_applicable: bool = False  # 是否能自动应用


class Optimizer:
    """优化引擎 — 根据失败模式自动生成改进方案。"""

    def __init__(self):
        self._suggestions: list[OptimizationSuggestion] = []

    def analyze_pattern(self, pattern: FailurePattern) -> OptimizationSuggestion:
        """分析一个失败模式，生成优化建议。

        Args:
            pattern: 失败模式

        Returns:
            OptimizationSuggestion: 优化建议
        """
        suggestion = self._suggest_for_pattern(pattern)
        self._suggestions.append(suggestion)
        return suggestion

    def analyze_patterns(
        self, patterns: list[FailurePattern]
    ) -> list[OptimizationSuggestion]:
        """批量分析多个模式。"""
        return [self.analyze_pattern(p) for p in patterns]

    def get_top_suggestions(
        self, limit: int = 5
    ) -> list[OptimizationSuggestion]:
        """获取优先级最高的建议。"""
        return sorted(
            self._suggestions,
            key=lambda s: (s.priority, len(s.action_items)),
            reverse=True,
        )[:limit]

    def _suggest_for_pattern(
        self, pattern: FailurePattern
    ) -> OptimizationSuggestion:
        """为特定模式生成建议。"""
        root = pattern.root_cause
        component = pattern.error_messages[0][:50] if pattern.error_messages else ""

        suggestions_map = {
            "llm_reasoning": self._llm_reasoning_suggestion,
            "tool_error": self._tool_error_suggestion,
            "permission": self._permission_suggestion,
            "timeout": self._timeout_suggestion,
            "plugin_bug": self._plugin_bug_suggestion,
            "skill_config": self._skill_config_suggestion,
        }

        handler = suggestions_map.get(root, self._unknown_suggestion)
        return handler(pattern, component)

    def _llm_reasoning_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="prompt_template",
            component=component,
            description="LLM reasoning error detected. Improve system prompt.",
            action_items=[
                "Add more specific examples to the system prompt",
                "Include expected output format guidelines",
                "Add step-by-step reasoning instructions",
                "Consider adding few-shot examples for this scenario",
            ],
            priority=2,
            auto_applicable=False,
        )

    def _tool_error_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="tool_config",
            component=component,
            description=f"Tool error: {pattern.error_messages[0] if pattern.error_messages else 'unknown'}",
            action_items=[
                "Check tool parameters and input validation",
                "Add error handling and retry logic for the tool",
                "Verify the tool's API endpoint and authentication",
                "Consider adding input sanitization before tool calls",
            ],
            priority=1,
            auto_applicable=False,
        )

    def _permission_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="permission_policy",
            component=component,
            description="Permission denied. Update permission policy.",
            action_items=[
                "Add the required resource to the permission whitelist",
                "Review permission level (NONE/READ_ONLY/SANDBOX/FULL)",
                "Consider using a more permissive level if appropriate",
            ],
            priority=2,
            auto_applicable=True,
        )

    def _timeout_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="runtime_config",
            component=component,
            description="Operation timed out. Adjust timeout settings.",
            action_items=[
                "Increase timeout for this operation type",
                "Break large tasks into smaller sub-tasks",
                "Consider async execution for long-running operations",
            ],
            priority=1,
            auto_applicable=True,
        )

    def _plugin_bug_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="plugin_impl",
            component=component,
            description=f"Plugin bug in {component}",
            action_items=[
                f"Review {component} plugin implementation for bugs",
                "Add input validation and error handling",
                "Add unit tests for edge cases",
                "Consider adding logging for debugging",
            ],
            priority=2,
            auto_applicable=False,
        )

    def _skill_config_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="skill_logic",
            component=component,
            description=f"Skill configuration issue in {component}",
            action_items=[
                f"Review {component} skill configuration",
                "Check plugin dependencies are correctly specified",
                "Verify match_keywords are appropriate",
                "Consider adding more specific matching patterns",
            ],
            priority=1,
            auto_applicable=False,
        )

    def _unknown_suggestion(
        self, pattern: FailurePattern, component: str
    ) -> OptimizationSuggestion:
        return OptimizationSuggestion(
            target="runtime_config",
            component=component,
            description="Unknown error pattern. Review logs manually.",
            action_items=[
                "Check trace logs for detailed error information",
                "Review the failed step for unexpected behavior",
                "Consider adding more detailed logging for this scenario",
            ],
            priority=0,
            auto_applicable=False,
        )

    def clear(self) -> None:
        self._suggestions.clear()
