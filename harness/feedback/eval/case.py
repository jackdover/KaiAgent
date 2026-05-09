"""Eval 评估框架 — 测试用例与测试套件定义。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel


class EvalCase(BaseModel):
    """评估用例 — 一个具体的测试场景。"""
    id: str
    name: str
    input: str
    expected: Any
    skill: str = ""
    judge: str = "exact"       # judge 方式: "exact" | "llm" | "function"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class EvalResult(BaseModel):
    """评估结果。"""
    case_id: str
    passed: bool = False
    score: float = 0.0
    output: Any = None
    error: str | None = None
    trace_id: str = ""
    duration_ms: float = 0.0
    details: str = ""


class EvalReport(BaseModel):
    """评估报告 — 一次评估运行的结果汇总。"""
    suite_name: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    total_duration_ms: float = 0.0
    results: list[EvalResult] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""


class EvalSuite:
    """评估套件 — 一组相关用例的集合。"""

    def __init__(self, name: str = "", cases: list[EvalCase] | None = None):
        self.name = name
        self.cases = list(cases) if cases else []

    def add_case(self, case: EvalCase) -> None:
        """添加一个测试用例。"""
        self.cases.append(case)

    def add_cases(self, cases: list[EvalCase]) -> None:
        """批量添加测试用例。"""
        self.cases.extend(cases)

    def filter_by_tag(self, tag: str) -> list[EvalCase]:
        """按标签筛选用例。"""
        return [c for c in self.cases if tag in c.tags]

    def filter_by_skill(self, skill: str) -> list[EvalCase]:
        """按 Skill 筛选用例。"""
        return [c for c in self.cases if c.skill == skill]

    def to_file(self, path: str) -> None:
        """导出用例到 JSON 文件。"""
        data = {
            "name": self.name,
            "cases": [c.model_dump() for c in self.cases],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def from_file(cls, path: str) -> EvalSuite:
        """从 JSON 文件导入用例。"""
        data = json.loads(Path(path).read_text())
        cases = [EvalCase(**c) for c in data["cases"]]
        return cls(name=data.get("name", ""), cases=cases)

    @property
    def count(self) -> int:
        return len(self.cases)
