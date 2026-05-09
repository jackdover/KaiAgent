"""Exact Judge — 精确匹配评判器。"""

from __future__ import annotations

from typing import Any


class ExactJudge:
    """精确匹配评判器 — 判断输出与期望值是否完全匹配。"""

    @staticmethod
    async def judge(output: Any, expected: Any) -> tuple[bool, float, str]:
        """评判输出是否与期望值匹配。

        Args:
            output: 实际输出
            expected: 期望输出

        Returns:
            tuple[bool, float, str]: (是否通过, 分数, 详情)
        """
        if isinstance(expected, str) and isinstance(output, str):
            passed = output.strip() == expected.strip()
        else:
            passed = output == expected

        score = 1.0 if passed else 0.0
        detail = "Exact match" if passed else f"Expected '{expected}', got '{output}'"
        return passed, score, detail


class SubstringJudge:
    """子串匹配评判器 — 判断输出是否包含期望子串。"""

    @staticmethod
    async def judge(output: str, expected: str) -> tuple[bool, float, str]:
        if expected in output:
            return True, 1.0, f"Found expected substring: '{expected}'"
        return False, 0.0, f"Substring '{expected}' not found in output"


class KeywordJudge:
    """关键词评分评判器 — 检查输出中包含多少期望关键词。"""

    @staticmethod
    async def judge(output: str, expected: list[str]) -> tuple[bool, float, str]:
        if not expected:
            return True, 1.0, "No keywords to check"

        found = [kw for kw in expected if kw in output]
        score = len(found) / len(expected)
        passed = score >= 0.5  # 命中超过一半视为通过

        detail = (
            f"Found {len(found)}/{len(expected)} keywords: {found}"
            if found
            else "No keywords found"
        )
        return passed, score, detail
