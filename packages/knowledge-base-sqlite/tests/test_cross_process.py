"""Several processes on one SQLite file through ``SqliteStore``: no lock error, no lost write.

Load: 8 writers and 4 readers at once, about 2.5 s. Probe (by hand, never committed):
with no busy handler at all (``timeout=0`` and no ``busy_timeout`` PRAGMA) this fails with
``database is locked`` at 8 writers. Dropping only the PRAGMA, or only using a deferred
``BEGIN``, stays green at 8 writers: ``sqlite3.connect`` keeps its own 5 s busy handler,
and every transaction's first statement is a write, so a deferred ``BEGIN`` takes the
write lock with the same wait. Those two mutations are equivalent here.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from functools import partial
from pathlib import Path
from uuid import UUID

from cross_process_jobs import (
    DIMENSIONS,
    count_found,
    fresh,
    make_point,
    nearest_to_first,
    open_store,
    reader,
    run,
    writer,
)
from fake_kb import sqlite_settings
from store_adapters import T0

_WRITERS = 8
_READERS = 4
_PER_WRITER = 200
_SHARED_IDS = 20
_ROUNDS = _PER_WRITER // _SHARED_IDS
_EMBEDDINGS = 'SELECT embedding FROM "memory-fake-8"'  # COLLECTION's table


def test_concurrent_writers_and_readers_lose_nothing(tmp_path: Path) -> None:
    settings = sqlite_settings(tmp_path / "knowledge.db")
    writers = [
        writer(settings, [make_point(w * _PER_WRITER + i) for i in range(_PER_WRITER)])
        for w in range(_WRITERS)
    ]

    run([*writers, *[reader(settings) for _ in range(_READERS)]])

    total = _WRITERS * _PER_WRITER
    ids = [UUID(int=seed + 1) for seed in range(total)]
    assert sum(open_store(settings).count_kinds().values()) == total
    assert fresh(settings, partial(count_found, ids)) == total
    # Writer 0's first point, queried by its own vector, is the nearest.
    assert fresh(settings, nearest_to_first) == UUID(int=1)


def test_writers_racing_on_the_same_ids_keep_the_newest(tmp_path: Path) -> None:
    settings = sqlite_settings(tmp_path / "knowledge.db")
    # Writer w, round r stamps every shared id with step r * _WRITERS + w: all distinct.
    writers = [
        writer(
            settings,
            [
                make_point(i, at_step=r * _WRITERS + w)
                for r in range(_ROUNDS)
                for i in range(_SHARED_IDS)
            ],
        )
        for w in range(_WRITERS)
    ]

    run([*writers, *[reader(settings) for _ in range(_READERS)]])

    newest = _ROUNDS * _WRITERS - 1
    items = open_store(settings).get([UUID(int=i + 1) for i in range(_SHARED_IDS)])
    assert [item.payload["at"] for item in items] == [newest] * _SHARED_IDS
    assert [item.updated_at for item in items] == [T0 + timedelta(seconds=newest)] * _SHARED_IDS
    with sqlite3.connect(tmp_path / "knowledge.db") as raw:
        sizes = {len(blob) for (blob,) in raw.execute(_EMBEDDINGS)}
    assert sizes == {DIMENSIONS * 4}
