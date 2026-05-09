"""内置 Plugin: 文件操作。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness.plugins.interface import CapabilityType, Plugin, PluginMetadata
from harness.core.types import ToolDefinition


class FilePlugin(Plugin):
    """文件操作 Plugin — 读取、写入、列出文件。"""

    metadata = PluginMetadata(
        name="file",
        version="0.1.0",
        description="File system operations: read, write, list files",
        capabilities=[CapabilityType.TOOL, CapabilityType.SENSOR],
    )

    def __init__(self):
        self._workdir: str = "."
        self._harness: Any = None

    async def load(self, config: dict[str, Any]) -> None:
        self._workdir = config.get("workdir", ".")

    async def init(self, harness: Any) -> None:
        self._harness = harness

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="read_file",
                description="Read the contents of a file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path to read",
                        },
                    },
                    "required": ["path"],
                },
            ),
            ToolDefinition(
                name="write_file",
                description="Write content to a file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "content": {
                            "type": "string",
                            "description": "Content to write",
                        },
                    },
                    "required": ["path", "content"],
                },
            ),
            ToolDefinition(
                name="list_files",
                description="List files in a directory",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern (e.g. '*.py')",
                        },
                    },
                    "required": ["path"],
                },
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict) -> str:
        """执行工具调用。"""
        if name == "read_file":
            return await self._read_file(arguments["path"])
        elif name == "write_file":
            return await self._write_file(
                arguments["path"], arguments["content"]
            )
        elif name == "list_files":
            return await self._list_files(
                arguments["path"],
                arguments.get("pattern", "*"),
            )
        return f"Unknown tool: {name}"

    async def _read_file(self, path: str) -> str:
        full_path = Path(self._workdir) / path
        if not full_path.exists():
            return f"Error: File not found: {path}"
        if not full_path.is_file():
            return f"Error: Not a file: {path}"
        try:
            content = full_path.read_text(encoding="utf-8")
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    async def _write_file(self, path: str, content: str) -> str:
        full_path = Path(self._workdir) / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            full_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    async def _list_files(self, path: str, pattern: str) -> str:
        full_path = Path(self._workdir) / path
        if not full_path.exists():
            return f"Error: Path not found: {path}"
        if not full_path.is_dir():
            return f"Error: Not a directory: {path}"
        try:
            files = list(full_path.glob(pattern))
            if not files:
                return f"No files matching '{pattern}' in {path}"
            lines = [f"{f.name} ({'dir' if f.is_dir() else 'file'})" for f in files]
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing files: {e}"
