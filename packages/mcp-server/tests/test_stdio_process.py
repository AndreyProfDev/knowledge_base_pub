"""The real process over stdio: the handshake, the first keyless call, the modules imported.

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

EXPECTED_TOOLS = {
    "get_memory_request",
    "search_memory",
    *(
        f"{verb}_{kind}"
        for kind in ("entity", "knowledge", "workflow")
        for verb in ("store", "update", "get", "list", "delete")
    ),
}

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
    name, *tools = asyncio.run(_bounded_handshake())

    assert name == "knowledge_base"
    assert len(tools) == 17
    assert set(tools) == EXPECTED_TOOLS


def test_an_unset_embedder_key_fails_the_start(tmp_path: Path) -> None:
    """The testing overlay blanks the default openai-large key: the start names it and the .env."""
    env = {"TOOLS_ENV": "testing", "MCP_TRANSPORT": "stdio", "KB_DATA_DIR": str(tmp_path)}

    done = _run(env)

    assert done.returncode != 0
    assert "OPEN_AI_API_KEY" in done.stderr
    assert f"{tmp_path}/.env" in done.stderr
    assert done.stdout == ""


_HEAVY = ("openai", "tiktoken", "tokenizers", "numpy", "qdrant_client", "lancedb")


def _modules_after(tmp_path: Path, *, list_knowledge: bool) -> set[str]:
    """Run one stdio session; the modules the server logged as it ended."""
    log = tmp_path / "stderr.log"
    env = {**_KEYLESS, "KB_DATA_DIR": str(tmp_path), "KB_DEBUG_MODULES": "true"}

    async def session() -> None:
        with log.open("w") as errlog:
            params = StdioServerParameters(command=_SCRIPT, env=env)
            async with (
                stdio_client(params, errlog=errlog) as (read, write),
                ClientSession(read, write) as client,
            ):
                await client.initialize()
                await client.list_tools()
                if list_knowledge:
                    listed = await client.call_tool("list_knowledge", {})
                    assert not listed.is_error, listed

    asyncio.run(asyncio.wait_for(session(), timeout=30))
    [line] = [x for x in log.read_text().splitlines() if "modules: " in x]
    return set(line.split("modules: ", 1)[1].split(","))


def test_nothing_heavy_is_imported_after_tools_list(tmp_path: Path) -> None:
    modules = _modules_after(tmp_path, list_knowledge=False)

    assert "mcp" in modules
    assert not {m for m in modules if m.split(".")[0] in _HEAVY}


def test_a_list_call_still_imports_no_embedder_client(tmp_path: Path) -> None:
    modules = _modules_after(tmp_path, list_knowledge=True)

    assert "openai" not in modules


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


def test_with_mcp_transport_unset_the_base_transport_is_stdio() -> None:
    """no deployment sets MCP_TRANSPORT and pytest's env pins it, so only a child can show this."""
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
    assert done.stdout.strip() == "stdio"
