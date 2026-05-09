"""核心类型定义 — Agent Loop 的所有基础数据类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any


class AgentStatus(Enum):
    """Agent 会话生命周期状态。"""
    INIT = auto()
    IDLE = auto()
    THINKING = auto()
    ACTING = auto()
    OBSERVING = auto()
    CHECKPOINT = auto()
    RESUMING = auto()
    ERROR = auto()
    DONE = auto()


class HookMode(Enum):
    """Hook 执行模式。"""
    OBSERVE = "observe"  # 只观察，不修改数据
    MODIFY = "modify"    # 可以修改上下文数据
    ABORT = "abort"      # 可以终止当前流程


class ActionType(Enum):
    """Action 类型。"""
    TOOL_CALL = "tool_call"
    TEXT_RESPONSE = "text_response"
    SKILL_INVOKE = "skill_invoke"
    FINISH = "finish"


@dataclass
class ToolCall:
    """工具调用定义。"""
    name: str
    arguments: dict[str, Any]
    tool_call_id: str = ""


@dataclass
class Action:
    """Agent 在 ACTING 阶段产出的动作。"""
    type: ActionType
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    """Action 执行后得到的观察结果。"""
    content: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Step:
    """Loop 中的一个完整 step: think → act → observe。"""
    id: str
    thought: str | None = None
    action: Action | None = None
    observation: Observation | None = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """一个完整会话的状态快照。"""
    session_id: str
    status: AgentStatus = AgentStatus.INIT
    steps: list[Step] = field(default_factory=list)
    current_step: Step | None = None
    checkpoint_path: Path | None = None
    task: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class LLMMessage:
    """LLM 对话消息。"""
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    """LLM 响应。"""
    content: str | None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str = "stop"
    usage: dict[str, int] | None = None


class ToolDefinition:
    """工具定义 (OpenAI Function Calling 格式兼容)。"""
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ):
        self.name = name
        self.description = description
        self.parameters = parameters

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class SessionResult:
    """会话执行结果。"""
    session_id: str
    status: AgentStatus
    steps: list[Step]
    output: str | None = None
    error: str | None = None
    total_duration: float = 0.0
