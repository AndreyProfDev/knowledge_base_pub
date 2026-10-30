"""The startup log, and the refusal to serve when the knowledge base cannot register."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest
from mcp.server import MCPServer
from starlette.applications import Starlette

from knowledge_base_config import Environment
from knowledge_base_mcp_server.app import STDIO, build_server, log_report, main
from knowledge_base_mcp_server.configs.settings import McpServerSettings, get_settings


def settings(**overrides: object) -> McpServerSettings:
    return get_settings(Environment.TESTING).model_copy(update=overrides)


def _refuse(server: MCPServer) -> list[Callable[..., Any]]:
    msg = "active embedder 'openai-small' has no API key: set OPEN_AI_API_KEY"
    raise RuntimeError(msg)


class TestLogReport:
    def test_counts_the_tools_on_stdio(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
            log_report(["search_memory", "store_knowledge"], settings(transport=STDIO))
        assert [r.getMessage() for r in caplog.records] == ["serving 2 tool(s) on stdio"]

    def test_the_http_url_is_logged_for_a_network_transport(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        pinned = settings(transport="http", host="0.0.0.0", port=9799, path="/mcp")
        with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
            log_report(["search_memory"], pinned)
        assert "http://0.0.0.0:9799/mcp" in caplog.text


class TestRegistrationFailure:
    def test_a_raising_register_exits_with_the_reason(self) -> None:
        """Nothing else is served here, so a refusal must stop the process, not hide."""
        with pytest.raises(SystemExit, match=r"did not register: .*set OPEN_AI_API_KEY"):
            build_server(register_kb=_refuse)

    def test_an_empty_message_still_names_the_exception_and_logs_the_traceback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _time_out(server: MCPServer) -> list[Callable[..., Any]]:
            raise TimeoutError

        with (
            caplog.at_level(logging.ERROR, logger="knowledge_base_mcp_server"),
            pytest.raises(SystemExit, match=r"did not register: TimeoutError"),
        ):
            build_server(register_kb=_time_out)

        [record] = caplog.records
        assert record.getMessage() == "knowledge base did not register: TimeoutError: "
        assert record.exc_info is not None
        assert record.exc_info[0] is TimeoutError

    @pytest.mark.parametrize("transport", [STDIO, "http"])
    def test_neither_transport_starts_after_a_refusal(self, transport: str) -> None:
        def no_stdio(server: MCPServer) -> None:
            pytest.fail("stdio started")

        def no_http(app: Starlette, /, *, host: str, port: int, log_config: None) -> None:
            pytest.fail("uvicorn started")

        with pytest.raises(SystemExit, match="did not register"):
            main(
                settings=settings(transport=transport),
                register_kb=_refuse,
                run_stdio=no_stdio,
                run_http=no_http,
            )
