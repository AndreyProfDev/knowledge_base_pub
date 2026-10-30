"""A stored item that fails its envelope or payload model: deletable, otherwise a server fault."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import lancedb
import pytest
from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb, stored
from fake_kind import FakeKind

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import ItemNotFound, StoredItemInvalid
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    reembed_memory,
    update_memory_item,
)
from tools_knowledge_base.store.protocol import Point

_KINDS = (FakeKind(), FakeKind("other"))


def _corrupt(tmp_path: Path, kind: str = "fake") -> tuple[KnowledgeBase, UUID]:
    """A LanceDB knowledge base holding one item whose stored payload is not an object."""
    kb = open_fake_kb(*_KINDS, settings=lancedb_settings(tmp_path))
    item_id = stored(kb, "sky", ["a"], kind=kind).item_id
    db = lancedb.connect(tmp_path)
    (table,) = db.list_tables().tables
    # update's `values` is an unparameterised dict in lancedb's annotations.
    _ = db.open_table(table).update(  # pyright: ignore[reportUnknownMemberType]
        values={"payload": "[]"}
    )
    return kb, item_id


def test_an_item_with_a_corrupt_envelope_can_be_deleted(tmp_path: Path) -> None:
    kb, item_id = _corrupt(tmp_path)
    with pytest.raises(StoredItemInvalid):
        get_memory_item(kb, "fake", item_id)

    delete_memory_item(kb, "fake", item_id)

    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "fake", item_id)


def test_a_corrupt_item_of_another_kind_is_not_deleted(tmp_path: Path) -> None:
    kb, item_id = _corrupt(tmp_path, kind="other")

    with pytest.raises(ItemNotFound):
        delete_memory_item(kb, "fake", item_id)
    with pytest.raises(StoredItemInvalid):
        get_memory_item(kb, "other", item_id)


def test_an_item_with_a_corrupt_envelope_is_not_updated(tmp_path: Path) -> None:
    kb, item_id = _corrupt(tmp_path)

    with pytest.raises(StoredItemInvalid):
        update_memory_item(kb, "fake", item_id, {"title": "sky", "tags": []})


def test_reembed_of_a_drifted_payload_is_stored_item_invalid(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    source = open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-a", 8, 16))
    drifted = uuid4()
    source.store.upsert(
        [Point(id=drifted, kind="fake", updated_at=datetime.now(UTC), payload={}, vector=[1.0] * 8)]
    )
    target = open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-b", 12, 4))

    with pytest.raises(StoredItemInvalid, match=str(drifted)):
        reembed_memory(target, "memory-fake-a")
