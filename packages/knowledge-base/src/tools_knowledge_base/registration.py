"""``register`` — mounts the knowledge base's tools onto an MCP server.

The knowledge base's own server (``knowledge-base-mcp``,
``knowledge_base_mcp_server.app``) calls this by name on the server it built.
Raising from here declines registration, and that server then exits non-zero
with the reason on stderr: a missing embedding key stops startup instead of
failing every store at call time. A payload field that is not plain, or a tool
name that repeats or is not a valid MCP tool name, declines it the same way.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from mcp.server import MCPServer

from knowledge_base_config import environment_from_env
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.readiness import require_embedder_key, require_kinds
from tools_knowledge_base.server import tools_kinds, tools_memory

SUMMARY = (
    "A personal knowledge base of typed memories, one tool set per installed kind: "
    "store_<kind>, update_<kind>, get_<kind>, list_<kind> and delete_<kind>; "
    "search_memory searches every kind semantically. Writes are queued: poll "
    "get_memory_request until done."
)

# The MCP specification's tool name: these characters, 1 to 128 of them.
_MCP_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def register(
    server: MCPServer,
    *,
    settings: KnowledgeBaseSettings | None = None,
    open_kb: Callable[[KnowledgeBaseSettings], KnowledgeBase] = open_knowledge_base,
) -> list[Callable[..., Any]]:
    """Register the generic tools and every installed kind's tools onto ``server``.

    Two rules decide what may mount: every payload field is plain (no alias, not
    excluded, an identifier that is not a keyword, not ``id``; see ``tools_kinds``),
    and every tool name is unique and a valid MCP tool name (letters, digits, ``_``,
    ``-``, ``.``; 1 to 128 characters).

    Args:
        server: The server to mount the tools onto.
        settings: Override for the loaded configuration; tests pass a keyed copy.
        open_kb: Opens the one ``KnowledgeBase`` every tool closes over; tests
            open one on fakes here instead of patching anything.

    Raises:
        KnowledgeBaseError: the active embedder has no API key. Checked here, not
            at first call, so the tools never appear in a catalogue they cannot serve.
            Also: no memory kind is installed; a payload field is not plain; a tool
            name breaks the name rule; or, from ``open_kb``, the collection's vectors
            are not the embedder's dimension.
        pydantic.PydanticInvalidForJsonSchema: a kind's payload cannot be described as
            a JSON schema.
        Exception: whatever else ``open_kb`` raises, such as an unreachable store.
    """
    settings = settings or get_settings(environment_from_env())
    require_embedder_key(settings)
    kb = open_kb(settings)
    require_kinds(kb)
    tools = [*tools_memory.tools(kb), *tools_kinds.tools(kb)]
    _check_names([fn.__name__ for fn, _ in tools])
    for fn, hints in tools:
        server.tool(annotations=hints)(fn)
    return [fn for fn, _ in tools]


def _check_names(names: list[str]) -> None:
    """Refuse tool names that repeat or MCP does not allow."""
    problems = {
        "repeated": sorted({name for name in names if names.count(name) > 1}),
        "not a valid MCP tool name": [n for n in names if not _MCP_TOOL_NAME.fullmatch(n)],
    }
    found = "; ".join(
        f"{what}: {', '.join(map(repr, bad))}" for what, bad in problems.items() if bad
    )
    if found:
        msg = f"knowledge base tool names refused, {found}"
        raise KnowledgeBaseError(msg)
