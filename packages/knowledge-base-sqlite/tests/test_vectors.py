"""A vector that cannot be stored or scored raises instead of being stored or scored wrongly."""

from __future__ import annotations

import sqlite3
from array import array
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fake_kb import sqlite_settings
from store_adapters import COLLECTION

from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_sqlite.store import SqliteStore


def _store(tmp_path: Path) -> SqliteStore:
    return SqliteStore(sqlite_settings(tmp_path / "kb.db"), COLLECTION, dimensions=2)


def _point(vector: list[float]) -> Point:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    return Point(id=uuid4(), kind="fake", updated_at=at, payload={}, vector=vector)


def test_a_point_of_the_wrong_dimension_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    store = _store(tmp_path)
    good = _point([1.0, 0.0])

    with pytest.raises(KnowledgeBaseError, match="3-dimension vector does not fit a 2-dim"):
        store.upsert([good, _point([1.0, 0.0, 0.0])])

    assert store.get([good.id]) == []


@pytest.mark.parametrize("vector", [[0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0]])
def test_a_zero_or_non_finite_vector_is_refused_on_write_and_on_search(
    tmp_path: Path, vector: list[float]
) -> None:
    store = _store(tmp_path)

    with pytest.raises(KnowledgeBaseError, match="has no cosine similarity"):
        store.upsert([_point(vector)])
    with pytest.raises(KnowledgeBaseError, match="has no cosine similarity"):
        _ = store.search(vector, kinds=None, limit=1, min_score=None)


@pytest.mark.parametrize("vector", [[1e39, 1.0], [1e-50, 1e-50]])
def test_a_vector_that_overflows_or_underflows_in_float32_is_refused_on_write(
    tmp_path: Path, vector: list[float]
) -> None:
    store = _store(tmp_path)
    good = _point([1.0, 0.0])
    store.upsert([good])

    with pytest.raises(KnowledgeBaseError, match="has no cosine similarity"):
        store.upsert([_point(vector)])

    assert [h.id for h in store.search([1.0, 0.0], kinds=None, limit=5, min_score=None)] == [
        good.id
    ]


def test_a_query_of_the_wrong_dimension_is_refused(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="1-dimension vector does not fit"):
        _ = _store(tmp_path).search([1.0], kinds=None, limit=1, min_score=None)


@pytest.mark.parametrize(
    "blob", [b"", b"\x00" * 8, b"\x00" * 12, array("f", [1.0, 0.0, 0.0]).tobytes()]
)
def test_a_stored_embedding_that_cannot_be_scored_is_stored_item_invalid(
    tmp_path: Path, blob: bytes
) -> None:
    store = _store(tmp_path)
    written = _point([1.0, 0.0])
    store.upsert([written])
    raw = sqlite3.connect(tmp_path / "kb.db", autocommit=True)
    _ = raw.execute('UPDATE "memory-fake-8" SET embedding = ?', (blob,))

    with pytest.raises(StoredItemInvalid, match=f"row {written.id} holds a .*-dimension embedding"):
        _ = store.search([1.0, 0.0], kinds=None, limit=1, min_score=None)
