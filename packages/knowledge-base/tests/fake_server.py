"""The knowledge base registered on an in-process MCP server, called as a client calls it."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fake_kb import temp_sqlite_settings
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import SecretStr

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.registration import Registered, register


def keyed_settings(active: str = "openai-large", api_key: str = "sk-test") -> KnowledgeBaseSettings:
    """The testing overlay with ``active`` forced, whatever ``KB_EMBEDDER`` the shell exports."""
    settings = temp_sqlite_settings()
    embeddings = settings.embeddings
    embedder = embeddings.embedders[active].model_copy(update={"api_key": SecretStr(api_key)})
    return settings.model_copy(
        update={
            "embeddings": embeddings.model_copy(
                update={"active": active, "embedders": {**embeddings.embedders, active: embedder}}
            )
        }
    )


def _drained(seconds: float) -> int:
    return 0


def register_nothing(server: MCPServer) -> Registered:
    """Dispatch is under test, not the knowledge base."""
    return Registered([], lambda: 0, _drained)


def serve(kb: KnowledgeBase) -> MCPServer:
    """A server with ``kb``'s tools registered on it."""
    server = MCPServer("test")
    register(server, settings=keyed_settings(), open_kb=lambda _settings: kb)
    return server


def call(server: MCPServer, name: str, **arguments: object) -> dict[str, Any]:
    """JSON arguments, validated against the tool's own schema; its structured result."""
    result = asyncio.run(server.call_tool(name, arguments))
    assert isinstance(result, CallToolResult), name
    assert not result.is_error, (name, result)
    return result.structured_content or {}


def call_error(server: MCPServer, name: str, **arguments: object) -> str:
    """The text of the error a tool call answers with."""
    with pytest.raises(ToolError) as raised:
        asyncio.run(server.call_tool(name, arguments))
    return str(raised.value).removeprefix(f"Error executing tool {name}: ")
