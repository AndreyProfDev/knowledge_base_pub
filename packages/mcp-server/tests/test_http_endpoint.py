"""The HTTP endpoint serves every knowledge-base tool, over a real ASGI round trip."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from fake_embedder import FakeEmbedder
from fake_server import keyed_settings
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from omegaconf import DictConfig, OmegaConf
from starlette.applications import Starlette

from knowledge_base_config import Environment
from knowledge_base_mcp_server.app import build_app
from knowledge_base_mcp_server.configs.settings import McpServerSettings, get_settings
from tools_knowledge_base.context import open_knowledge_base
from tools_knowledge_base.registration import SUMMARY, register

EXPECTED_TOOLS = sorted(
    [
        "get_memory_request",
        "get_warmup_progress",
        "search_memory",
        "warmup_memory",
        *(
            f"{verb}_{kind}"
            for kind in ("entity", "knowledge", "workflow")
            for verb in ("store", "update", "get", "list", "delete")
        ),
    ]
)


def _register_on_fakes(server: MCPServer) -> list[Callable[..., Any]]:
    """The real ``register``, keyed and on a fake embedder: no network, no key."""
    return register(
        server,
        settings=keyed_settings(),
        open_kb=lambda settings: open_knowledge_base(settings, embedder=FakeEmbedder()),
    )


async def _initialize_and_list(app: Starlette, path: str) -> tuple[str, list[str]]:
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
        streamable_http_client("http://testserver" + path, http_client=client) as (read, write),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
        return initialized.instructions or "", sorted(tool.name for tool in listed.tools)


def test_the_endpoint_lists_every_knowledge_base_tool() -> None:
    settings = get_settings(Environment.TESTING)
    app, tool_names = build_app(settings, register_kb=_register_on_fakes)

    init_text, listed = asyncio.run(_initialize_and_list(app, settings.path))

    assert tool_names == EXPECTED_TOOLS
    assert listed == EXPECTED_TOOLS
    assert SUMMARY.split(":")[0] in init_text, "initialize must carry the summary"


def test_the_base_settings_serve_mcp_on_9799() -> None:
    """The deployed port and path come from the base YAML; the testing overlay hides them."""
    settings = get_settings(Environment.LOCAL)

    # The transport is not asserted here: pytest's env pins MCP_TRANSPORT, so the
    # base default is checked in a child process (test_stdio_process.py).
    assert (settings.port, settings.path) == (9799, "/mcp")


def test_the_container_binds_every_interface() -> None:
    """compose runs ``TOOLS_ENV=prod``: base plus any prod overlay, read straight from YAML.

    The local and testing overlays both override ``host``, so only the files
    themselves show what the container binds. On loopback, the published port
    would be dead while the in-container healthcheck stayed green.
    """
    configs = McpServerSettings.yaml_directory
    layers = [configs / "base" / "mcp_server.yaml", *sorted((configs / "prod").glob("*.yaml"))]
    merged = OmegaConf.merge(*(OmegaConf.load(layer) for layer in layers))

    assert isinstance(merged, DictConfig)
    assert merged["host"] == "0.0.0.0"


def test_a_server_run_on_the_host_binds_loopback_only() -> None:
    """The base's 0.0.0.0 is for the container; on the host it would reach the LAN."""
    assert get_settings(Environment.LOCAL).host == "127.0.0.1"


_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


async def _initialize_status(
    app: Starlette, path: str, host: str, *, origin: str | None = None
) -> int:
    headers = {"Host": host, "Accept": "application/json, text/event-stream"}
    if origin is not None:
        headers["Origin"] = origin
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(path, json=_INITIALIZE, headers=headers)
        return response.status_code


@pytest.mark.parametrize(
    ("host", "status"),
    [
        ("localhost:9799", 200),
        # compose publishes on ${KB_MCP_PORT:-9799}; a moved host port must still answer.
        ("127.0.0.1:19799", 200),
        ("evil.example:9799", 421),
    ],
)
def test_the_base_host_guard_admits_any_loopback_port_only(host: str, status: int) -> None:
    settings = get_settings(Environment.LOCAL)
    app, _ = build_app(settings, register_kb=_register_on_fakes)

    assert asyncio.run(_initialize_status(app, settings.path, host)) == status


def test_the_host_guard_reads_the_settings() -> None:
    """``allowed_hosts`` is wired through, not a constant that happens to list testserver."""
    settings = get_settings(Environment.TESTING).model_copy(update={"allowed_hosts": ("only",)})
    app, _ = build_app(settings, register_kb=_register_on_fakes)

    assert asyncio.run(_initialize_status(app, settings.path, "testserver")) == 421


def test_a_cross_origin_browser_request_is_refused() -> None:
    """The base ``allowed_origins`` admit no real Origin: a web page cannot drive the tools."""
    settings = get_settings(Environment.LOCAL)
    app, _ = build_app(settings, register_kb=_register_on_fakes)

    status = asyncio.run(
        _initialize_status(app, settings.path, "localhost:9799", origin="http://evil.example")
    )

    assert status == 403


def test_the_origin_guard_reads_the_settings() -> None:
    """``allowed_origins`` is wired through: listing an origin admits it."""
    settings = get_settings(Environment.LOCAL).model_copy(
        update={"allowed_origins": ("http://evil.example",)}
    )
    app, _ = build_app(settings, register_kb=_register_on_fakes)

    status = asyncio.run(
        _initialize_status(app, settings.path, "localhost:9799", origin="http://evil.example")
    )

    assert status == 200


@pytest.mark.parametrize(("path", "status"), [("/elsewhere", 200), ("/mcp", 404)])
def test_the_endpoint_is_served_on_the_configured_path_only(path: str, status: int) -> None:
    settings = get_settings(Environment.TESTING).model_copy(update={"path": "/elsewhere"})
    app, _ = build_app(settings, register_kb=_register_on_fakes)

    assert asyncio.run(_initialize_status(app, path, "testserver")) == status
