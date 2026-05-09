"""内置 Plugin: Shell 命令执行。"""

from __future__ import annotations

import asyncio
from typing import Any

from harness.plugins.interface import CapabilityType, Plugin, PluginMetadata
from harness.core.types import ToolDefinition


class ShellPlugin(Plugin):
    """Shell 命令 Plugin — 执行系统命令。"""

    metadata = PluginMetadata(
        name="shell",
        version="0.1.0",
        description="Execute shell commands in a subprocess",
        capabilities=[CapabilityType.TOOL],
    )

    def __init__(self):
        self._timeout: int = 30
        self._harness: Any = None

    async def load(self, config: dict[str, Any]) -> None:
        self._timeout = config.get("timeout", 30)

    async def init(self, harness: Any) -> None:
        self._harness = harness

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="execute_command",
                description="Execute a shell command and return its output",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default 30)",
                        },
                    },
                    "required": ["command"],
                },
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict) -> str:
        if name == "execute_command":
            return await self._run_command(
                arguments["command"],
                arguments.get("timeout", self._timeout),
            )
        return f"Unknown tool: {name}"

    async def _run_command(self, command: str, timeout: int) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return f"Error: Command timed out after {timeout}s"

            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                if output:
                    output += "\n--- stderr ---\n"
                output += stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                output += f"\n(exit code: {proc.returncode})"

            return output if output else "(no output)"

        except FileNotFoundError:
            return f"Error: Command not found: {command.split()[0]}"
        except Exception as e:
            return f"Error executing command: {e}"
