"""The knowledge base registered on an in-process MCP server, called as a client calls it."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer
from mcp.types import CallToolResult
from pydantic import SecretStr

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.registration import register


def keyed_settings(active: str = "openai-small", api_key: str = "sk-test") -> KnowledgeBaseSettings:
    """The testing overlay with ``active`` forced, whatever ``KB_EMBEDDER`` the shell exports."""
    settings = get_settings(Environment.TESTING)
    embeddings = settings.embeddings
    embedder = embeddings.embedders[active].model_copy(update={"api_key": SecretStr(api_key)})
    return settings.model_copy(
        update={
            "embeddings": embeddings.model_copy(
                update={"active": active, "embedders": {**embeddings.embedders, active: embedder}}
            )
        }
    )


def register_nothing(server: MCPServer) -> list[Callable[..., Any]]:
    """Dispatch is under test, not the knowledge base."""
    return []


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
