"""What only the SQLite adapter does; the shared behaviour is core's conformance suite."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb, sqlite_settings
from store_adapters import COLLECTION, point, qdrant_settings

from tools_knowledge_base.errors import KnowledgeBaseError, StoredItemInvalid
from tools_knowledge_base.store.protocol import Item, Point
from tools_knowledge_base_sqlite.store import (
    SqliteStore,
    _micros,
)


def _store(tmp_path: Path, *, dimensions: int | None = 8) -> SqliteStore:
    return SqliteStore(sqlite_settings(tmp_path / "kb.db"), COLLECTION, dimensions=dimensions)


def _point(vector: list[float], *, kind: str = "fake") -> Point:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    return Point(id=uuid4(), kind=kind, updated_at=at, payload={}, vector=vector)


def test_a_store_is_used_from_a_second_thread(tmp_path: Path) -> None:
    store = _store(tmp_path)
    written = point("from the main thread")
    store.upsert([written])
    seen: list[list[Item]] = []

    worker = threading.Thread(target=lambda: seen.append(store.get([written.id])))
    worker.start()
    worker.join()

    assert [[item.id for item in items] for items in seen] == [[written.id]]


def test_a_failed_commit_rolls_back_and_the_thread_can_write_again(tmp_path: Path) -> None:
    store = _store(tmp_path)
    conn = store._conn()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE child (parent INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)"
    )

    with pytest.raises(sqlite3.IntegrityError), store._write() as writing:
        writing.execute("INSERT INTO child VALUES (1)")

    assert not conn.in_transaction
    with store._write() as writing:
        writing.execute("INSERT INTO parent VALUES (1)")
    assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 0


def test_a_body_that_already_ended_its_transaction_still_reraises(tmp_path: Path) -> None:
    store = _store(tmp_path)

    def end_then_fail(conn: sqlite3.Connection) -> None:
        conn.execute("ROLLBACK")
        message = "boom"
        raise ValueError(message)

    with pytest.raises(ValueError, match="boom"), store._write() as writing:
        end_then_fail(writing)

    assert not store._conn().in_transaction


def test_reopening_returns_the_stored_dimensions(tmp_path: Path) -> None:
    _ = _store(tmp_path, dimensions=8)

    assert _store(tmp_path, dimensions=None).dimensions == 8
    assert _store(tmp_path, dimensions=16).dimensions == 8


def test_reopening_at_another_dimension_through_the_knowledge_base_is_refused(
    tmp_path: Path,
) -> None:
    settings = sqlite_settings(tmp_path / "kb.db")
    first = open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-8", dimensions=8))
    first.store.count_kinds()
    second = open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-8", dimensions=16))

    with pytest.raises(KnowledgeBaseError, match="holds 8-dimension vectors, but embedder"):
        second.store.count_kinds()


def test_the_database_directory_is_created(tmp_path: Path) -> None:
    settings = sqlite_settings(tmp_path / "nested" / "dir" / "kb.db")

    _ = SqliteStore(settings, COLLECTION, dimensions=8)

    assert (tmp_path / "nested" / "dir" / "kb.db").is_file()


def test_a_failed_write_is_rolled_back_and_releases_the_write_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert([point("first")])
    raw = sqlite3.connect(tmp_path / "kb.db", autocommit=True)
    _ = raw.execute(f'DROP TABLE "{COLLECTION}"')

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        store.upsert([point("second")])

    # A write lock the failed upsert kept would make this raise "database is locked".
    other = sqlite3.connect(tmp_path / "kb.db", timeout=0, autocommit=True)
    _ = other.execute("BEGIN IMMEDIATE")
    _ = other.execute("ROLLBACK")


def test_every_connection_waits_five_seconds_in_wal_mode(tmp_path: Path) -> None:
    store = _store(tmp_path)

    conn = store._conn()

    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_a_thread_opens_one_autocommit_connection_and_reuses_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store._conn()
    store.upsert([point("reused")])

    assert store._conn() is first
    assert first.autocommit is True


def test_each_collection_gets_its_own_kind_index(tmp_path: Path) -> None:
    settings = sqlite_settings(tmp_path / "kb.db")
    _ = SqliteStore(settings, "alpha", dimensions=8)
    _ = SqliteStore(settings, "beta", dimensions=8)
    raw = sqlite3.connect(tmp_path / "kb.db", autocommit=True)

    names = raw.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()

    kind_indexes = sorted(name for (name,) in names if name.endswith(":kind"))
    assert kind_indexes == ["alpha:kind", "beta:kind"]


def test_a_page_of_exactly_the_remaining_rows_has_no_next_cursor(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert([point("one"), point("two")])

    items, cursor = store.list("fake", limit=2, cursor=None)

    assert len(items) == 2
    assert cursor is None


def test_updated_at_round_trips_to_the_microsecond_in_any_offset(tmp_path: Path) -> None:
    store = _store(tmp_path)
    at = datetime(2026, 3, 4, 5, 6, 7, 123456, tzinfo=timezone(timedelta(hours=5)))
    written = point("offset", at=at)
    store.upsert([written])

    (item,) = store.get([written.id])
    store.delete([written.id], older_than=at)
    survived = store.get([written.id])
    store.delete([written.id], older_than=at + timedelta(microseconds=1))

    assert item.updated_at == at
    assert item.updated_at.utcoffset() == timedelta(0)
    assert len(survived) == 1
    assert store.get([written.id]) == []


def test_micros_is_a_whole_integer_count_since_the_epoch() -> None:
    micros = _micros(datetime(1970, 1, 1, 0, 0, 1, 5, tzinfo=timezone(timedelta(hours=2))))

    assert micros == -7_198_999_995
    assert isinstance(micros, int)


@pytest.mark.parametrize("read", ["get", "list", "search"])
@pytest.mark.parametrize(("stored", "match"), [("[]", "not a valid Item"), ("{", "not JSON")])
def test_a_row_with_a_corrupt_envelope_is_stored_item_invalid(
    tmp_path: Path, read: str, stored: str, match: str
) -> None:
    store = _store(tmp_path)
    written = point("corrupt")
    store.upsert([written])
    raw = sqlite3.connect(tmp_path / "kb.db", autocommit=True)
    _ = raw.execute('UPDATE "memory-fake-8" SET payload = ?', (stored,))
    reads = {
        "get": lambda: store.get([written.id]),
        "list": lambda: store.list("fake", limit=10, cursor=None),
        "search": lambda: store.search(written.vector, kinds=None, limit=10, min_score=None),
    }

    with pytest.raises(StoredItemInvalid, match=f"row {written.id} in '{COLLECTION}'.*{match}"):
        _ = reads[read]()


def test_a_next_page_row_whose_id_is_not_a_uuid_is_stored_item_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    corrupt = uuid4()
    store.upsert([point("one"), point("two", point_id=corrupt)])
    raw = sqlite3.connect(tmp_path / "kb.db", autocommit=True)
    # "~" sorts after every hex digit, so the corrupt row is the second page's first.
    renamed = ("~not-a-uuid", str(corrupt))
    _ = raw.execute('UPDATE "memory-fake-8" SET id = ? WHERE id = ?', renamed)

    with pytest.raises(StoredItemInvalid, match=r"row ~not-a-uuid in 'memory-fake-8' .*not a UUID"):
        _ = store.list("fake", limit=1, cursor=None)


def test_search_orders_by_cosine_not_by_dot_product_and_min_score_keeps_equals(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, dimensions=2)
    short, long = _point([0.1, 0.0]), _point([3.0, 4.0])
    store.upsert([long, short])

    hits = store.search([2.0, 0.0], kinds=None, limit=10, min_score=None)
    kept = store.search([2.0, 0.0], kinds=None, limit=10, min_score=0.6)

    # The dot products are 0.2 and 6.0, which would put the long vector first.
    assert [hit.id for hit in hits] == [short.id, long.id]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.6], abs=1e-6)
    # The long vector's score is exactly 0.6, and a score equal to min_score is kept.
    assert [hit.id for hit in kept] == [short.id, long.id]


def test_settings_without_a_sqlite_block_are_refused() -> None:
    # The Qdrant settings select qdrant, so their sqlite block is unset.
    with pytest.raises(KnowledgeBaseError, match=r"^vector_store\.sqlite is unset$"):
        _ = SqliteStore(qdrant_settings(), COLLECTION, dimensions=8)
