"""配置管理 — Harness 全局配置的 Schema 定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.core.permissions import PermissionLevel


@dataclass
class LLMProviderConfig:
    """LLM 提供商配置。"""
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class MemoryConfig:
    """记忆系统配置。"""
    working_max_tokens: int = 128_000
    episodic_persist_dir: str = ".harness/memory/episodic"
    semantic_enabled: bool = False


@dataclass
class RecoveryConfig:
    """恢复机制配置。"""
    checkpoint_dir: str = ".harness/checkpoints"
    checkpoint_interval: int = 3  # 每 N 步保存一次
    checkpoint_ttl_days: int = 7


@dataclass
class PluginConfig:
    """插件系统配置。"""
    auto_discover: bool = True
    builtin_enabled: bool = True
    extra_paths: list[str] = field(default_factory=list)


@dataclass
class EvalConfig:
    """评估配置。"""
    enabled: bool = False
    suites_dir: str = ".harness/eval/suites"
    results_dir: str = ".harness/eval/results"


@dataclass
class HarnessConfig:
    """Harness 全局配置。"""
    name: str = "harness"
    max_steps: int = 50
    permission_level: PermissionLevel = PermissionLevel.SANDBOX
    permission: dict[str, Any] = field(default_factory=dict)
    llm: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)

    @classmethod
    def default(cls) -> HarnessConfig:
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HarnessConfig:
        llm_data = data.get("llm", {})
        memory_data = data.get("memory", {})
        recovery_data = data.get("recovery", {})
        plugins_data = data.get("plugins", {})
        eval_data = data.get("eval", {})

        return cls(
            name=data.get("name", "harness"),
            max_steps=data.get("max_steps", 50),
            permission_level=PermissionLevel[data.get("permission_level", "SANDBOX").upper()],
            permission=data.get("permission", {}),
            llm=LLMProviderConfig(**llm_data),
            memory=MemoryConfig(**memory_data),
            recovery=RecoveryConfig(**recovery_data),
            plugins=PluginConfig(**plugins_data),
            eval=EvalConfig(**eval_data),
        )
