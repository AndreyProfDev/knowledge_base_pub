"""Edit: an update is a write to the new key that retires the old point if the key moved."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind, FakePayload
from pydantic import ValidationError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import ItemNotFound, UnknownKind
from tools_knowledge_base.operations import (
    get_memory_item,
    list_memory_items,
    store_memory,
    update_memory_item,
)
from tools_knowledge_base.queue import drain


def _titles(kb: KnowledgeBase) -> list[str]:
    return sorted(
        item.payload.model_dump()["title"] for item in list_memory_items(kb, "fake").items
    )


def test_an_edit_keeping_the_key_updates_the_item_in_place() -> None:
    kb = open_fake_kb()
    old = stored(kb, "huey")

    edit = update_memory_item(kb, "fake", old.item_id, {"title": "huey", "tags": ["edited"]})
    drain(kb.huey)

    assert edit.item_id == old.item_id
    assert edit.status == "queued"
    assert get_memory_item(kb, "fake", old.item_id).payload == FakePayload(
        title="huey", tags=["edited"]
    )
    assert _titles(kb) == ["huey"]


def test_an_edit_changing_the_key_stores_the_new_id_and_retires_the_old() -> None:
    kb = open_fake_kb()
    old = stored(kb, "huey")

    edit = update_memory_item(kb, "fake", old.item_id, {"title": "renamed", "tags": []})
    assert get_memory_item(kb, "fake", old.item_id)  # the old point stays until the worker runs
    drain(kb.huey)

    assert edit.item_id != old.item_id
    assert get_memory_item(kb, "fake", edit.item_id).payload.model_dump()["title"] == "renamed"
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "fake", old.item_id)


def test_a_write_of_the_old_key_requested_after_the_edit_outlives_it() -> None:
    kb = open_fake_kb()
    old = stored(kb, "huey")
    update_memory_item(kb, "fake", old.item_id, {"title": "renamed", "tags": []})
    store_memory(kb, "fake", {"title": "huey", "tags": ["again"]})
    edit_task = kb.huey.dequeue()  # pyright: ignore[reportUnknownVariableType]
    restore_task = kb.huey.dequeue()  # pyright: ignore[reportUnknownVariableType]

    # The later re-store finishes first; the edit's delete must spare it.
    kb.huey.execute(restore_task)  # pyright: ignore[reportUnknownMemberType]
    kb.huey.execute(edit_task)  # pyright: ignore[reportUnknownMemberType]

    assert _titles(kb) == ["huey", "renamed"]
    assert get_memory_item(kb, "fake", old.item_id).payload == FakePayload(
        title="huey", tags=["again"]
    )


def test_an_edit_validates_its_payload_before_enqueue() -> None:
    kb = open_fake_kb()
    old = stored(kb, "huey")

    with pytest.raises(ValidationError):
        update_memory_item(kb, "fake", old.item_id, {"title": "huey"})
    with pytest.raises(ValidationError, match="embed text is empty"):
        update_memory_item(kb, "fake", old.item_id, {"title": "", "tags": []})

    assert kb.huey.pending_count() == 0


def test_an_edit_of_an_absent_or_other_kinds_id_is_not_found() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("other"))
    other = stored(kb, "huey", kind="other")
    payload: dict[str, object] = {"title": "huey", "tags": []}

    with pytest.raises(ItemNotFound):
        update_memory_item(kb, "fake", uuid4(), payload)
    with pytest.raises(ItemNotFound, match=f"no fake item has id {other.item_id}"):
        update_memory_item(kb, "fake", other.item_id, payload)
    with pytest.raises(UnknownKind):
        update_memory_item(kb, "nope", other.item_id, payload)

    assert kb.huey.pending_count() == 0
