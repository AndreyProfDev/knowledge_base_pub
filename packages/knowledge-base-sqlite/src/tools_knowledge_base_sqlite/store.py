"""``SqliteStore``: one SQLite table per embedder, exact cosine search in pure Python."""

from __future__ import annotations

import builtins
import heapq
import json
import sqlite3
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from operator import itemgetter
from pathlib import Path
from uuid import UUID

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid, stored_as
from tools_knowledge_base.store.protocol import Hit, Item, Point
from tools_knowledge_base_sqlite.vectors import cosine, norm_of, pack

# Every statement is a module constant: `{table}` is the quoted collection name.
_PRAGMAS = ("PRAGMA busy_timeout=5000", "PRAGMA journal_mode=WAL")
_BEGIN = "BEGIN IMMEDIATE"
_COMMIT = "COMMIT"
_ROLLBACK = "ROLLBACK"
_CREATE_COLLECTIONS = (
    "CREATE TABLE IF NOT EXISTS _collections(name TEXT PRIMARY KEY, dimensions INTEGER NOT NULL)"
)
_REGISTER = "INSERT OR IGNORE INTO _collections(name, dimensions) VALUES (?, ?)"
_DIMENSIONS = "SELECT dimensions FROM _collections WHERE name = ?"
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, kind TEXT NOT NULL,"
    " updated_at INTEGER NOT NULL, payload TEXT NOT NULL, embedding BLOB NOT NULL)"
)
_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS {index} ON {table}(kind)"
_UPSERT = (
    "INSERT INTO {table}(id, kind, updated_at, payload, embedding) VALUES (?, ?, ?, ?, ?)"
    " ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, updated_at = excluded.updated_at,"
    " payload = excluded.payload, embedding = excluded.embedding"
    " WHERE excluded.updated_at > {table}.updated_at"
)
_GET = (
    "SELECT id, kind, updated_at, payload FROM {table} WHERE id IN (SELECT value FROM json_each(?))"
)
_KIND_OF = "SELECT kind FROM {table} WHERE id = ?"
_LIST = (
    "SELECT id, kind, updated_at, payload FROM {table}"
    " WHERE kind = ? AND id >= ? ORDER BY id LIMIT ?"
)
_DELETE = "DELETE FROM {table} WHERE id IN (SELECT value FROM json_each(?))"
_DELETE_OLDER = (
    "DELETE FROM {table} WHERE id IN (SELECT value FROM json_each(?)) AND updated_at < ?"
)
_COUNT_KINDS = "SELECT kind, COUNT(*) AS n FROM {table} GROUP BY kind"
_SCAN = "SELECT id, kind, updated_at, payload, embedding FROM {table}"
_SCAN_KINDS = (
    "SELECT id, kind, updated_at, payload, embedding FROM {table}"
    " WHERE kind IN (SELECT value FROM json_each(?))"
)

# Row keys as constants: `sqlite3.Row` lookup ignores case, so a literal's case is no behaviour.
_ID, _KIND, _UPDATED, _PAYLOAD = "id", "kind", "updated_at", "payload"
_EMBEDDING, _COUNT, _DIMS = "embedding", "n", "dimensions"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


class SqliteStore:
    """The ``sqlite`` adapter, on the database file ``vector_store.sqlite.path``.

    A missing ``collection`` table is created at ``dimensions``; with ``dimensions=None``
    it raises ``KnowledgeBaseError``. Each thread has its own connection (WAL, 5 s busy
    wait); each write is one ``BEGIN IMMEDIATE`` transaction, so separate processes over
    one local file see each other's writes. Search scores every stored embedding.
    """

    def __init__(
        self, settings: KnowledgeBaseSettings, collection: str, *, dimensions: int | None
    ) -> None:
        config = settings.vector_store.sqlite
        if config is None:
            msg = "vector_store.sqlite is unset"
            raise KnowledgeBaseError(msg)
        self._path: Path = config.path
        self._collection: str = collection
        self._table: str = _quote(collection)
        self._local = threading.local()
        stored = self._stored_dimensions()
        if stored is None:
            if dimensions is None:
                msg = f"collection {collection!r} does not exist"
                raise KnowledgeBaseError(msg)
            stored = self._create(dimensions)
        self.dimensions: int = stored

    def upsert(self, points: Sequence[Point]) -> None:
        """Write each point unless its stored twin has an equal or newer ``updated_at``."""
        rows = [
            (
                str(point.id),
                point.kind,
                _micros(point.updated_at),
                json.dumps(point.payload),
                pack(point.vector, self.dimensions),
            )
            for point in points
        ]
        with self._write() as conn:
            conn.executemany(self._sql(_UPSERT), rows)

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        """The points among ``ids`` that exist."""
        rows = self._read(_GET, json.dumps([str(i) for i in ids]))
        return [_item(self._collection, row) for row in rows]

    def kind_of(self, item_id: UUID) -> str | None:
        """The ``kind`` of row ``item_id``, ``None`` if absent."""
        row = self._conn().execute(self._sql(_KIND_OF), (str(item_id),)).fetchone()
        return row[_KIND] if row is not None else None

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        """One page of ``kind``'s points in id order from ``cursor``."""
        # "" sorts before every id, so no cursor starts at the first row.
        start = str(cursor) if cursor is not None else ""
        # More rows than limit + 1 change nothing: only rows[: limit + 1] are read.
        fetch = limit + 1  # pragma: no mutate, equivalent: extra rows unread
        rows = self._read(_LIST, kind, start, fetch)
        items = [_item(self._collection, row) for row in rows[:limit]]
        return items, _cursor(self._collection, rows[limit]) if len(rows) > limit else None

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        """Delete ``ids``; with ``older_than``, only those updated before it."""
        wanted = json.dumps([str(i) for i in ids])
        with self._write() as conn:
            if older_than is None:
                conn.execute(self._sql(_DELETE), (wanted,))
            else:
                conn.execute(self._sql(_DELETE_OLDER), (wanted, _micros(older_than)))

    def count_kinds(self) -> dict[str, int]:
        """How many points each ``kind`` holds."""
        return {row[_KIND]: row[_COUNT] for row in self._read(_COUNT_KINDS)}

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        """The nearest points by cosine similarity, best first, each at least ``min_score``."""
        if kinds is None:
            rows = self._read(_SCAN)
        else:
            rows = self._read(_SCAN_KINDS, json.dumps(list(kinds)))
        query = list(vector)
        norm = norm_of(query, self.dimensions)
        scored = [(cosine(query, norm, row[_EMBEDDING], row[_ID]), row) for row in rows]
        kept = [pair for pair in scored if min_score is None or pair[0] >= min_score]
        best = heapq.nlargest(limit, kept, key=itemgetter(0))
        return [Hit(**dict(_item(self._collection, row)), score=score) for score, row in best]

    def _sql(self, template: str) -> str:
        return template.format(table=self._table, index=_quote(f"{self._collection}:kind"))

    def _read(self, template: str, *params: object) -> builtins.list[sqlite3.Row]:
        return self._conn().execute(self._sql(template), params).fetchall()

    def _conn(self) -> sqlite3.Connection:
        """This thread's connection; a thread's first call opens it."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, autocommit=True)
            conn.row_factory = sqlite3.Row
            for pragma in _PRAGMAS:
                conn.execute(pragma)
            conn.execute(_CREATE_COLLECTIONS)
            self._local.conn = conn
        return conn

    @contextmanager
    def _write(self) -> Generator[sqlite3.Connection]:
        """One write transaction: the lock is taken up front, rolled back if the body raises."""
        conn = self._conn()
        conn.execute(_BEGIN)
        try:
            yield conn
            conn.execute(_COMMIT)
        except BaseException:
            if conn.in_transaction:  # a failed COMMIT leaves the transaction open
                conn.execute(_ROLLBACK)
            raise

    def _stored_dimensions(self) -> int | None:
        row = self._conn().execute(_DIMENSIONS, (self._collection,)).fetchone()
        return row[_DIMS] if row is not None else None

    def _create(self, dimensions: int) -> int:
        """Register and create the collection; another process may have won, so read it back."""
        with self._write() as conn:
            conn.execute(_REGISTER, (self._collection, dimensions))
            conn.execute(self._sql(_CREATE_TABLE))
            conn.execute(self._sql(_CREATE_INDEX))
            row = conn.execute(_DIMENSIONS, (self._collection,)).fetchone()
        return row[_DIMS]


def _quote(name: str) -> str:
    """``name`` as a SQL identifier; collection names hold no quote character."""
    return f'"{name}"'


def _micros(moment: datetime) -> int:
    """``moment`` as whole microseconds since the epoch, exact whatever its offset."""
    return (moment - _EPOCH) // _MICROSECOND


def _cursor(table: str, row: sqlite3.Row) -> UUID:
    """The next page's first id; one that is not a UUID raises ``StoredItemInvalid``."""
    try:
        return UUID(row[_ID])
    except ValueError as exc:
        msg = f"row {row[_ID]} in {table!r} has an id that is not a UUID"
        raise StoredItemInvalid(msg) from exc


def _item(table: str, row: sqlite3.Row) -> Item:
    """``row`` as an ``Item``; one that fails it raises ``StoredItemInvalid``."""
    try:
        payload = json.loads(row[_PAYLOAD])
    except json.JSONDecodeError as exc:
        msg = f"row {row[_ID]} in {table!r} has a payload that is not JSON: {exc}"
        raise StoredItemInvalid(msg) from exc
    updated_at = _EPOCH + timedelta(microseconds=row[_UPDATED])
    fields = {"id": row[_ID], "kind": row[_KIND], "updated_at": updated_at, "payload": payload}
    return stored_as(Item, fields, f"row {row[_ID]} in {table!r} is not a valid Item")
