"""What only the Qdrant adapter does; the shared behaviour is core's conformance suite."""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override
from uuid import UUID, uuid4

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_qdrant.store import QdrantStore


def _settings() -> KnowledgeBaseSettings:
    return get_settings(Environment.TESTING)


def test_reopening_a_collection_reads_its_dimensions() -> None:
    client = QdrantClient(location=":memory:")
    _ = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=client)

    reopened = QdrantStore(_settings(), "memory-fake-8", dimensions=None, client=client)

    assert reopened.dimensions == 8


def test_a_collection_with_named_vectors_is_refused() -> None:
    client = QdrantClient(location=":memory:")
    _ = client.create_collection(
        "memory-named",
        vectors_config={
            "dense": models.VectorParams(size=8, distance=models.Distance.COSINE),
        },
    )

    with pytest.raises(KnowledgeBaseError, match="no single unnamed vector"):
        _ = QdrantStore(_settings(), "memory-named", dimensions=None, client=client)


def test_settings_without_a_qdrant_block_are_refused() -> None:
    settings = _settings()
    # model_copy skips validation, so the qdrant block can be dropped.
    vector_store = settings.vector_store.model_copy(update={"qdrant": None})
    settings = settings.model_copy(update={"vector_store": vector_store})

    with pytest.raises(KnowledgeBaseError, match=r"^vector_store\.qdrant is unset$"):
        _ = QdrantStore(settings, "memory-fake-8", dimensions=8)


class _IndexRecordingClient(QdrantClient):
    """A local client recording each index request: collection, field and schema."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.indexed: list[tuple[str, str, object]] = []

    @override
    def create_payload_index(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, collection_name: str, field_name: str, **kwargs: Any
    ) -> models.UpdateResult:
        self.indexed.append((collection_name, field_name, kwargs.get("field_schema")))
        return models.UpdateResult(operation_id=0, status=models.UpdateStatus.COMPLETED)


class _ServerClient(_IndexRecordingClient):
    """An in-memory client that reports itself as a server."""

    def __init__(self) -> None:
        super().__init__(location=":memory:")

    @property
    @override
    def init_options(self) -> dict[str, Any]:
        return {**super().init_options, "location": None, "url": "http://qdrant:6333"}


def test_a_server_gets_the_kind_tenant_index_local_mode_does_not() -> None:
    server = _ServerClient()
    _ = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=server)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _ = QdrantStore(_settings(), "memory-fake-8", dimensions=8)

    tenant = models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True)
    assert server.indexed == [("memory-fake-8", "kind", tenant)]


def test_in_memory_and_on_disk_local_modes_request_no_index(tmp_path: Path) -> None:
    memory = _IndexRecordingClient(location=":memory:")
    disk = _IndexRecordingClient(path=str(tmp_path))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _ = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=memory)
            _ = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=disk)
    finally:
        disk.close()

    assert (memory.indexed, disk.indexed) == ([], [])


def test_a_collection_of_another_distance_is_refused() -> None:
    client = QdrantClient(location=":memory:")
    _ = client.create_collection(
        "memory-dot", vectors_config=models.VectorParams(size=8, distance=models.Distance.DOT)
    )

    with pytest.raises(
        KnowledgeBaseError,
        match=r"^collection 'memory-dot' uses Dot distance; scores assume Cosine$",
    ):
        _ = QdrantStore(_settings(), "memory-dot", dimensions=None, client=client)


@pytest.mark.parametrize("missing", ["kind", "updated_at", "payload"])
def test_a_point_missing_a_payload_field_raises_naming_it(missing: str) -> None:
    client = QdrantClient(location=":memory:")
    store = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=client)
    point_id = str(uuid4())
    payload: dict[str, Any] = {"kind": "fake", "updated_at": "2026-01-01T00:00:00+00:00"}
    payload["payload"] = {}
    del payload[missing]
    _ = client.upsert(
        "memory-fake-8", [models.PointStruct(id=point_id, vector=[1.0] * 8, payload=payload)]
    )

    with pytest.raises(StoredItemInvalid, match=f"point {point_id} in 'memory-fake-8' has no"):
        _ = store.get([UUID(point_id)])


@pytest.mark.parametrize("read", ["get", "list", "search"])
def test_a_point_with_a_corrupt_envelope_is_stored_item_invalid(read: str) -> None:
    client = QdrantClient(location=":memory:")
    store = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=client)
    point_id = uuid4()
    payload: dict[str, Any] = {"kind": "fake", "updated_at": "not-a-date", "payload": {}}
    _ = client.upsert(
        "memory-fake-8", [models.PointStruct(id=str(point_id), vector=[1.0] * 8, payload=payload)]
    )
    reads = {
        "get": lambda: store.get([point_id]),
        "list": lambda: store.list("fake", limit=10, cursor=None),
        "search": lambda: store.search([1.0] * 8, kinds=None, limit=10, min_score=None),
    }

    with pytest.raises(StoredItemInvalid, match=f"point {point_id} in 'memory-fake-8'.*updated_at"):
        _ = reads[read]()


@pytest.mark.parametrize("stored_at", ["not-a-date", None])
def test_an_upsert_overwrites_a_point_whose_updated_at_is_not_a_date(
    stored_at: str | None,
) -> None:
    client = QdrantClient(location=":memory:")
    store = QdrantStore(_settings(), "memory-fake-8", dimensions=8, client=client)
    point_id = uuid4()
    payload: dict[str, Any] = {"kind": "fake", "payload": {}}
    if stored_at is not None:
        payload["updated_at"] = stored_at
    _ = client.upsert(
        "memory-fake-8", [models.PointStruct(id=str(point_id), vector=[1.0] * 8, payload=payload)]
    )
    at = datetime(2026, 1, 1, tzinfo=UTC)

    store.upsert([Point(id=point_id, kind="fake", updated_at=at, payload={}, vector=[1.0] * 8)])

    assert [item.updated_at for item in store.get([point_id])] == [at]
