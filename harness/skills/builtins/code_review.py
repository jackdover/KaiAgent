"""示例 Skill: Code Review — 代码审查助手。"""

from __future__ import annotations

from harness.skills.interface import Skill, SkillMetadata, SkillContext
from harness.core.types import ToolDefinition


class CodeReviewSkill(Skill):
    """代码审查 Skill — 审查代码质量、发现潜在问题。"""

    metadata = SkillMetadata(
        name="code_review",
        version="0.1.0",
        description="审查代码质量，分析代码风格、潜在 bug 和改进建议",
        match_keywords=["review", "审查", "code review", "代码审查", "review code"],
        plugin_deps=["file", "shell"],
    )

    async def get_system_prompt(self, context: SkillContext) -> str:
        """注入代码审查领域的系统提示。"""
        return (
            "You are a senior code reviewer with deep expertise in software engineering. "
            "Your task is to review code thoroughly:\n"
            "1. Read the source files using read_file\n"
            "2. Analyze code quality, potential bugs, and style issues\n"
            "3. Provide specific, actionable feedback\n"
            "4. Include line numbers and code snippets in your suggestions\n\n"
            "Focus areas:\n"
            "- Correctness: logic errors, edge cases, race conditions\n"
            "- Security: injection, XSS, auth issues\n"
            "- Maintainability: naming, complexity, duplication\n"
            "- Performance: inefficient algorithms, N+1 queries, memory leaks\n"
            "- Style: consistency with language conventions"
        )

    async def get_tools(self, context: SkillContext) -> list[ToolDefinition]:
        """返回代码审查需要的工具。"""
        if context.plugin_registry:
            return context.plugin_registry.collect_tools()
        return []
