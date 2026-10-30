"""``LanceStore``: one embedded LanceDB table per embedder, partitioned by a ``kind`` column."""

from __future__ import annotations

import builtins
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

import lancedb
import pyarrow as pa
from lancedb.expr import Expr, col
from lancedb.query import ColumnOrdering, LanceQueryBuilder, LanceVectorQueryBuilder
from lancedb.table import Table

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid, stored_as
from tools_knowledge_base.store.protocol import Hit, Item, Point

_COLUMNS = ["id", "kind", "updated_at", "payload"]
type _FixedList = pa.FixedSizeListType[pa.DataType, int]


class LanceStore:
    """The ``lancedb`` adapter, on the directory ``vector_store.lancedb.path``.

    A missing ``collection`` table is created at ``dimensions``; with ``dimensions=None``
    it raises ``KnowledgeBaseError``. The connection re-reads every commit, so separate
    processes over one directory see each other's writes.
    """

    def __init__(
        self, settings: KnowledgeBaseSettings, collection: str, *, dimensions: int | None
    ) -> None:
        config = settings.vector_store.lancedb
        if config is None:
            msg = "vector_store.lancedb is unset"
            raise KnowledgeBaseError(msg)
        self._max_small_fragments: int = config.max_small_fragments
        db = lancedb.connect(config.path, read_consistency_interval=timedelta(0))
        try:
            self._table: Table = db.open_table(collection)
        except ValueError:
            if dimensions is None:
                msg = f"collection {collection!r} does not exist"
                raise KnowledgeBaseError(msg) from None
            # create_table's `data` union names an unstubbed pandas type.
            self._table = db.create_table(  # pyright: ignore[reportUnknownMemberType]
                collection, schema=_schema(dimensions)
            )
        # pyarrow-stubs leave Field's value type generic, so `.type` reads unknown.
        vector_type = cast("pa.DataType", self._table.schema.field("vector").type)  # pyright: ignore[reportUnknownMemberType]  # pragma: no mutate, equivalent: type-only
        if not isinstance(vector_type, pa.FixedSizeListType):
            msg = f"collection {collection!r} has no fixed-size vector column"
            raise KnowledgeBaseError(msg)
        fixed = cast("_FixedList", vector_type)  # pragma: no mutate, equivalent: type-only
        self.dimensions: int = fixed.list_size

    def upsert(self, points: Sequence[Point]) -> None:
        """Write each point unless its stored twin has an equal or newer ``updated_at``.

        Compacts the table once it has more than ``max_small_fragments`` small fragments.
        """
        if not points:
            return
        # merge_insert refuses two source rows for one id; keep each id's newest, as
        # applying the batch in order under the updated_at guard would.
        newest: dict[UUID, Point] = {}
        for point in points:
            kept = newest.get(point.id)
            if kept is None or kept.updated_at < point.updated_at:
                newest[point.id] = point
        rows = [
            {
                "id": str(point.id),
                "kind": point.kind,
                "updated_at": point.updated_at,
                "payload": json.dumps(point.payload),
                "vector": list(point.vector),
            }
            for point in newest.values()
        ]
        # Lance SQL folds unquoted identifiers to lower case, so a case change is a no-op.
        on = "id"  # pragma: no mutate, equivalent: identifiers are case-blind
        newer = "target.updated_at < source.updated_at"  # pragma: no mutate, equivalent: case-free
        merge = (
            self._table.merge_insert(on)
            .when_matched_update_all(where=newer)
            .when_not_matched_insert_all()
        )
        merge.execute(  # pyright: ignore[reportUnknownMemberType]
            pa.Table.from_pylist(rows, schema=_schema(self.dimensions))
        )
        # stats() is annotated as the TableStatistics dataclass but returns its dict.
        returned = cast("object", self._table.stats())  # pragma: no mutate, equivalent: type-only
        stats = cast("dict[str, Any]", returned)  # pragma: no mutate, equivalent: type-only
        if stats["fragment_stats"]["num_small_fragments"] > self._max_small_fragments:
            self._table.optimize()

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        """The points among ``ids`` that exist."""
        return [_item(self._table.name, row) for row in _rows(self._scan().where(_ids(ids)))]

    def kind_of(self, item_id: UUID) -> str | None:
        """The ``kind`` of row ``item_id``, ``None`` if absent; no other column is read."""
        query = self._scan().where(_ids([item_id])).select(["kind"])
        column = query.to_arrow().column("kind").to_pylist()
        kinds = cast("builtins.list[str]", column)  # pragma: no mutate, equivalent: type-only
        return kinds[0] if kinds else None

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        """One page of ``kind``'s points in id order from ``cursor``."""
        where = col("kind") == kind
        if cursor is not None:
            where &= col("id") >= str(cursor)
        ordered = self._scan().where(where).order_by([ColumnOrdering(column_name="id")])
        # More rows than limit + 1 change nothing: only rows[: limit + 1] are read.
        rows = _rows(ordered.limit(limit + 1))  # pragma: no mutate, equivalent: extra rows unread
        items = [_item(self._table.name, row) for row in rows[:limit]]
        return items, _cursor(self._table.name, rows[limit]) if len(rows) > limit else None

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        """Delete ``ids``; with ``older_than``, only those updated before it."""
        where = _ids(ids)
        if older_than is not None:
            where &= col("updated_at") < older_than
        self._table.delete(where)

    def count_kinds(self) -> dict[str, int]:
        """How many points each ``kind`` holds."""
        column = self._scan().select(["kind"]).to_arrow().column("kind").to_pylist()
        kinds = cast("builtins.list[str]", column)  # pragma: no mutate, equivalent: type-only
        return dict(Counter(kinds))

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        """The nearest points by cosine score (``1 - distance``), best first."""
        # A float list makes a vector query; search() is annotated as the base builder.
        found: object = self._table.search(list(vector))  # pyright: ignore[reportUnknownMemberType]
        query = cast("LanceVectorQueryBuilder", found)  # pragma: no mutate, equivalent: type-only
        # Lance lower-cases the distance type, so a case change is a no-op.
        cosine = "cosine"  # pragma: no mutate, equivalent: the name is case-blind
        query = query.distance_type(cosine).limit(limit)
        if kinds is not None:
            query = query.where(col("kind").isin(list(kinds)))
        if min_score is not None:
            query = query.distance_range(upper_bound=1 - min_score)
        rows = query.select([*_COLUMNS, "_distance"]).to_arrow().to_pylist()
        table = self._table.name
        return [Hit(**dict(_item(table, row)), score=1 - row["_distance"]) for row in rows]

    def _scan(self) -> LanceQueryBuilder:
        # search()'s query union names unstubbed PIL and pandas types.
        return self._table.search()  # pyright: ignore[reportUnknownMemberType]


def _schema(dimensions: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("updated_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("payload", pa.string(), nullable=False),
            pa.field("vector", pa.list_(pa.float32(), dimensions), nullable=False),
        ]
    )


def _rows(query: LanceQueryBuilder) -> builtins.list[dict[str, Any]]:
    return query.select(_COLUMNS).to_arrow().to_pylist()


def _ids(ids: Sequence[UUID]) -> Expr:
    return col("id").isin([str(i) for i in ids])


def _cursor(table: str, row: dict[str, Any]) -> UUID:
    """The next page's first id; one that is not a UUID raises ``StoredItemInvalid``."""
    try:
        return UUID(row["id"])
    except ValueError as exc:
        msg = f"row {row['id']} in {table!r} has an id that is not a UUID"
        raise StoredItemInvalid(msg) from exc


def _item(table: str, row: dict[str, Any]) -> Item:
    """``row`` as an ``Item``; one that fails it raises ``StoredItemInvalid``."""
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError as exc:
        msg = f"row {row['id']} in {table!r} has a payload that is not JSON: {exc}"
        raise StoredItemInvalid(msg) from exc
    fields = {key: row[key] for key in _COLUMNS}
    where = f"row {row['id']} in {table!r} is not a valid Item"
    return stored_as(Item, {**fields, "payload": payload}, where)
