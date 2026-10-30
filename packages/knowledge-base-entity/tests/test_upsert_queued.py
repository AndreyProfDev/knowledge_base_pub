"""Two writes of one ``(name, type)`` queued before the worker runs leave one item."""

from __future__ import annotations

from fake_kb import open_fake_kb

from tools_knowledge_base.operations import list_memory_items, store_memory
from tools_knowledge_base.queue import drain
from tools_knowledge_base_entity.kind import EntityKind, EntityPayload


def test_two_queued_writes_of_one_key_leave_one_item_the_last_requested() -> None:
    kb = open_fake_kb(EntityKind())
    first = store_memory(kb, "entity", {"name": "Alice", "type": "person", "description": "a"})
    second = store_memory(kb, "entity", {"name": "Alice", "type": "person", "description": "b"})

    drain(kb.huey)

    assert first.item_id == second.item_id
    page = list_memory_items(kb, "entity")
    assert [item.payload for item in page.items] == [
        EntityPayload(name="Alice", type="person", description="b")
    ]
