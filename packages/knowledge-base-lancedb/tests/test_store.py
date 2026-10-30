"""What only the LanceDB adapter refuses; the shared behaviour is core's conformance suite."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import lancedb
import pyarrow as pa
import pytest
from fake_kb import lancedb_settings

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import LanceDBSettings, get_settings
from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_lancedb.store import LanceStore


def test_a_table_with_a_variable_length_vector_is_refused(tmp_path: Path) -> None:
    db = lancedb.connect(tmp_path)
    schema = pa.schema([pa.field("id", pa.string()), pa.field("vector", pa.list_(pa.float32()))])
    _ = db.create_table("memory-loose", schema=schema)  # pyright: ignore[reportUnknownMemberType]

    with pytest.raises(KnowledgeBaseError, match="no fixed-size vector column"):
        _ = LanceStore(lancedb_settings(tmp_path), "memory-loose", dimensions=None)


def test_upserts_past_max_small_fragments_are_compacted(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    vector_store = settings.vector_store.model_copy(
        update={"lancedb": LanceDBSettings(path=tmp_path, max_small_fragments=2)}
    )
    store = LanceStore(
        settings.model_copy(update={"vector_store": vector_store}), "memory-fake-8", dimensions=8
    )
    at = datetime(2026, 1, 1, tzinfo=UTC)
    db = lancedb.connect(tmp_path)
    small_fragments: list[int] = []

    for written in range(1, 7):
        store.upsert([Point(id=uuid4(), kind="fake", updated_at=at, payload={}, vector=[1.0] * 8)])
        stats = cast("dict[str, Any]", cast("object", db.open_table("memory-fake-8").stats()))
        assert stats["num_rows"] == written
        small_fragments.append(stats["fragment_stats"]["num_small_fragments"])

    # Exactly max_small_fragments is left alone; one more is compacted into one.
    assert small_fragments == [1, 2, 1, 2, 1, 2]


def test_a_vector_of_the_wrong_length_is_refused_before_it_is_written(tmp_path: Path) -> None:
    store = LanceStore(lancedb_settings(tmp_path), "memory-fake-8", dimensions=8)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    short = Point(id=uuid4(), kind="fake", updated_at=at, payload={}, vector=[1.0] * 4)

    with pytest.raises(ValueError, match="expected 8 but got array of size 4"):
        store.upsert([short])
    assert store.count_kinds() == {}


@pytest.mark.parametrize("read", ["get", "list", "search"])
@pytest.mark.parametrize(("stored", "match"), [("[]", "not a valid Item"), ("{", "not JSON")])
def test_a_row_with_a_corrupt_envelope_is_stored_item_invalid(
    tmp_path: Path, read: str, stored: str, match: str
) -> None:
    store = LanceStore(lancedb_settings(tmp_path), "memory-fake-8", dimensions=8)
    point_id = uuid4()
    at = datetime(2026, 1, 1, tzinfo=UTC)
    store.upsert([Point(id=point_id, kind="fake", updated_at=at, payload={}, vector=[1.0] * 8)])
    table = lancedb.connect(tmp_path).open_table("memory-fake-8")
    _ = table.update(values={"payload": stored})  # pyright: ignore[reportUnknownMemberType]
    reads = {
        "get": lambda: store.get([point_id]),
        "list": lambda: store.list("fake", limit=10, cursor=None),
        "search": lambda: store.search([1.0] * 8, kinds=None, limit=10, min_score=None),
    }

    with pytest.raises(StoredItemInvalid, match=f"row {point_id} in 'memory-fake-8'.*{match}"):
        _ = reads[read]()


def test_a_next_page_row_whose_id_is_not_a_uuid_is_stored_item_invalid(tmp_path: Path) -> None:
    store = LanceStore(lancedb_settings(tmp_path), "memory-fake-8", dimensions=8)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    corrupt = uuid4()
    store.upsert(
        [
            Point(id=point_id, kind="fake", updated_at=at, payload={}, vector=[1.0] * 8)
            for point_id in (uuid4(), corrupt)
        ]
    )
    table = lancedb.connect(tmp_path).open_table("memory-fake-8")
    # "~" sorts after every hex digit, so the corrupt row is the second page's first.
    _ = table.update(  # pyright: ignore[reportUnknownMemberType]
        where=f"id = '{corrupt}'", values={"id": "~not-a-uuid"}
    )

    with pytest.raises(StoredItemInvalid, match=r"row ~not-a-uuid in 'memory-fake-8' .*not a UUID"):
        _ = store.list("fake", limit=1, cursor=None)


def test_settings_without_a_lancedb_block_are_refused() -> None:
    # The testing overlay selects qdrant, so its lancedb block is unset.
    with pytest.raises(KnowledgeBaseError, match=r"^vector_store\.lancedb is unset$"):
        _ = LanceStore(get_settings(Environment.TESTING), "memory-fake-8", dimensions=8)
