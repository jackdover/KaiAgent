"""权限系统 — 控制 Agent 的行为边界。"""

from __future__ import annotations

import fnmatch
from enum import Enum, IntEnum, auto
from pathlib import Path
from typing import Any


class PermissionLevel(IntEnum):
    """权限等级。"""
    NONE = 0       # 完全无权限，只能输出文本
    READ_ONLY = 1  # 只读文件系统，受限网络请求
    SANDBOX = 2    # 限定目录读写，白名单网络/命令
    FULL = 3       # 完全信任，无限制


class ResourceType(Enum):
    """资源类型。"""
    FILE_READ = auto()
    FILE_WRITE = auto()
    FILE_DELETE = auto()
    EXEC_COMMAND = auto()
    NETWORK_REQUEST = auto()
    ENV_READ = auto()


class PermissionDenied(Exception):
    """权限拒绝异常。"""

    def __init__(
        self,
        action: str,
        resource: str,
        required_level: PermissionLevel | None = None,
        reason: str = "",
    ):
        self.action = action
        self.resource = resource
        self.required_level = required_level
        self.reason = reason
        msg = f"Permission denied: {action} on '{resource}'"
        if reason:
            msg += f" ({reason})"
        if required_level is not None:
            msg += f" [required: {required_level.name}]"
        super().__init__(msg)


class PermissionPolicy:
    """权限策略 — 定义 Agent 允许访问的资源。"""

    def __init__(
        self,
        level: PermissionLevel = PermissionLevel.NONE,
        read_paths: list[str] | None = None,
        write_paths: list[str] | None = None,
        exec_commands: list[str] | None = None,
        network_hosts: list[str] | None = None,
        env_vars: list[str] | None = None,
    ):
        self.level = level
        self.read_paths = read_paths or []
        self.write_paths = write_paths or []
        self.exec_commands = exec_commands or []
        self.network_hosts = network_hosts or []
        self.env_vars = env_vars or []

    def check(
        self,
        resource_type: ResourceType,
        resource: str,
    ) -> None:
        """检查是否有权访问指定资源。

        支持传入 ResourceType 枚举或字符串 (如 "FILE_READ", "EXEC_COMMAND")。

        Raises:
            PermissionDenied: 如果没有权限
        """
        if isinstance(resource_type, str):
            try:
                resource_type = ResourceType[resource_type]
            except KeyError:
                raise ValueError(f"Unknown resource type: {resource_type}")

        if self.level == PermissionLevel.FULL:
            return

        if self.level == PermissionLevel.NONE:
            raise PermissionDenied(
                action=resource_type.name,
                resource=resource,
                required_level=PermissionLevel.READ_ONLY,
                reason="No permissions granted",
            )

        checks = {
            ResourceType.FILE_READ: self._check_read_path,
            ResourceType.FILE_WRITE: self._check_write_path,
            ResourceType.FILE_DELETE: self._check_write_path,
            ResourceType.EXEC_COMMAND: self._check_exec_command,
            ResourceType.NETWORK_REQUEST: self._check_network_host,
            ResourceType.ENV_READ: self._check_env_var,
        }

        checker = checks.get(resource_type)
        if checker:
            checker(resource)

    def _check_read_path(self, path: str) -> None:
        path = Path(path).resolve()
        for allowed in self.read_paths:
            allowed_path = Path(allowed).resolve()
            if path == allowed_path or allowed_path in path.parents:
                return
        raise PermissionDenied(
            "FILE_READ", str(path), self.level,
            f"Path not in read whitelist: {self.read_paths}",
        )

    def _check_write_path(self, path: str) -> None:
        if self.level == PermissionLevel.READ_ONLY:
            raise PermissionDenied(
                "FILE_WRITE", str(path), self.level,
                "Read-only mode",
            )
        path = Path(path).resolve()
        for allowed in self.write_paths:
            allowed_path = Path(allowed).resolve()
            if path == allowed_path or allowed_path in path.parents:
                return
        raise PermissionDenied(
            "FILE_WRITE", str(path), self.level,
            f"Path not in write whitelist: {self.write_paths}",
        )

    def _check_exec_command(self, command: str) -> None:
        cmd_name = command.split()[0] if command else ""
        if not self.exec_commands:
            raise PermissionDenied(
                "EXEC_COMMAND", command, self.level,
                "No commands allowed",
            )
        if not any(fnmatch.fnmatch(cmd_name, pat) for pat in self.exec_commands):
            raise PermissionDenied(
                "EXEC_COMMAND", command, self.level,
                f"Command not in whitelist: {self.exec_commands}",
            )

    def _check_network_host(self, host: str) -> None:
        if not self.network_hosts:
            raise PermissionDenied(
                "NETWORK_REQUEST", host, self.level,
                "No network hosts allowed",
            )
        if not any(fnmatch.fnmatch(host, pat) for pat in self.network_hosts):
            raise PermissionDenied(
                "NETWORK_REQUEST", host, self.level,
                f"Host not in whitelist: {self.network_hosts}",
            )

    def _check_env_var(self, var: str) -> None:
        if not self.env_vars:
            raise PermissionDenied(
                "ENV_READ", var, self.level,
                "No env vars allowed",
            )
        if not any(fnmatch.fnmatch(var, pat) for pat in self.env_vars):
            raise PermissionDenied(
                "ENV_READ", var, self.level,
                f"Env var not in whitelist: {self.env_vars}",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.name,
            "read_paths": self.read_paths,
            "write_paths": self.write_paths,
            "exec_commands": self.exec_commands,
            "network_hosts": self.network_hosts,
            "env_vars": self.env_vars,
        }

    @classmethod
    def sandbox(cls, base_dir: str = ".") -> PermissionPolicy:
        """创建一个沙箱级别权限策略。"""
        return cls(
            level=PermissionLevel.SANDBOX,
            read_paths=[base_dir],
            write_paths=[base_dir],
            exec_commands=["ls", "cat", "pwd", "echo", "python", "node"],
            network_hosts=["api.openai.com", "api.anthropic.com"],
            env_vars=["PATH", "HOME", "USER"],
        )

    @classmethod
    def read_only(cls, base_dir: str = ".") -> PermissionPolicy:
        """创建一个只读级别权限策略。"""
        return cls(
            level=PermissionLevel.READ_ONLY,
            read_paths=[base_dir],
            exec_commands=["ls", "cat", "pwd", "echo"],
            network_hosts=["api.openai.com"],
            env_vars=["PATH"],
        )

    @classmethod
    def full(cls) -> PermissionPolicy:
        """创建一个完全信任权限策略。"""
        return cls(level=PermissionLevel.FULL)
