"""``name`` is the workflow's identity: the same name overwrites in place, a rename moves."""

from __future__ import annotations

import pytest
from fake_kb import open_fake_kb

from tools_knowledge_base.errors import ItemNotFound
from tools_knowledge_base.operations import (
    get_memory_item,
    list_memory_items,
    store_memory,
    update_memory_item,
)
from tools_knowledge_base.queue import drain
from tools_knowledge_base_workflow.kind import WorkflowKind, WorkflowPayload


def test_the_same_name_overwrites_description_and_steps_in_place() -> None:
    kb = open_fake_kb(WorkflowKind())
    first = store_memory(kb, "workflow", {"name": "deploy", "description": "old", "steps": ["a"]})
    assert drain(kb.huey) == (1, 0)

    again = store_memory(kb, "workflow", {"name": "deploy", "steps": ["b", "c"]})
    assert drain(kb.huey) == (1, 0)

    assert again.item_id == first.item_id
    assert [item.payload for item in list_memory_items(kb, "workflow").items] == [
        WorkflowPayload(name="deploy", steps=["b", "c"])
    ]


def test_an_update_that_renames_the_workflow_moves_the_item() -> None:
    kb = open_fake_kb(WorkflowKind())
    first = store_memory(kb, "workflow", {"name": "deploy", "steps": ["a"]})
    assert drain(kb.huey) == (1, 0)

    moved = update_memory_item(kb, "workflow", first.item_id, {"name": "ship", "steps": ["a"]})
    assert drain(kb.huey) == (1, 0)

    assert moved.item_id != first.item_id
    assert get_memory_item(kb, "workflow", moved.item_id).payload == WorkflowPayload(
        name="ship", steps=["a"]
    )
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "workflow", first.item_id)
