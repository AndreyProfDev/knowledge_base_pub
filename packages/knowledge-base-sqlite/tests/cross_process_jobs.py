"""Jobs for ``test_cross_process``: importable by name, so a fork server's children can run them."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from datetime import timedelta
from functools import partial
from multiprocessing import get_context
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from uuid import UUID

from store_adapters import COLLECTION, T0

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base_sqlite.store import SqliteStore

DIMENSIONS = 1536
READS = 50
TIMEOUT = 120

Job = Callable[[Barrier], object]
Outcome = tuple[bool, object]


def vector(seed: int) -> list[float]:
    rng = random.Random(seed)  # noqa: S311 - test data, not a secret
    return [rng.uniform(-1, 1) for _ in range(DIMENSIONS)]


def make_point(seed: int, *, at_step: int = 0, point_id: UUID | None = None) -> Point:
    return Point(
        id=point_id or UUID(int=seed + 1),
        kind="fake",
        updated_at=T0 + timedelta(seconds=at_step),
        payload={"title": f"point {seed}", "tags": [], "at": at_step},
        vector=vector(seed),
    )


def open_store(settings: KnowledgeBaseSettings) -> SqliteStore:
    return SqliteStore(settings, COLLECTION, dimensions=DIMENSIONS)


def _child(job: Job, barrier: Barrier, results: Queue[Outcome]) -> None:
    try:
        results.put((True, job(barrier)))
    except Exception as exc:
        results.put((False, repr(exc)))


def run(jobs: Sequence[Job]) -> list[object]:
    """Run ``jobs`` in fork-server processes released together; fail on any exception.

    A fork server is a clean single-threaded process, so no child is forked from this
    multi-threaded one (Python 3.12 warns about that, and it can deadlock the child).
    """
    ctx = get_context("forkserver")
    barrier = ctx.Barrier(len(jobs))
    results: Queue[Outcome] = ctx.Queue()
    processes = [ctx.Process(target=_child, args=(job, barrier, results)) for job in jobs]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=TIMEOUT) for _ in processes]
    for process in processes:
        process.join()
    assert [value for ok, value in outcomes if not ok] == []
    return [value for ok, value in outcomes if ok]


def _write_all(settings: KnowledgeBaseSettings, points: Sequence[Point], barrier: Barrier) -> None:
    store = open_store(settings)
    barrier.wait(TIMEOUT)
    for point in points:
        store.upsert([point])


def _read_many(settings: KnowledgeBaseSettings, barrier: Barrier) -> None:
    store = open_store(settings)
    barrier.wait(TIMEOUT)
    for seed in range(READS):
        store.search(vector(seed), kinds=None, limit=5, min_score=None)
        store.count_kinds()


def writer(settings: KnowledgeBaseSettings, points: Sequence[Point]) -> Job:
    return partial(_write_all, settings, points)


def reader(settings: KnowledgeBaseSettings) -> Job:
    return partial(_read_many, settings)


def _on_fresh_store(
    settings: KnowledgeBaseSettings, job: Callable[[SqliteStore], object], barrier: Barrier
) -> object:
    barrier.wait(TIMEOUT)
    return job(open_store(settings))


def fresh(settings: KnowledgeBaseSettings, job: Callable[[SqliteStore], object]) -> object:
    """``job`` run on a store opened in a new process."""
    return run([partial(_on_fresh_store, settings, job)])[0]


def count_found(ids: Sequence[UUID], store: SqliteStore) -> int:
    return len(store.get(ids))


def nearest_to_first(store: SqliteStore) -> UUID:
    return store.search(vector(0), kinds=None, limit=1, min_score=None)[0].id
