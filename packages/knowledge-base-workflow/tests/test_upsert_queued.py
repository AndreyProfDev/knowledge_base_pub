"""Two writes of one name queued before the worker runs leave one item; case is identity."""

from __future__ import annotations

from fake_kb import open_fake_kb

from tools_knowledge_base.operations import list_memory_items, store_memory
from tools_knowledge_base.queue import drain
from tools_knowledge_base_workflow.kind import WorkflowKind, WorkflowPayload


def test_two_queued_writes_of_one_name_leave_one_item_the_last_requested() -> None:
    kb = open_fake_kb(WorkflowKind())
    first = store_memory(kb, "workflow", {"name": "deploy", "steps": ["a"]})
    second = store_memory(kb, "workflow", {"name": "deploy", "steps": ["b", "c"]})

    drain(kb.huey)

    assert first.item_id == second.item_id
    assert [item.payload for item in list_memory_items(kb, "workflow").items] == [
        WorkflowPayload(name="deploy", steps=["b", "c"])
    ]


def test_names_differing_only_in_case_are_different_workflows() -> None:
    kind = WorkflowKind()

    assert kind.key(WorkflowPayload(name="Deploy", steps=["s"])) != kind.key(
        WorkflowPayload(name="deploy", steps=["s"])
    )
