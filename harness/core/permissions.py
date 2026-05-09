"""权限系统 — 控制 Agent 的行为边界。

支持 deny-first 评估链: deny → ask → allow。
支持多种审批模式: auto, interactive, plan, bubble。
支持工具级权限过滤 (glob 模式)。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from pathlib import Path
from typing import Any, Callable


class PermissionLevel(IntEnum):
    """权限等级。"""
    NONE = 0       # 完全无权限，只能输出文本
    READ_ONLY = 1  # 只读文件系统，受限网络请求
    SANDBOX = 2    # 限定目录读写，白名单网络/命令
    FULL = 3       # 完全信任，无限制


class ApprovalMode(Enum):
    """审批模式。"""
    AUTO = "auto"          # 自动批准 (ML classifier 占位)
    INTERACTIVE = "interactive"  # 交互式审批
    PLAN = "plan"          # 仅显示计划，不执行
    BUBBLE = "bubble"      # 子代理冒泡到父级审批


class ResourceType(Enum):
    """资源类型。"""
    FILE_READ = auto()
    FILE_WRITE = auto()
    FILE_DELETE = auto()
    EXEC_COMMAND = auto()
    NETWORK_REQUEST = auto()
    ENV_READ = auto()
    TOOL_CALL = auto()  # 通用工具调用

    @classmethod
    def from_tool_name(cls, tool_name: str) -> ResourceType:
        """根据工具名称猜测资源类型。"""
        mapping = {
            "read_file": cls.FILE_READ,
            "list_files": cls.FILE_READ,
            "write_file": cls.FILE_WRITE,
            "execute_command": cls.EXEC_COMMAND,
            "http_get": cls.NETWORK_REQUEST,
            "http_post": cls.NETWORK_REQUEST,
        }
        return mapping.get(tool_name, cls.TOOL_CALL)


class PermissionDenied(Exception):
    """权限拒绝异常。"""

    def __init__(
        self,
        action: str,
        resource: str,
        required_level: PermissionLevel | None = None,
        reason: str = "",
        deny_rule: str | None = None,
    ):
        self.action = action
        self.resource = resource
        self.required_level = required_level
        self.reason = reason
        self.deny_rule = deny_rule
        msg = f"Permission denied: {action} on '{resource}'"
        if reason:
            msg += f" ({reason})"
        if required_level is not None:
            msg += f" [required: {required_level.name}]"
        if deny_rule:
            msg += f" [denied by rule: {deny_rule}]"
        super().__init__(msg)


class PermissionApprovalRequired(Exception):
    """需要用户审批的权限异常 — 用于交互式审批模式。"""

    def __init__(
        self,
        action: str,
        resource: str,
        message: str = "",
    ):
        self.action = action
        self.resource = resource
        self.message = message or f"Approval required: {action} on '{resource}'"
        super().__init__(self.message)


@dataclass
class DenyRule:
    """拒绝规则 — 匹配条件 + 原因。"""
    pattern: str                 # glob 模式 (如 "rm", "rm -rf *", "/etc/**")
    resource_type: ResourceType  # 资源类型
    reason: str = ""             # 拒绝原因
    enabled: bool = True         # 是否启用


@dataclass
class ToolPermission:
    """工具级权限规则。"""
    tool_pattern: str            # 工具名 glob 模式 (如 "read_*", "execute_command")
    allowed: bool = True         # True=允许, False=拒绝
    resource_pattern: str | None = None  # 资源路径 glob 模式 (如 "/etc/**")
    reason: str = ""


@dataclass
class PendingApproval:
    """待审批的权限请求。"""
    action: str
    resource: str
    resource_type: ResourceType
    tool_name: str
    message: str = ""


class MockApprovalCallback:
    """模拟审批回调 — 在没有真实 UI 时使用。

    在 interactive 模式下，默认拒绝。
    替换此回调可实现自定义审批逻辑。
    """

    def __init__(self, callback: Callable[[PendingApproval], bool] | None = None):
        self._callback = callback

    async def request_approval(self, pending: PendingApproval) -> bool:
        """请求用户审批。子类应重写此方法。"""
        if self._callback:
            return self._callback(pending)
        # 默认拒绝
        return False


class PermissionPolicy:
    """权限策略 — 定义 Agent 允许访问的资源。

    评估链 (deny-first):
        1. 检查 deny 规则 (deny → 立即拒绝)
        2. 检查 ask 规则 (pending → 需要审批)
        3. 检查 allow 规则 (FULL → 通过)
        4. 检查白名单 (路径、命令、网络、环境变量)
        5. 未匹配 → 拒绝
    """

    def __init__(
        self,
        level: PermissionLevel = PermissionLevel.NONE,
        read_paths: list[str] | None = None,
        write_paths: list[str] | None = None,
        exec_commands: list[str] | None = None,
        network_hosts: list[str] | None = None,
        env_vars: list[str] | None = None,
        deny_rules: list[DenyRule] | None = None,
        tool_permissions: list[ToolPermission] | None = None,
        approval_mode: ApprovalMode = ApprovalMode.AUTO,
        approval_callback: MockApprovalCallback | None = None,
    ):
        self.level = level
        self.read_paths = read_paths or []
        self.write_paths = write_paths or []
        self.exec_commands = exec_commands or []
        self.network_hosts = network_hosts or []
        self.env_vars = env_vars or []
        self.deny_rules = deny_rules or []
        self.tool_permissions = tool_permissions or []
        self.approval_mode = approval_mode
        self.approval_callback = approval_callback or MockApprovalCallback()

    def check(
        self,
        resource_type: ResourceType,
        resource: str,
    ) -> None:
        """检查是否有权访问指定资源。

        Args:
            resource_type: 资源类型 (枚举或字符串)
            resource: 资源标识符

        Raises:
            PermissionDenied: 如果被拒绝
            PermissionApprovalRequired: 如果需要交互式审批
        """
        if isinstance(resource_type, str):
            try:
                resource_type = ResourceType[resource_type]
            except KeyError:
                raise ValueError(f"Unknown resource type: {resource_type}")

        if self.level == PermissionLevel.FULL:
            return

        # 1. Deny-first: 检查 deny 规则
        for rule in self.deny_rules:
            if not rule.enabled:
                continue
            if rule.resource_type != resource_type:
                continue
            if fnmatch.fnmatch(resource, rule.pattern):
                raise PermissionDenied(
                    action=resource_type.name,
                    resource=resource,
                    reason=rule.reason or f"Denied by rule: {rule.pattern}",
                    deny_rule=rule.pattern,
                )

        if self.level == PermissionLevel.NONE:
            raise PermissionDenied(
                action=resource_type.name,
                resource=resource,
                required_level=PermissionLevel.READ_ONLY,
                reason="No permissions granted",
            )

        # 2. 交互式审批模式
        if self.approval_mode in (ApprovalMode.INTERACTIVE, ApprovalMode.PLAN):
            raise PermissionApprovalRequired(
                action=resource_type.name,
                resource=resource,
                message=f"{self.approval_mode.value} mode: {resource_type.name} on '{resource}'"
                if self.approval_mode == ApprovalMode.PLAN
                else f"Approval needed: {resource_type.name} on '{resource}'",
            )

        # 3. 检查资源白名单
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

    def check_tool(self, tool_name: str, resource: str = "") -> None:
        """检查工具级权限。

        评估链:
            1. 工具级 deny 规则
            2. 工具级 allow 规则
            3. 回退到资源级 check

        Args:
            tool_name: 工具名称
            resource: 工具参数中的资源标识符

        Raises:
            PermissionDenied: 如果被拒绝
        """
        # 1. 检查工具级 deny
        for tp in self.tool_permissions:
            if not tp.allowed and fnmatch.fnmatch(tool_name, tp.tool_pattern):
                if tp.resource_pattern is None or fnmatch.fnmatch(resource, tp.resource_pattern):
                    raise PermissionDenied(
                        action=tool_name,
                        resource=resource or tool_name,
                        reason=tp.reason or f"Tool denied by rule: {tp.tool_pattern}",
                        deny_rule=tp.tool_pattern,
                    )

        # 2. 检查工具级 allow
        for tp in self.tool_permissions:
            if tp.allowed and fnmatch.fnmatch(tool_name, tp.tool_pattern):
                if tp.resource_pattern is None or fnmatch.fnmatch(resource, tp.resource_pattern):
                    return  # 明确允许，跳过资源级检查

        # 3. 回退到资源级 check
        resource_type = ResourceType.from_tool_name(tool_name)
        if resource:
            self.check(resource_type, resource)
        else:
            self.check(resource_type, tool_name)

    async def request_approval(self, pending: PendingApproval) -> bool:
        """请求用户审批 (交互式模式)。"""
        return await self.approval_callback.request_approval(pending)

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

    def add_deny_rule(
        self,
        pattern: str,
        resource_type: ResourceType = ResourceType.EXEC_COMMAND,
        reason: str = "",
    ) -> None:
        """添加拒绝规则。"""
        self.deny_rules.append(DenyRule(
            pattern=pattern,
            resource_type=resource_type,
            reason=reason,
        ))

    def add_tool_permission(
        self,
        tool_pattern: str,
        allowed: bool = True,
        resource_pattern: str | None = None,
        reason: str = "",
    ) -> None:
        """添加工具级权限规则。"""
        self.tool_permissions.append(ToolPermission(
            tool_pattern=tool_pattern,
            allowed=allowed,
            resource_pattern=resource_pattern,
            reason=reason,
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.name,
            "approval_mode": self.approval_mode.value,
            "read_paths": self.read_paths,
            "write_paths": self.write_paths,
            "exec_commands": self.exec_commands,
            "network_hosts": self.network_hosts,
            "env_vars": self.env_vars,
            "deny_rules": [
                {"pattern": r.pattern, "resource_type": r.resource_type.name, "reason": r.reason}
                for r in self.deny_rules
            ],
            "tool_permissions": [
                {"tool_pattern": tp.tool_pattern, "allowed": tp.allowed, "reason": tp.reason}
                for tp in self.tool_permissions
            ],
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
            deny_rules=[
                DenyRule("rm", ResourceType.EXEC_COMMAND, "rm is disabled in sandbox mode"),
                DenyRule("rmdir", ResourceType.EXEC_COMMAND, "rmdir is disabled in sandbox mode"),
                DenyRule("del", ResourceType.EXEC_COMMAND, "del is disabled in sandbox mode"),
            ],
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

    @classmethod
    def auto(
        cls,
        base_dir: str = ".",
        auto_approve_patterns: list[str] | None = None,
    ) -> PermissionPolicy:
        """创建一个自动审批权限策略 (带 ML 分类器占位)。

        自动批准匹配模式的工具调用，不匹配的降级为 ask。
        """
        return cls(
            level=PermissionLevel.SANDBOX,
            read_paths=[base_dir],
            write_paths=[base_dir],
            exec_commands=["ls", "cat", "pwd", "echo", "python", "node"],
            network_hosts=["*"],
            env_vars=["PATH", "HOME", "USER"],
            approval_mode=ApprovalMode.AUTO,
        )
