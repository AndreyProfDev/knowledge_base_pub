"""``register`` — mounts the knowledge base's tools onto an MCP server.

The knowledge base's own server (``knowledge-base-mcp``,
``knowledge_base_mcp_server.app``) calls this by name on the server it built.
Raising from here declines registration, and that server then exits non-zero
with the reason on stderr. No memory kind installed, a payload field that is
not plain, or a tool name that repeats or is not a valid MCP tool name,
declines it that way. Nothing else is checked here: a missing embedding key, an
unreachable store or a dimension mismatch fails the first tool call that needs it.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from functools import partial
from typing import Any, NamedTuple

from mcp.server import MCPServer

from knowledge_base_config import environment_from_env
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.readiness import require_kinds
from tools_knowledge_base.server import tools_kinds, tools_memory

SUMMARY = (
    "A personal knowledge base of typed memories, one tool set per installed kind: "
    "store_<kind>, update_<kind>, get_<kind>, list_<kind> and delete_<kind>; "
    "search_memory searches every kind semantically. Writes are queued in "
    "this server process: poll get_memory_request until done. An unknown request id "
    "means another process or a restart, and the write is lost."
)

# The MCP specification's tool name: these characters, 1 to 128 of them.
_MCP_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class Registered(NamedTuple):
    """What ``register`` mounted: the tool functions, the queue's backlog count and a drain."""

    tools: list[Callable[..., Any]]
    queued: Callable[[], int]
    drain: Callable[[float], int]


def register(
    server: MCPServer,
    *,
    settings: KnowledgeBaseSettings | None = None,
    open_kb: Callable[[KnowledgeBaseSettings], KnowledgeBase] = open_knowledge_base,
) -> Registered:
    """Register the generic tools and every installed kind's tools onto ``server``.

    Returns:
        The registered tool functions, a count of the writes still queued, and a
        bounded drain of them (seconds in, writes left out).

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
        KnowledgeBaseError: no memory kind is installed; a payload field is not
            plain; or a tool name breaks the name rule.
        pydantic.PydanticInvalidForJsonSchema: a kind's payload cannot be described as
            a JSON schema.
        Exception: whatever ``open_kb`` raises.
    """
    settings = settings or get_settings(environment_from_env())
    kb = open_kb(settings)
    require_kinds(kb)
    tools = [*tools_memory.tools(kb), *tools_kinds.tools(kb)]
    _check_names([fn.__name__ for fn, _ in tools])
    for fn, hints in tools:
        server.tool(annotations=hints)(fn)
    return Registered([fn for fn, _ in tools], kb.writes.queued, partial(_drain, kb))


def _drain(kb: KnowledgeBase, seconds: float) -> int:
    """Run the queued writes for up to ``seconds``; return how many are still queued.

    The run is on a daemon thread, so a write stuck past the bound cannot hold the
    process from exiting.
    """
    worker = threading.Thread(target=kb.writes.drain, name="kb-exit-drain", daemon=True)
    worker.start()
    worker.join(seconds)
    return kb.writes.queued()


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
