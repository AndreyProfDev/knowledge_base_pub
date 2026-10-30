"""Two ``LanceStore`` instances on one directory, as the worker and the CLI are."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings

from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_lancedb.store import LanceStore

COLLECTION = "memory-fake-8"
EMBEDDER = FakeEmbedder()


def _point(text: str) -> Point:
    return Point(
        id=uuid4(),
        kind="fake",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"title": text, "tags": []},
        vector=EMBEDDER.embed_documents([text])[0],
    )


def test_each_instance_sees_the_others_writes_and_deletes(tmp_path: Path) -> None:
    worker = LanceStore(lancedb_settings(tmp_path), COLLECTION, dimensions=EMBEDDER.dimensions)
    reader = LanceStore(lancedb_settings(tmp_path), COLLECTION, dimensions=None)
    point = _point("shared")
    assert reader.get([point.id]) == []

    worker.upsert([point])
    assert [item.id for item in reader.get([point.id])] == [point.id]

    reader.delete([point.id])
    assert worker.get([point.id]) == []


def test_reopening_a_table_reads_its_dimensions(tmp_path: Path) -> None:
    _ = LanceStore(lancedb_settings(tmp_path), COLLECTION, dimensions=8)

    reopened = LanceStore(lancedb_settings(tmp_path), COLLECTION, dimensions=None)

    assert reopened.dimensions == 8
