"""The knowledge base's own MCP server: one endpoint, the knowledge base's tools.

The knowledge base is registered by name, not discovered: this server serves
nothing else, so a ``register`` that raises ends the process with the reason
instead of serving an empty catalogue.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Protocol

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from knowledge_base_config import environment_from_env
from knowledge_base_mcp_server.configs.settings import McpServerSettings, get_settings
from tools_knowledge_base.configs.settings import get_settings as kb_get_settings
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.readiness import require_embedder_key
from tools_knowledge_base.registration import SUMMARY, Registered, register

_logger = logging.getLogger("knowledge_base_mcp_server")

SERVER_NAME = "knowledge_base"

STDIO = "stdio"
HTTP = "http"

# How long stdin EOF waits for queued writes: a client usually kills a slow exit soon.
DRAIN_SECONDS = 5.0

RegisterKb = Callable[[MCPServer], Registered]


def configure_logging(settings: McpServerSettings) -> None:
    """Log to stderr, ``basicConfig``'s default; stdout belongs to the transport."""
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )


def build_server(
    *, register_kb: RegisterKb = register
) -> tuple[MCPServer, list[str], Callable[[float], int]]:
    """Create the server and register the knowledge base onto it.

    Returns:
        The server, the sorted names of the tools registered on it, and a bounded
        drain of the write queue (seconds in, writes still queued out).

    Raises:
        SystemExit: ``register_kb`` raised (no kind installed, a refused tool
            name). The message carries the reason, and nothing is served. An
            unreachable store or an uninstalled backend do not end up here:
            nothing is opened until a tool call needs it, so the first such call
            fails with the reason instead. A missing embedder key is refused
            earlier, by :func:`main`.
    """
    server = MCPServer(SERVER_NAME, instructions=SUMMARY)
    try:
        registered = register_kb(server)
    except Exception as exc:
        # The type too: an empty-message exception (TimeoutError()) says nothing
        # on its own, and SystemExit's message is all the operator sees.
        msg = f"knowledge base did not register: {type(exc).__name__}: {exc}"
        _logger.exception(msg)
        raise SystemExit(msg) from exc
    return server, sorted(fn.__name__ for fn in registered.tools), registered.drain


def build_app(
    settings: McpServerSettings, *, register_kb: RegisterKb = register
) -> tuple[Starlette, list[str]]:
    """Build the ASGI app. Split from :func:`main` so tests can drive it in-process."""
    server, tool_names, _ = build_server(register_kb=register_kb)
    app = server.streamable_http_app(
        streamable_http_path=settings.path,
        # Without this the SDK's DNS-rebinding guard answers 421 Misdirected
        # Request for any Host it does not expect.
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        ),
    )
    return app, tool_names


def log_report(tool_names: list[str], settings: McpServerSettings) -> None:
    """Say how many tools registered and where they are served."""
    where = (
        "stdio"
        if settings.transport == STDIO
        else f"http://{settings.host}:{settings.port}{settings.path}"
    )
    _logger.info("serving %d tool(s) on %s", len(tool_names), where)


class ServeHttp(Protocol):
    """``uvicorn.run``'s shape, as ``main`` calls it."""

    def __call__(self, app: Starlette, /, *, host: str, port: int, log_config: None) -> None:
        """Serve ``app`` on ``host:port`` until stopped."""


def check_embedder_key() -> None:
    """Raise ``KnowledgeBaseError`` if the active embedder needs a key and has none."""
    require_embedder_key(kb_get_settings(environment_from_env()))


def main(
    *,
    settings: McpServerSettings | None = None,
    register_kb: RegisterKb = register,
    run_stdio: Callable[[MCPServer], None] = MCPServer.run,
    run_http: ServeHttp = uvicorn.run,
    drain_seconds: float = DRAIN_SECONDS,
    require_key: Callable[[], None] = check_embedder_key,
) -> None:
    """Serve the knowledge base over stdio or HTTP.

    ``settings`` exists so tests can drive dispatch with a constructed
    ``McpServerSettings`` instead of the process environment. ``register_kb``
    lets them register on fakes, and ``run_stdio``/``run_http`` (``MCPServer.run``,
    ``uvicorn.run``) let them see what was served, and how, without serving it.
    Over stdio, writes still queued when stdin closes get ``drain_seconds`` to finish;
    those left are lost, and logged. ``require_key`` runs first, for both
    transports: a missing embedder key ends the process with the reason and the
    ``.env`` path, before anything is registered.
    """
    settings = settings or get_settings()
    configure_logging(settings)
    try:
        require_key()
    except KnowledgeBaseError as exc:
        raise SystemExit(str(exc)) from exc
    if settings.transport == STDIO:
        # No port and no daemon: the client that spawned this process owns its lifetime.
        server, tool_names, drain = build_server(register_kb=register_kb)
        log_report(tool_names, settings)
        run_stdio(server)
        if settings.debug_modules:
            _logger.info("modules: %s", ",".join(sorted(sys.modules)))
        # The client closes stdin when its session ends: finish the accepted writes,
        # for a bounded time, so a store followed at once by exit is not lost.
        lost = drain(drain_seconds)
        _logger.log(
            logging.WARNING if lost else logging.INFO, "%d write(s) still queued at exit", lost
        )
        return
    if settings.transport != HTTP:
        msg = (
            f"transport={settings.transport!r} is not {STDIO!r} or {HTTP!r}; "
            f"set MCP_TRANSPORT or the transport setting."
        )
        raise SystemExit(msg)
    app, tool_names = build_app(settings, register_kb=register_kb)
    log_report(tool_names, settings)
    # log_config=None: uvicorn keeps configure_logging's setup instead of its own.
    run_http(app, host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()


__all__ = ["build_app", "build_server", "main"]
