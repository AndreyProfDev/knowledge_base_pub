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
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.registration import Registered


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
            require_key=lambda: None,
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
        require_key=lambda: None,
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
        require_key=lambda: None,
    )

    [(app, how)] = served.http
    assert isinstance(app, Starlette)
    assert how == {"host": settings.host, "port": settings.port, "log_config": None}
    assert served.stdio == []


@pytest.mark.parametrize("transport", [STDIO, HTTP])
def test_a_refused_key_ends_the_start_before_registering_or_serving(transport: str) -> None:
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": transport})
    served = _Served()
    registered: list[MCPServer] = []

    def refuse() -> None:
        msg = "no key: set OPEN_AI_API_KEY"
        raise KnowledgeBaseError(msg)

    def register_recording(server: MCPServer) -> Registered:
        registered.append(server)
        return register_nothing(server)

    with pytest.raises(SystemExit, match="no key: set OPEN_AI_API_KEY"):
        main(
            settings=settings,
            register_kb=register_recording,
            run_stdio=served.run_stdio,
            run_http=served.run_http,
            require_key=refuse,
        )

    assert (registered, served.stdio, served.http) == ([], [], [])


@pytest.mark.parametrize("transport", [STDIO, HTTP])
def test_the_default_key_check_reads_the_active_embedders_key(transport: str) -> None:
    """The testing overlay leaves the default openai-large key empty; KB_DATA_DIR is pinned."""
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": transport})
    served = _Served()

    with pytest.raises(SystemExit, match=r"OPEN_AI_API_KEY.*/nonexistent/kb-testing/\.env"):
        main(
            settings=settings,
            register_kb=register_nothing,
            run_stdio=served.run_stdio,
            run_http=served.run_http,
        )

    assert (served.stdio, served.http) == ([], [])


def test_http_logs_the_serving_line_before_serving(caplog: pytest.LogCaptureFixture) -> None:
    """The server's startup signal: how many tools, and the URL."""
    settings = get_settings(Environment.TESTING).model_copy(update={"transport": HTTP})
    logged_before_serving: list[list[str]] = []

    def serve(app: Starlette, /, *, host: str, port: int, log_config: None) -> None:
        logged_before_serving.append([r.getMessage() for r in caplog.records])

    with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
        main(
            settings=settings,
            register_kb=register_nothing,
            run_http=serve,
            require_key=lambda: None,
        )

    [messages] = logged_before_serving
    assert messages == [
        f"serving 0 tool(s) on http://{settings.host}:{settings.port}{settings.path}"
    ]
