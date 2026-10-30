"""The knowledge base's own MCP server: one endpoint, the knowledge base's tools.

The knowledge base is registered by name, not discovered: this server serves
nothing else, so a ``register`` that raises ends the process with the reason
instead of serving an empty catalogue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from knowledge_base_mcp_server.configs.settings import McpServerSettings, get_settings
from tools_knowledge_base.registration import SUMMARY, register

_logger = logging.getLogger("knowledge_base_mcp_server")

SERVER_NAME = "knowledge_base"

STDIO = "stdio"
HTTP = "http"

RegisterKb = Callable[[MCPServer], list[Callable[..., Any]]]


def configure_logging(settings: McpServerSettings) -> None:
    """Log to stderr, ``basicConfig``'s default; stdout belongs to the transport."""
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )


def build_server(*, register_kb: RegisterKb = register) -> tuple[MCPServer, list[str]]:
    """Create the server and register the knowledge base onto it.

    Returns:
        The server and the sorted names of the tools registered on it.

    Raises:
        SystemExit: ``register_kb`` raised (a missing embedder key, no kind
            installed, a refused tool name, an unreachable store). The message
            carries the reason, and nothing is served.
    """
    server = MCPServer(SERVER_NAME, instructions=SUMMARY)
    try:
        tools = register_kb(server)
    except Exception as exc:
        # The type too: an empty-message exception (TimeoutError()) says nothing
        # on its own, and SystemExit's message is all the operator sees.
        msg = f"knowledge base did not register: {type(exc).__name__}: {exc}"
        _logger.exception(msg)
        raise SystemExit(msg) from exc
    return server, sorted(fn.__name__ for fn in tools)


def build_app(
    settings: McpServerSettings, *, register_kb: RegisterKb = register
) -> tuple[Starlette, list[str]]:
    """Build the ASGI app. Split from :func:`main` so tests can drive it in-process."""
    server, tool_names = build_server(register_kb=register_kb)
    app = server.streamable_http_app(
        streamable_http_path=settings.path,
        # Without this the SDK's DNS-rebinding guard answers 421 Misdirected
        # Request for any Host it does not expect — which, behind Docker, is
        # every real request.
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


def main(
    *,
    settings: McpServerSettings | None = None,
    register_kb: RegisterKb = register,
    run_stdio: Callable[[MCPServer], None] = MCPServer.run,
    run_http: ServeHttp = uvicorn.run,
) -> None:
    """Serve the knowledge base over stdio or HTTP.

    ``settings`` exists so tests can drive dispatch with a constructed
    ``McpServerSettings`` instead of the process environment. ``register_kb``
    lets them register on fakes, and ``run_stdio``/``run_http`` (``MCPServer.run``,
    ``uvicorn.run``) let them see what was served, and how, without serving it.
    """
    settings = settings or get_settings()
    configure_logging(settings)
    if settings.transport == STDIO:
        # No port and no daemon: the client that spawned this process owns its lifetime.
        server, tool_names = build_server(register_kb=register_kb)
        log_report(tool_names, settings)
        run_stdio(server)
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
