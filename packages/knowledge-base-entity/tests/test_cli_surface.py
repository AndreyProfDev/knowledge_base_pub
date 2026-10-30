"""The generated ``store-entity`` / ``update-entity`` and ``search --kind entity``."""

from __future__ import annotations

import pytest
from cli_harness import invoke, item_id_in
from fake_kb import open_fake_kb

from tools_knowledge_base.errors import ItemNotFound
from tools_knowledge_base.operations import get_memory_item
from tools_knowledge_base.queue import drain
from tools_knowledge_base_entity.kind import EntityKind, EntityPayload


def test_store_entity_binds_the_type_and_search_accepts_the_kind() -> None:
    kb = open_fake_kb(EntityKind())

    code, out = invoke(
        kb, "store-entity", "--name", "Alice", "--type", "person", "--description", "the user"
    )
    assert code == 0, out
    assert drain(kb.huey) == (1, 0)
    assert get_memory_item(kb, "entity", item_id_in(out)).payload == EntityPayload(
        name="Alice", type="person", description="the user"
    )

    code, out = invoke(kb, "search", "Alice", "--kind", "entity")
    assert code == 0, out
    assert "Alice (person): the user" in out


def test_store_entity_refuses_a_type_outside_the_set_and_queues_nothing() -> None:
    kb = open_fake_kb(EntityKind())

    code, out = invoke(
        kb, "store-entity", "--name", "Earth", "--type", "planet", "--description", "home"
    )
    assert code != 0, out
    assert "planet" in out
    assert kb.huey.pending_count() == 0


def test_the_help_explains_the_fields_and_lists_the_types() -> None:
    code, out = invoke(open_fake_kb(EntityKind()), "store-entity", "--help")
    assert code == 0, out
    flat = " ".join(out.split())
    assert (
        "One non-blank line; surrounding whitespace is stripped, not part of the identity." in flat
    )
    assert "What the entity is." in flat
    assert "Non-blank." in flat
    assert "person|system|project|concept|organization|tool" in flat


def test_update_entity_with_a_new_type_moves_the_item() -> None:
    kb = open_fake_kb(EntityKind())
    _, out = invoke(kb, "store-entity", "--name", "huey", "--type", "system", "--description", "q")
    assert drain(kb.huey) == (1, 0)
    item_id = item_id_in(out)

    code, out = invoke(
        kb, "update-entity", str(item_id), "--name", "huey", "--type", "tool", "--description", "q"
    )
    assert code == 0, out
    new_id = item_id_in(out)
    assert new_id != item_id
    assert drain(kb.huey) == (1, 0)

    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "entity", item_id)
    assert get_memory_item(kb, "entity", new_id).payload == EntityPayload(
        name="huey", type="tool", description="q"
    )
