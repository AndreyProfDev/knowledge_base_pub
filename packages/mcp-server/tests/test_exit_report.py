"""On stdin EOF the server finishes the queued writes for a bounded time, then says what is left."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from fake_server import keyed_settings
from mcp.server import MCPServer

from knowledge_base_config import Environment
from knowledge_base_mcp_server.app import STDIO, main
from knowledge_base_mcp_server.configs.settings import get_settings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations import store_memory
from tools_knowledge_base.registration import Registered, register


def _run(
    kb: KnowledgeBase, stdin_closes: Callable[[MCPServer], None], drain_seconds: float = 5.0
) -> None:
    def register_on_fakes(server: MCPServer) -> Registered:
        return register(server, settings=keyed_settings(), open_kb=lambda _settings: kb)

    settings = get_settings(Environment.TESTING).model_copy(update={"transport": STDIO})
    main(
        settings=settings,
        register_kb=register_on_fakes,
        run_stdio=stdin_closes,
        drain_seconds=drain_seconds,
        require_key=lambda: None,
    )


def test_a_write_queued_when_stdin_closes_is_run_before_exit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kb = open_fake_kb(FakeKind("alpha"))
    request_ids: list[str] = []

    def stdin_closes(server: MCPServer) -> None:
        request_ids.append(store_memory(kb, "alpha", {"title": "kept", "tags": []}).request_id)

    with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
        _run(kb, stdin_closes)

    assert kb.writes.status(request_ids[0]) == ("done", None)
    assert caplog.records[-1].getMessage() == "0 write(s) still queued at exit"
    assert caplog.records[-1].levelno == logging.INFO


def test_a_write_still_running_past_the_bound_is_logged_as_lost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kb = open_fake_kb(FakeKind("alpha"))
    release = threading.Event()

    def stdin_closes(server: MCPServer) -> None:
        kb.writes.submit(release.wait)

    try:
        with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
            _run(kb, stdin_closes, drain_seconds=0.05)
    finally:
        release.set()

    assert caplog.records[-1].getMessage() == "1 write(s) still queued at exit"
    assert caplog.records[-1].levelno == logging.WARNING


def test_no_queued_writes_at_stdin_close_is_logged_as_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    kb = open_fake_kb(FakeKind("alpha"))

    def stdin_closes(server: MCPServer) -> None:
        return None

    with caplog.at_level(logging.INFO, logger="knowledge_base_mcp_server"):
        _run(kb, stdin_closes)

    assert caplog.records[-1].getMessage() == "0 write(s) still queued at exit"
    assert caplog.records[-1].levelno == logging.INFO


def test_stdin_close_drains_for_the_configured_seconds() -> None:
    seen: list[float] = []

    def drain(seconds: float) -> int:
        seen.append(seconds)
        return 0

    settings = get_settings(Environment.TESTING).model_copy(update={"transport": STDIO})
    main(
        settings=settings,
        register_kb=lambda _server: Registered(tools=[], queued=lambda: 0, drain=drain),
        run_stdio=lambda _server: None,
        drain_seconds=0.25,
        require_key=lambda: None,
    )

    assert seen == [0.25]
