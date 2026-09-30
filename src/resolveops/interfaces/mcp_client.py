from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Protocol, cast

from mcp import Client
from mcp.server import MCPServer


class MCPReadUnavailable(RuntimeError):
    """The configured read-only MCP source could not be reached or validated."""


class MCPReadDenied(PermissionError):
    """A request tried to escape the client's tenant or read-only boundary."""


class ExternalReadClient(Protocol):
    def call_read_tool(
        self,
        tenant_id: str,
        tool_name: str,
        arguments: Mapping[str, str],
    ) -> dict[str, object]: ...


class MCPReadClient:
    """Small fail-closed consumer for an isolated, tenant-bound MCP simulator."""

    _ALLOWED_TOOLS = frozenset({"get_case"})

    def __init__(
        self,
        server: MCPServer | str,
        *,
        tenant_id: str,
        timeout_seconds: float = 5,
    ) -> None:
        self._server = server
        self._tenant_id = tenant_id
        self._timeout_seconds = timeout_seconds

    def call_read_tool(
        self,
        tenant_id: str,
        tool_name: str,
        arguments: Mapping[str, str],
    ) -> dict[str, object]:
        if tenant_id != self._tenant_id:
            raise MCPReadDenied("MCP tenant boundary violation")
        if tool_name not in self._ALLOWED_TOOLS:
            raise MCPReadDenied("MCP tool is not approved for agent consumption")
        try:
            return asyncio.run(self._call(tool_name, dict(arguments)))
        except MCPReadDenied:
            raise
        except Exception as exc:
            raise MCPReadUnavailable("read-only MCP source is unavailable") from exc

    async def _call(self, tool_name: str, arguments: dict[str, str]) -> dict[str, object]:
        async with Client(self._server, raise_exceptions=True) as client:
            result = await client.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=self._timeout_seconds,
            )
        if not isinstance(result.structured_content, dict):
            raise MCPReadUnavailable("MCP response did not contain structured data")
        return cast(dict[str, object], result.structured_content)
