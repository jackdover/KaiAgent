"""内置 Plugin: HTTP 网络请求。"""

from __future__ import annotations

from typing import Any

from harness.plugins.interface import CapabilityType, Plugin, PluginMetadata
from harness.core.types import ToolDefinition


class WebPlugin(Plugin):
    """网络请求 Plugin — 发送 HTTP 请求。"""

    metadata = PluginMetadata(
        name="web",
        version="0.1.0",
        description="HTTP requests: fetch URLs, query APIs",
        capabilities=[CapabilityType.TOOL, CapabilityType.SENSOR],
    )

    def __init__(self):
        self._timeout: int = 15
        self._harness: Any = None

    async def load(self, config: dict[str, Any]) -> None:
        self._timeout = config.get("timeout", 15)

    async def init(self, harness: Any) -> None:
        self._harness = harness

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="http_get",
                description="Perform an HTTP GET request to a URL",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to fetch",
                        },
                    },
                    "required": ["url"],
                },
            ),
            ToolDefinition(
                name="http_post",
                description="Perform an HTTP POST request to a URL",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to post to",
                        },
                        "body": {
                            "type": "object",
                            "description": "JSON body",
                        },
                    },
                    "required": ["url", "body"],
                },
            ),
        ]

    async def execute_tool(self, name: str, arguments: dict) -> str:
        if name == "http_get":
            return await self._http_get(arguments["url"])
        elif name == "http_post":
            return await self._http_post(
                arguments["url"], arguments.get("body", {})
            )
        return f"Unknown tool: {name}"

    async def _http_get(self, url: str) -> str:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, follow_redirects=True)
                return f"[{resp.status_code}] {resp.text[:2000]}"
        except ImportError:
            return await self._fallback_get(url)
        except Exception as e:
            return f"Error fetching {url}: {e}"

    async def _fallback_get(self, url: str) -> str:
        """不使用 httpx 时的回退方案。"""
        try:
            import urllib.request
            import json
            req = urllib.request.Request(url, headers={"User-Agent": "Harness/0.1"})
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                return f"[{resp.status}] {data[:2000]}"
        except Exception as e:
            return f"Error fetching {url}: {e}"

    async def _http_post(self, url: str, body: dict) -> str:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body)
                return f"[{resp.status_code}] {resp.text[:2000]}"
        except ImportError:
            return "httpx not available; POST not supported without httpx"
        except Exception as e:
            return f"Error posting to {url}: {e}"
