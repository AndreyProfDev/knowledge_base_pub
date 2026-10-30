"""Steps come back in the order they were stored, not sorted, through get and search."""

from __future__ import annotations

from fake_kb import open_fake_kb

from tools_knowledge_base.operations import get_memory_item, search_memory, store_memory
from tools_knowledge_base.queue import drain
from tools_knowledge_base_workflow.kind import WorkflowKind


def test_unsorted_steps_round_trip_in_order() -> None:
    kb = open_fake_kb(WorkflowKind())
    accepted = store_memory(kb, "workflow", {"name": "routine", "steps": ["c", "a", "b"]})
    assert drain(kb.huey) == (1, 0)

    item = get_memory_item(kb, "workflow", accepted.item_id)
    [hit] = search_memory(kb, "routine", kind="workflow")

    assert item.payload.model_dump()["steps"] == ["c", "a", "b"]
    assert hit.payload.model_dump()["steps"] == ["c", "a", "b"]
