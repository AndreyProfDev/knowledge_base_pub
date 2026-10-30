"""Transport selection: stdio for a client-spawned process, HTTP for a daemon."""

from __future__ import annotations

import logging

import pytest
from fake_server import register_nothing
from mcp.server import MCPServer
from starlette.applications import Starlette

from knowledge_base_config import Environment
from knowledge_base_mcp_server.app import HTTP, SERVER_NAME, STDIO, main
from knowledge_base_mcp_server.configs.settings import get_settings


class _Served:
    """Stands in for ``MCPServer.run`` and ``uvicorn.run``: records what each was handed."""

    def __init__(self) -> None:
        self.stdio: list[MCPServer] = []
        self.http: list[tuple[Starlette, dict[str, object]]] = []

    def run_stdio(self, server: MCPServer) -> None:
        self.stdio.append(server)

    def run_http(self, app: Starlette, /, *, host: str, port: int, log_config: None) -> None:
        self.http.append((app, {"host": host, "port": port, "log_config": log_config}))


def test_unknown_transport_exits_with_a_named_value() -> None:
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": "carrier-pigeon"})
    served = _Served()

    with pytest.raises(SystemExit, match="carrier-pigeon"):
        main(
            settings=settings,
            register_kb=register_nothing,
            run_stdio=served.run_stdio,
            run_http=served.run_http,
        )

    assert (served.stdio, served.http) == ([], [])


def test_stdio_runs_the_knowledge_base_server_and_never_starts_uvicorn() -> None:
    """stdio must not bind a port — the client owns stdin/stdout, not a socket."""
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": STDIO})
    served = _Served()

    main(
        settings=settings,
        register_kb=register_nothing,
        run_stdio=served.run_stdio,
        run_http=served.run_http,
    )

    [server] = served.stdio
    assert server.name == SERVER_NAME == "knowledge_base"
    assert served.http == []


def test_http_serves_the_app_on_the_settings_and_never_starts_stdio() -> None:
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": HTTP})
    served = _Served()

    main(
        settings=settings,
        register_kb=register_nothing,
        run_stdio=served.run_stdio,
        run_http=served.run_http,
    )

    [(app, how)] = served.http
    assert isinstance(app, Starlette)
    assert how == {"host": settings.host, "port": settings.port, "log_config": None}
    assert served.stdio == []


def test_http_logs_the_serving_line_before_serving(caplog: pytest.LogCaptureFixture) -> None:
    """The container's only startup signal: how many tools, and the URL."""
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": HTTP})
    logged_before_serving: list[list[str]] = []

    def serve(app: Starlette, /, *, host: str, port: int, log_config: None) -> None:
        logged_before_serving.append([r.getMessage() for r in caplog.records])

    with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
        main(settings=settings, register_kb=register_nothing, run_http=serve)

    [messages] = logged_before_serving
    assert messages == [
        f"serving 0 tool(s) on http://{settings.host}:{settings.port}{settings.path}"
    ]
