"""The configured 500-character cap counts the header and every step together."""

from __future__ import annotations

import asyncio

import pytest
from fake_kb import open_fake_kb
from fake_server import serve
from mcp.server.mcpserver.exceptions import ToolError

from tools_knowledge_base.operations import store_memory
from tools_knowledge_base_workflow.kind import WorkflowKind

_HINT = (
    "Name, description and steps count together: shorten them, "
    "or split it into several smaller workflows."
)


def _workflow(step_length: int) -> dict[str, object]:
    # Embed text "w\n" + step.
    return {"name": "w", "steps": ["s" * step_length]}


def test_a_workflow_of_exactly_the_cap_is_stored() -> None:
    kb = open_fake_kb(WorkflowKind())

    assert store_memory(kb, "workflow", _workflow(498)).item_id


def test_an_over_cap_store_workflow_call_is_an_error_naming_count_cap_and_hint() -> None:
    kb = open_fake_kb(WorkflowKind())

    with pytest.raises(ToolError) as caught:
        asyncio.run(serve(kb).call_tool("store_workflow", _workflow(499)))

    message = str(caught.value)
    assert (
        "workflow item is 501 characters; the workflow limit is 500 "
        "(counted over name: description (or name), then one step per line)." in message
    )
    assert _HINT in message
    assert kb.huey.pending_count() == 0
