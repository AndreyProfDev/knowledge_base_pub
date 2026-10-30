"""The real process over stdio: the handshake a client does, and the exit without a key.

Each test spawns the installed ``knowledge-base-mcp`` console script with a
literal environment, so what is asserted is the entry point a client config
names, not an in-process stand-in.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

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

# The venv's scripts sit beside its interpreter; not resolved, as that would
# follow the interpreter symlink out of the venv.
_SCRIPT = str(Path(sys.executable).parent / "knowledge-base-mcp")

# bge-m3's testing overlay needs no key and loads its tokenizer lazily, so
# registration succeeds offline; Qdrant and the queue are in memory.
_KEYLESS = {"TOOLS_ENV": "testing", "KB_EMBEDDER": "bge-m3", "MCP_TRANSPORT": "stdio"}


async def _handshake() -> list[str]:
    params = StdioServerParameters(command=_SCRIPT, env=_KEYLESS)
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
    # The server name is how a client tells this endpoint from any other.
    return [initialized.server_info.name, *sorted(tool.name for tool in listed.tools)]


async def _bounded_handshake() -> list[str]:
    # A server that ignores MCP_TRANSPORT answers nothing on stdout; fail, not hang.
    return await asyncio.wait_for(_handshake(), timeout=30)


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # stdin at EOF: a server that registers ends its stdio session at once.
    return subprocess.run(
        [_SCRIPT],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_stdio_handshake_lists_every_knowledge_base_tool() -> None:
    assert asyncio.run(_bounded_handshake()) == ["knowledge_base", *EXPECTED_TOOLS]


def test_an_unset_embedder_key_exits_non_zero_naming_the_key() -> None:
    """The testing overlay leaves openai-small's key empty, so this is the unset case."""
    done = _run({"TOOLS_ENV": "testing", "MCP_TRANSPORT": "stdio"})

    assert done.returncode != 0
    assert "OPEN_AI_API_KEY" in done.stderr, done.stderr
    # stdout is the JSON-RPC channel on stdio: the startup log must never reach it.
    assert "did not register" not in done.stdout, done.stdout


@pytest.mark.parametrize(
    ("level", "shown"),
    # None: TOOLS_LOG_LEVEL unset, so the base default (INFO) decides.
    [(None, True), ("INFO", True), ("WARNING", False)],
)
def test_the_log_level_setting_decides_whether_the_serving_line_shows(
    level: str | None, *, shown: bool
) -> None:
    done = _run(_KEYLESS if level is None else {**_KEYLESS, "TOOLS_LOG_LEVEL": level})

    assert done.returncode == 0, done.stderr
    assert ("serving" in done.stderr) is shown, done.stderr


def test_with_mcp_transport_unset_the_base_transport_is_http() -> None:
    """compose sets no MCP_TRANSPORT and pytest's env pins it, so only a child can show this."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "from knowledge_base_config import Environment\n"
            "from knowledge_base_mcp_server.configs.settings import get_settings\n"
            "print(get_settings(Environment.LOCAL).transport)",
        ],
        env={"TOOLS_ENV": "local"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "http"
