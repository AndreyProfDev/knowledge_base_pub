"""Each ``LanceStore`` filter scopes to what it names, and the table schema it creates."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import lancedb
import pyarrow as pa
from store_adapters import COLLECTION, EMBEDDER, T0, point

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.store.protocol import VectorStore


def test_get_returns_only_the_asked_ids(store: VectorStore) -> None:
    asked, other = point("asked"), point("other")
    store.upsert([asked, other])

    assert [item.id for item in store.get([asked.id])] == [asked.id]


def test_a_page_after_the_cursor_stays_in_its_kind(store: VectorStore) -> None:
    store.upsert(
        [
            point("first", point_id=UUID(int=1)),
            point("second", point_id=UUID(int=3)),
            point("elsewhere", kind="other", point_id=UUID(int=4)),
        ]
    )

    items, cursor = store.list("fake", limit=1, cursor=UUID(int=3))

    assert ([item.id for item in items], cursor) == ([UUID(int=3)], None)


def test_a_page_holding_exactly_the_last_points_has_no_next_cursor(store: VectorStore) -> None:
    only = point("only")
    store.upsert([only])

    items, cursor = store.list("fake", limit=1, cursor=None)

    assert ([item.id for item in items], cursor) == ([only.id], None)


def test_delete_older_than_spares_old_points_not_asked_for(store: VectorStore) -> None:
    asked, other = point("asked"), point("other")
    store.upsert([asked, other])

    store.delete([asked.id], older_than=T0 + timedelta(days=1))

    assert [item.id for item in store.get([asked.id, other.id])] == [other.id]


def test_a_new_table_declares_every_column_non_null(
    settings: KnowledgeBaseSettings, store: VectorStore
) -> None:
    config = settings.vector_store.lancedb
    assert config is not None

    schema = lancedb.connect(config.path).open_table(COLLECTION).schema

    assert schema == pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("updated_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("payload", pa.string(), nullable=False),
            pa.field("vector", pa.list_(pa.float32(), EMBEDDER.dimensions), nullable=False),
        ]
    )
    assert store.dimensions == EMBEDDER.dimensions
