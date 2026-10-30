"""Qdrant specifics past core's conformance suite (``test_core_suites.py``).

What each read asks Qdrant for, on a client that records it; points stored without the
adapter's payload; and the exact error messages.
"""

from __future__ import annotations

from typing import Any, override
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models
from store_adapters import COLLECTION, T0

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_qdrant.store import _PAGE, QdrantStore

_NEAR = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def point(title: str, *, kind: str = "fake", vector: list[float] = _NEAR) -> Point:
    return Point(id=uuid4(), kind=kind, updated_at=T0, payload={"title": title}, vector=vector)


class _RecordingClient(QdrantClient):
    """An in-memory client that records the keyword arguments of each scroll and retrieve."""

    def __init__(self) -> None:
        super().__init__(location=":memory:")
        self.scrolls: list[dict[str, Any]] = []
        self.retrieves: list[dict[str, Any]] = []

    @override
    def scroll(self, *args: Any, **kwargs: Any) -> tuple[list[models.Record], Any]:
        self.scrolls.append(kwargs)
        return super().scroll(*args, **kwargs)

    @override
    def retrieve(self, *args: Any, **kwargs: Any) -> list[models.Record]:
        self.retrieves.append(kwargs)
        return super().retrieve(*args, **kwargs)


def _store(client: QdrantClient | None = None) -> QdrantStore:
    return QdrantStore(
        get_settings(Environment.TESTING),
        COLLECTION,
        dimensions=len(_NEAR),
        client=client or QdrantClient(location=":memory:"),
    )


def test_a_missing_collection_without_dimensions_names_it() -> None:
    with pytest.raises(KnowledgeBaseError, match=r"^collection 'memory-absent' does not exist$"):
        _ = QdrantStore(get_settings(Environment.TESTING), "memory-absent", dimensions=None)


def test_kind_of_reads_only_the_kind_of_one_point() -> None:
    client = _RecordingClient()
    store = _store(client)
    other = point("other", kind="other")
    store.upsert([point("fake"), other])

    assert (store.kind_of(other.id), store.kind_of(uuid4())) == ("other", None)
    assert [call["with_payload"] for call in client.retrieves] == [["kind"], ["kind"]]


def test_kind_of_a_point_without_a_kind_names_the_point() -> None:
    client = QdrantClient(location=":memory:")
    store = _store(client)
    point_id = uuid4()
    _ = client.upsert(COLLECTION, [models.PointStruct(id=str(point_id), vector=[1.0] * 8)])

    with pytest.raises(StoredItemInvalid, match=f"^point {point_id} in 'memory-fake-8' has no"):
        _ = store.kind_of(point_id)


def test_delete_removes_a_point_without_an_updated_at() -> None:
    client = QdrantClient(location=":memory:")
    store = _store(client)
    point_id = uuid4()
    _ = client.upsert(COLLECTION, [models.PointStruct(id=str(point_id), vector=_NEAR)])

    store.delete([point_id])

    assert client.retrieve(COLLECTION, ids=[str(point_id)]) == []


def test_count_kinds_scrolls_kind_payloads_page_by_page() -> None:
    client = _RecordingClient()
    store = _store(client)
    # Past two of count_kinds' pages, whatever their size; the page size itself is not asserted.
    total = 2 * _PAGE + 1
    store.upsert([point(f"fake {i}") for i in range(total)])

    assert store.count_kinds() == {"fake": total}
    assert len(client.scrolls) > 1
    assert client.scrolls[0]["offset"] is None
    assert all(c["offset"] is not None for c in client.scrolls[1:])
    assert [c["with_payload"] for c in client.scrolls] == [["kind"]] * len(client.scrolls)


def test_count_kinds_of_a_point_without_a_kind_names_the_point() -> None:
    client = QdrantClient(location=":memory:")
    store = _store(client)
    point_id = uuid4()
    _ = client.upsert(COLLECTION, [models.PointStruct(id=str(point_id), vector=[1.0] * 8)])

    with pytest.raises(StoredItemInvalid, match=f"^point {point_id} in 'memory-fake-8' has no"):
        _ = store.count_kinds()
