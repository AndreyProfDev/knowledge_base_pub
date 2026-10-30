"""``warmup_memory`` and ``get_warmup_progress`` called through an in-process MCP server."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from fake_server import call, keyed_settings, serve
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from warmup_harness import FailingHuey, fake_items, warmup_settings, write_yaml

from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.operations import get_warmup_progress
from tools_knowledge_base.queue import drain
from tools_knowledge_base.registration import register


def test_a_run_through_the_tools_reports_then_finishes(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    server = serve(kb)

    report = call(server, "warmup_memory")
    assert report["kinds"] == {"fake": {"queued": 2, "unchanged": 0}}
    assert report["total_queued"] == 2

    progress = call(server, "get_warmup_progress", run_id=report["run_id"])
    assert (progress["total"], progress["pending"], progress["finished"]) == (2, 2, False)
    drain(kb.huey)
    progress = call(server, "get_warmup_progress", run_id=report["run_id"])
    assert (progress["done"], progress["pending"], progress["finished"]) == (2, 0, True)


def test_an_unknown_run_is_an_error_result_naming_it() -> None:
    with pytest.raises(ToolError, match="no warm-up run 'nope'"):
        asyncio.run(serve(open_fake_kb()).call_tool("get_warmup_progress", {"run_id": "nope"}))


def test_an_enqueue_failing_partway_is_an_error_result_naming_the_run(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(huey=FailingHuey(1), settings=warmup_settings(tmp_path))

    with pytest.raises(ToolError) as raised:
        asyncio.run(serve(kb).call_tool("warmup_memory", {}))

    match = re.search(r"warm-up run (\S+) stopped after queueing 1 requests", str(raised.value))
    assert match is not None, str(raised.value)
    assert get_warmup_progress(kb, match.group(1)).total == 1


def test_the_progress_tool_states_the_retry_note_and_takes_a_run_id() -> None:
    listed = {tool.name: tool for tool in asyncio.run(serve(open_fake_kb()).list_tools())}

    progress = listed["get_warmup_progress"]
    assert "about 150 s" in (progress.description or "")
    assert set(progress.input_schema["properties"]) == {"run_id"}


def test_a_kind_named_warmup_progress_does_not_shadow_the_tool() -> None:
    kb = open_fake_kb(FakeKind("warmup_progress"))
    with pytest.raises(KnowledgeBaseError, match="repeated: 'get_warmup_progress'"):
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)
