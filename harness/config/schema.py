"""配置管理 — Harness 全局配置的 Schema 定义。

支持 5 级配置层次 (优先级递增):
  1. Enterprise: .harness/settings.json
  2. User: ~/.harness/settings.json
  3. Project: .harness/settings.local.json
  4. Local: .harness/settings.json
  5. CLI: --config 参数
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.core.permissions import PermissionLevel


# ---- 配置层次发现 ---- #

def find_config_files(project_dir: str | Path = ".") -> list[Path]:
    """查找所有层级配置文件，返回按优先级升序排列的列表。

    查找顺序:
      1. .harness/settings.json (企业/共享)
      2. ~/.harness/settings.json (用户)
      3. .harness/settings.local.json (个人覆盖)
      4. CLI 指定的文件 (由调用方处理)

    Args:
        project_dir: 项目根目录

    Returns:
        list[Path]: 按优先级升序排列的配置文件路径
    """
    project_dir = Path(project_dir).resolve()
    configs: list[Path] = []

    # Level 1: 项目共享配置
    shared = project_dir / ".harness" / "settings.json"
    if shared.exists():
        configs.append(shared)

    # Level 2: 用户级配置
    user_dir = Path.home() / ".harness"
    user_config = user_dir / "settings.json"
    if user_config.exists():
        configs.append(user_config)

    # Level 3: 用户个人覆盖
    user_local = project_dir / ".harness" / "settings.local.json"
    if user_local.exists():
        configs.append(user_local)

    return configs


def find_claude_md(project_dir: str | Path = ".") -> str | None:
    """查找 CLAUDE.md 文件内容。

    类似 Claude Code 的 CLAUDE.md，注入到 System Prompt 中。
    查找顺序: CLAUDE.md > .claude/CLAUDE.md

    Args:
        project_dir: 项目根目录

    Returns:
        str | None: 文件内容
    """
    project_dir = Path(project_dir).resolve()
    candidates = [
        project_dir / "CLAUDE.md",
        project_dir / ".claude" / "CLAUDE.md",
    ]
    for path in candidates:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                return None
    return None


def find_rules(project_dir: str | Path = ".") -> list[dict[str, str]]:
    """查找 rules/*.md 文件，返回 (路径, 内容) 列表。

    支持路径作用域: rules/<scope>.md。
    例如 rules/backend.md 对 backend 路径下的操作生效。

    Args:
        project_dir: 项目根目录

    Returns:
        list[dict]: [{"path": "backend", "content": "..."}]
    """
    project_dir = Path(project_dir).resolve()
    rules_dir = project_dir / "rules"
    if not rules_dir.exists():
        return []

    rules = []
    for f in sorted(rules_dir.glob("*.md")):
        scope = f.stem  # 文件名 (不含扩展名) 作为作用域名
        try:
            content = f.read_text(encoding="utf-8")
            rules.append({"path": scope, "content": content})
        except Exception:
            continue
    return rules


def load_config_hierarchy(
    project_dir: str | Path = ".",
    cli_config_path: str | None = None,
) -> dict[str, Any]:
    """加载配置层次，合并所有层级的配置。

    从低优先级到高优先级逐层加载，高优先级覆盖低优先级。

    Args:
        project_dir: 项目根目录
        cli_config_path: CLI 指定的配置文件路径

    Returns:
        dict: 合并后的配置字典
    """
    merged: dict[str, Any] = {}

    # 自动发现并加载各级配置
    config_files = find_config_files(project_dir)
    for cfg_path in config_files:
        try:
            raw = cfg_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            merged = _deep_merge(merged, data)
        except (json.JSONDecodeError, OSError):
            continue

    # CLI 配置 (最高优先级)
    if cli_config_path:
        cli_path = Path(cli_config_path)
        if cli_path.exists():
            raw = cli_path.read_text(encoding="utf-8")
            if cli_path.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    data = yaml.safe_load(raw)
                    merged = _deep_merge(merged, data)
                except ImportError:
                    pass
            else:
                try:
                    data = json.loads(raw)
                    merged = _deep_merge(merged, data)
                except json.JSONDecodeError:
                    pass

    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---- 配置 Schema ---- #


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

    # CLAUDE.md 等效内容 (注入 System Prompt，抗压缩)
    claude_md_content: str = ""

    # 规则内容 (rules/*.md)
    rules: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def default(cls) -> HarnessConfig:
        return cls()

    @classmethod
    def load(
        cls,
        project_dir: str | Path = ".",
        cli_config_path: str | None = None,
    ) -> HarnessConfig:
        """加载配置层次 + CLAUDE.md + Rules。

        这是推荐的入口方法，自动处理 5 级配置层次。

        Args:
            project_dir: 项目根目录
            cli_config_path: CLI --config 路径

        Returns:
            HarnessConfig: 加载的配置对象
        """
        # 1. 合并配置层次
        merged = load_config_hierarchy(project_dir, cli_config_path)
        config = cls.from_dict(merged)

        # 2. 加载 CLAUDE.md
        claude_content = find_claude_md(project_dir)
        if claude_content:
            config.claude_md_content = claude_content

        # 3. 加载 Rules
        config.rules = find_rules(project_dir)

        return config

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
            claude_md_content=data.get("claude_md_content", ""),
            rules=data.get("rules", []),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> HarnessConfig:
        """从 JSON 或 YAML 文件加载配置。

        Args:
            path: 配置文件路径 (.json 或 .yaml/.yml)

        Returns:
            HarnessConfig: 加载的配置对象
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        raw = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError:
                raise ImportError(
                    "PyYAML is required to load YAML config files. "
                    "Install it with: pip install pyyaml"
                )
            data = yaml.safe_load(raw)
        elif path.suffix == ".json":
            data = json.loads(raw)
        else:
            raise ValueError(f"Unsupported config file format: {path.suffix}")

        return cls.from_dict(data)

    def build_system_prompt_extra(self) -> str:
        """构建额外的系统提示 (CLAUDE.md + Rules)。"""
        parts = []

        # CLAUDE.md 内容 (抗压缩标记)
        if self.claude_md_content:
            parts.append(
                "=== CLAUDE.md (Protected — do not compress) ===\n"
                f"{self.claude_md_content.strip()}\n"
                "=== End CLAUDE.md ==="
            )

        # Rules 内容
        if self.rules:
            for rule in self.rules:
                scope = rule.get("path", "global")
                content = rule.get("content", "")
                if content:
                    parts.append(
                        f"=== Rule: {scope} ===\n"
                        f"{content.strip()}\n"
                        f"=== End Rule: {scope} ==="
                    )

        return "\n\n".join(parts)
