"""问题抽象 — 将失败案例归纳为可复现的 Failure Pattern。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.feedback.attribution.analyzer import Attribution, RootCause


@dataclass
class FailurePattern:
    """失败模式 — 一类失败问题的抽象表示。"""
    pattern_id: str
    signature: str               # 错误特征签名 (用于去重)
    category: str                # 分类
    root_cause: RootCause = "unknown"
    frequency: int = 1
    first_seen: datetime = field(default_factory=datetime.now)
    latest_seen: datetime = field(default_factory=datetime.now)
    example_traces: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    suggested_fix: str = ""
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "signature": self.signature,
            "category": self.category,
            "root_cause": self.root_cause,
            "frequency": self.frequency,
            "first_seen": self.first_seen.isoformat(),
            "latest_seen": self.latest_seen.isoformat(),
            "example_traces": self.example_traces[-3:],  # 保留最近 3 条
            "error_messages": self.error_messages[-5:],
            "suggested_fix": self.suggested_fix,
            "resolved": self.resolved,
        }


class PatternExtractor:
    """模式提取器 — 从归因结果中提取和聚合失败模式。"""

    def __init__(self, persist_dir: str = ".harness/patterns"):
        self.persist_dir = Path(persist_dir)
        self._patterns: dict[str, FailurePattern] = {}
        self._load()

    def extract(self, attribution: Attribution) -> FailurePattern:
        """从归因结果中提取失败模式。

        如果已有相似模式，更新频率；否则创建新模式。

        Args:
            attribution: 归因结果

        Returns:
            FailurePattern: 匹配或新建的模式
        """
        signature = self._compute_signature(attribution)

        if signature in self._patterns:
            pattern = self._patterns[signature]
            pattern.frequency += 1
            pattern.latest_seen = datetime.now()
            if attribution.trace_id:
                pattern.example_traces.append(attribution.trace_id)
            if attribution.error_detail:
                pattern.error_messages.append(attribution.error_detail)
            return pattern

        # 新建模式
        pattern = FailurePattern(
            pattern_id=f"pat_{hashlib.md5(signature.encode()).hexdigest()[:8]}",
            signature=signature,
            category=self._categorize(attribution),
            root_cause=attribution.root_cause,
            example_traces=(
                [attribution.trace_id] if attribution.trace_id else []
            ),
            error_messages=(
                [attribution.error_detail] if attribution.error_detail else []
            ),
            suggested_fix=attribution.suggestion,
        )
        self._patterns[signature] = pattern
        return pattern

    def list_patterns(self) -> list[dict[str, Any]]:
        """列出所有模式。"""
        return sorted(
            [p.to_dict() for p in self._patterns.values()],
            key=lambda x: x["frequency"],
            reverse=True,
        )

    def get_top_patterns(self, limit: int = 5) -> list[FailurePattern]:
        """获取最频繁的失败模式。"""
        sorted_pats = sorted(
            self._patterns.values(),
            key=lambda p: p.frequency,
            reverse=True,
        )
        return sorted_pats[:limit]

    def _compute_signature(self, attribution: Attribution) -> str:
        """计算归因特征签名。"""
        components = [
            attribution.root_cause,
            attribution.failed_component,
            attribution.error_detail[:100] if attribution.error_detail else "",
        ]
        return "::".join(components)

    def _categorize(self, attribution: Attribution) -> str:
        """对失败进行分类。"""
        root_cause = attribution.root_cause
        error_msg = (attribution.error_detail or "").lower()

        categories = {
            "llm_reasoning": "llm_error",
            "tool_error": "tool_integration",
            "permission": "security_config",
            "timeout": "performance",
            "plugin_bug": "plugin_quality",
            "skill_config": "skill_config",
        }

        base_cat = categories.get(root_cause, "unknown")
        if "timeout" in error_msg:
            return f"{base_cat}/timeout"
        if "not found" in error_msg:
            return f"{base_cat}/not_found"
        return base_cat

    def _load(self) -> None:
        """从文件加载已保存的模式。"""
        if not self.persist_dir.exists():
            return
        for f in self.persist_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                pattern = FailurePattern(
                    pattern_id=data["pattern_id"],
                    signature=data["signature"],
                    category=data["category"],
                    root_cause=data.get("root_cause", "unknown"),
                    frequency=data.get("frequency", 1),
                    first_seen=datetime.fromisoformat(data["first_seen"]),
                    latest_seen=datetime.fromisoformat(data["latest_seen"]),
                    example_traces=data.get("example_traces", []),
                    error_messages=data.get("error_messages", []),
                    suggested_fix=data.get("suggested_fix", ""),
                    resolved=data.get("resolved", False),
                )
                self._patterns[pattern.signature] = pattern
            except (json.JSONDecodeError, KeyError):
                continue

    def save(self) -> None:
        """持久化所有模式到文件。"""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        for pattern in self._patterns.values():
            file_path = self.persist_dir / f"{pattern.pattern_id}.json"
            file_path.write_text(
                json.dumps(pattern.to_dict(), ensure_ascii=False, indent=2)
            )

    def clear(self) -> None:
        self._patterns.clear()
