"""In-process twins of what ``test_stdio_process.py`` shows through the spawned script.

The subprocess runs the installed source, so a change to it here would go unnoticed
there; these drive the same code paths in this process.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

import pytest
from fake_server import register_nothing
from mcp.server import MCPServer
from starlette.applications import Starlette

from knowledge_base_config import Environment
from knowledge_base_mcp_server.app import configure_logging, main
from knowledge_base_mcp_server.configs.settings import get_settings


@contextmanager
def _bare_root() -> Generator[logging.Logger]:
    """The root logger as a fresh process has it: ``basicConfig`` acts only on no handlers.

    Entered in the test body: pytest adds its capture handlers for the call phase.
    """
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def test_logging_goes_to_stderr_formatted_at_the_settings_level(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = get_settings(Environment.TESTING).model_copy(update={"log_level": "debug"})

    with _bare_root() as root:
        configure_logging(settings)
        level = root.level
        logging.getLogger("knowledge_base_mcp_server").debug("hi")

    # Not the root's WARNING default: the lower-case setting was applied.
    assert level == logging.DEBUG
    assert capsys.readouterr() == ("", "DEBUG knowledge_base_mcp_server: hi\n")


def test_main_reads_the_tools_env_settings_by_default() -> None:
    """pytest's env pins ``TOOLS_ENV=testing`` and ``MCP_TRANSPORT=http``."""
    served: list[tuple[str, int]] = []

    def serve(app: Starlette, /, *, host: str, port: int, log_config: None) -> None:
        served.append((host, port))

    def stdio(server: MCPServer) -> None:
        pytest.fail(f"served {server.name} over stdio: MCP_TRANSPORT is not pinned to http")

    main(register_kb=register_nothing, run_stdio=stdio, run_http=serve)

    testing = get_settings(Environment.TESTING)
    assert served == [(testing.host, testing.port)]


def test_get_settings_defaults_to_the_tools_env_environment() -> None:
    assert get_settings() == get_settings(Environment.TESTING)
