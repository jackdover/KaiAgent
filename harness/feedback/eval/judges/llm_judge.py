"""LLM Judge — 使用 LLM 评判输出质量。"""

from __future__ import annotations

from typing import Any


class LLMJudge:
    """LLM 评判器 — 使用 LLM 评估输出质量。

    适用于需要主观判断的场景（如代码质量、文案效果）。

    TODO: 接入真实的 LLM Provider 进行评估。
    """

    def __init__(self, llm_provider: Any | None = None):
        self._llm = llm_provider

    async def judge(
        self,
        output: str,
        expected: dict[str, Any],
    ) -> tuple[bool, float, str]:
        """使用 LLM 评判输出。

        在没有 LLM Provider 时，使用基于规则的兜底判断。

        Args:
            output: 实际输出
            expected: 期望格式: {"criteria": str, "min_score": float}

        Returns:
            tuple[bool, float, str]: (是否通过, 分数, 详情)
        """
        criteria = expected.get("criteria", "output should be relevant and correct")
        min_score = expected.get("min_score", 0.7)

        if self._llm:
            return await self._llm_judge(output, criteria, min_score)

        return await self._rule_based_fallback(output, criteria, min_score)

    async def _llm_judge(
        self,
        output: str,
        criteria: str,
        min_score: float,
    ) -> tuple[bool, float, str]:
        """使用 LLM 评判 (stub, 需要接入真实 Provider)。"""
        return True, 0.9, "[LLM Judge stub] would evaluate using LLM"

    async def _rule_based_fallback(
        self,
        output: str,
        criteria: str,
        min_score: float,
    ) -> tuple[bool, float, str]:
        """基于规则的兜底评判。"""
        if not output:
            return False, 0.0, "Empty output"
        if len(output) < 10:
            return False, 0.2, f"Output too short ({len(output)} chars)"
        return True, 0.8, "Output length OK (rule-based fallback)"
