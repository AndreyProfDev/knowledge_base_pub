"""``QdrantStore``: one Qdrant collection per embedder, partitioned by a ``kind`` payload."""

from __future__ import annotations

import builtins
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from functools import partial
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.conversions.common_types import PointId
from qdrant_client.http import models

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid, stored_as
from tools_knowledge_base.store.protocol import Hit, Item, Point

_KIND = "kind"
_UPDATED_AT = "updated_at"
_PAYLOAD = "payload"
_PAGE = 256
"""Points per ``count_kinds`` scroll; a cost knob, unobservable in what it returns."""


class QdrantStore:
    """The ``qdrant`` adapter, on ``vector_store.qdrant.location``.

    A missing ``collection`` is created at ``dimensions``, with cosine distance and (on a
    server) a tenant ``kind`` index; with ``dimensions=None`` it raises
    ``KnowledgeBaseError``, as does an existing collection whose distance is not cosine.
    ``client`` overrides the one built from settings, so two stores can share one
    in-memory instance.
    """

    def __init__(
        self,
        settings: KnowledgeBaseSettings,
        collection: str,
        *,
        dimensions: int | None,
        client: QdrantClient | None = None,
    ) -> None:
        qdrant = settings.vector_store.qdrant
        if qdrant is None:
            msg = "vector_store.qdrant is unset"
            raise KnowledgeBaseError(msg)
        self._client: QdrantClient = client or QdrantClient(location=qdrant.location)
        self._collection: str = collection
        if self._client.collection_exists(collection):
            self.dimensions: int = self._stored_dimensions()
            return
        if dimensions is None:
            msg = f"collection {collection!r} does not exist"
            raise KnowledgeBaseError(msg)
        self._client.create_collection(
            collection,
            vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
        )
        if not _is_local(self._client):
            # Local mode has no payload indexes (it warns and ignores one); a server uses it.
            self._client.create_payload_index(
                collection,
                _KIND,
                field_schema=models.KeywordIndexParams(
                    type=models.KeywordIndexType.KEYWORD, is_tenant=True
                ),
            )
        self.dimensions = dimensions

    def _stored_dimensions(self) -> int:
        vectors = self._client.get_collection(self._collection).config.params.vectors
        if not isinstance(vectors, models.VectorParams):
            msg = f"collection {self._collection!r} has no single unnamed vector"
            raise KnowledgeBaseError(msg)
        if vectors.distance != models.Distance.COSINE:
            msg = (
                f"collection {self._collection!r} uses {vectors.distance.value} distance;"
                " scores assume Cosine"
            )
            raise KnowledgeBaseError(msg)
        return vectors.size

    def upsert(self, points: Sequence[Point]) -> None:
        """Write each point unless its stored twin has an equal or newer ``updated_at``."""
        operations: list[models.UpdateOperation] = [
            models.UpsertOperation(
                upsert=models.PointsList(
                    points=[
                        models.PointStruct(
                            id=str(point.id),
                            vector=list(point.vector),
                            payload={
                                _KIND: point.kind,
                                _UPDATED_AT: point.updated_at.isoformat(),
                                _PAYLOAD: point.payload,
                            },
                        )
                    ],
                    update_filter=_not_updated_since(point.updated_at),
                )
            )
            for point in points
        ]
        if operations:
            _ = self._client.batch_update_points(self._collection, operations)

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        """The points among ``ids`` that exist."""
        records = self._client.retrieve(self._collection, ids=[str(i) for i in ids])
        return [self._item(record.id, record.payload) for record in records]

    def kind_of(self, item_id: UUID) -> str | None:
        """The ``kind`` of point ``item_id``, ``None`` if absent; no other field is read."""
        records = self._client.retrieve(self._collection, ids=[str(item_id)], with_payload=[_KIND])
        return str(self._field(item_id, records[0].payload, _KIND)) if records else None

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        """One page of ``kind``'s points in id order from ``cursor``."""
        records, next_offset = self._client.scroll(
            self._collection,
            scroll_filter=_kinds_filter([kind]),
            limit=limit,
            offset=None if cursor is None else str(cursor),
        )
        items = [self._item(record.id, record.payload) for record in records]
        return items, None if next_offset is None else UUID(str(next_offset))

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        """Delete ``ids``; with ``older_than``, only those updated before it."""
        point_ids: builtins.list[models.ExtendedPointId] = [str(i) for i in ids]
        selector: models.PointIdsList | models.FilterSelector = (
            models.PointIdsList(points=point_ids)
            if older_than is None
            else models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.HasIdCondition(has_id=point_ids),
                        _updated_before_condition(older_than),
                    ]
                )
            )
        )
        _ = self._client.delete(self._collection, points_selector=selector)

    def count_kinds(self) -> dict[str, int]:
        """How many points each ``kind`` holds, scrolled from the ``kind`` payloads."""
        counts: Counter[str] = Counter()
        offset: PointId | None = None
        # The pragma silences this line's 5 mutants: 4 would be killed, and the survivor, a dropped
        # `limit`, is equivalent (Qdrant's default page scrolls the same points). The loop below
        # stays mutated; the inverted `if offset is not None` never ends, even on a single page, so
        # mutmut reports it Timeout or Killed depending on its hash-seeded test order.
        scroll = partial(self._client.scroll, limit=_PAGE)  # pragma: no mutate, equivalent: paging
        while True:
            records, offset = scroll(self._collection, offset=offset, with_payload=[_KIND])
            counts.update(str(self._field(r.id, r.payload, _KIND)) for r in records)
            if offset is None:
                return dict(counts)

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        """The nearest points by cosine score, best first."""
        response = self._client.query_points(
            self._collection,
            query=list(vector),
            query_filter=None if kinds is None else _kinds_filter(kinds),
            limit=limit,
            score_threshold=min_score,
        )
        return [Hit(**dict(self._item(p.id, p.payload)), score=p.score) for p in response.points]

    def _field(
        self, point_id: models.ExtendedPointId, payload: models.Payload | None, key: str
    ) -> object:
        if payload is None or key not in payload:
            msg = f"point {point_id} in {self._collection!r} has no {key!r} payload"
            raise StoredItemInvalid(msg)
        return payload[key]

    def _item(self, point_id: models.ExtendedPointId, payload: models.Payload | None) -> Item:
        """The point as an ``Item``; one that fails it raises ``StoredItemInvalid``."""
        fields = {
            key: self._field(point_id, payload, key) for key in (_KIND, _UPDATED_AT, _PAYLOAD)
        }
        where = f"point {point_id} in {self._collection!r} is not a valid Item"
        return stored_as(Item, {"id": str(point_id), **fields}, where)


def _is_local(client: QdrantClient) -> bool:
    """In-process mode: ``:memory:`` or an on-disk ``path``, not a server URL."""
    options = client.init_options
    return options["location"] == ":memory:" or options["path"] is not None


def _kinds_filter(kinds: Sequence[str]) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key=_KIND, match=models.MatchAny(any=list(kinds)))]
    )


def _updated_before_condition(moment: datetime) -> models.FieldCondition:
    return models.FieldCondition(key=_UPDATED_AT, range=models.DatetimeRange(lt=moment))


def _not_updated_since(moment: datetime) -> models.Filter:
    """Not a valid ``updated_at`` at or after ``moment``: a missing or garbage date is stale."""
    since = models.FieldCondition(key=_UPDATED_AT, range=models.DatetimeRange(gte=moment))
    return models.Filter(must_not=[since])
