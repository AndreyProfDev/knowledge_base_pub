"""The ``(name, type)`` pair is the entity's identity: equal pairs upsert, others do not."""

from __future__ import annotations

import pytest
from fake_kb import open_fake_kb

from tools_knowledge_base.errors import ItemNotFound
from tools_knowledge_base.operations import get_memory_item, store_memory, update_memory_item
from tools_knowledge_base.queue import drain
from tools_knowledge_base_entity.kind import EntityKind, EntityPayload


def test_the_same_name_and_type_overwrites_the_description_in_place() -> None:
    kb = open_fake_kb(EntityKind())
    first = store_memory(kb, "entity", {"name": "huey", "type": "system", "description": "old"})
    assert drain(kb.huey) == (1, 0)

    again = store_memory(kb, "entity", {"name": "huey", "type": "system", "description": "new"})
    assert drain(kb.huey) == (1, 0)

    assert again.item_id == first.item_id
    assert get_memory_item(kb, "entity", first.item_id).payload == EntityPayload(
        name="huey", type="system", description="new"
    )


def test_the_same_name_under_another_type_is_a_separate_item() -> None:
    kb = open_fake_kb(EntityKind())
    system = store_memory(kb, "entity", {"name": "huey", "type": "system", "description": "s"})
    tool = store_memory(kb, "entity", {"name": "huey", "type": "tool", "description": "t"})
    assert drain(kb.huey) == (2, 0)

    assert system.item_id != tool.item_id
    assert get_memory_item(kb, "entity", system.item_id).payload.model_dump()["description"] == "s"
    assert get_memory_item(kb, "entity", tool.item_id).payload.model_dump()["description"] == "t"


def test_an_update_that_changes_the_type_moves_the_item() -> None:
    kb = open_fake_kb(EntityKind())
    first = store_memory(kb, "entity", {"name": "huey", "type": "system", "description": "q"})
    assert drain(kb.huey) == (1, 0)

    moved = update_memory_item(
        kb, "entity", first.item_id, {"name": "huey", "type": "tool", "description": "q"}
    )
    assert drain(kb.huey) == (1, 0)

    assert moved.item_id != first.item_id
    assert get_memory_item(kb, "entity", moved.item_id).payload == EntityPayload(
        name="huey", type="tool", description="q"
    )
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "entity", first.item_id)
