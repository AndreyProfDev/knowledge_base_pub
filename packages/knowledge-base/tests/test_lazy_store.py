from __future__ import annotations

import builtins
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.store.lazy import LazyStore
from tools_knowledge_base.store.protocol import Hit, Item, Point

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_ITEM = Item(id=uuid4(), kind="fake", updated_at=_NOW, payload={})


class _Recorder:
    """A store that records each call it gets."""

    dimensions = 8

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def upsert(self, points: Sequence[Point]) -> None:
        self.calls.append(("upsert", points))

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        self.calls.append(("get", ids))
        return [_ITEM]

    def kind_of(self, item_id: UUID) -> str | None:
        self.calls.append(("kind_of", item_id))
        return "fake"

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        self.calls.append(("list", (kind, limit, cursor)))
        return [_ITEM], _ITEM.id

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        self.calls.append(("delete", (ids, older_than)))

    def count_kinds(self) -> dict[str, int]:
        self.calls.append(("count_kinds", None))
        return {"fake": 3}

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        self.calls.append(("search", (vector, kinds, limit, min_score)))
        return [Hit(**_ITEM.model_dump(), score=0.5)]


def test_nothing_opens_before_the_first_call() -> None:
    opened: list[int] = []

    def open_it() -> _Recorder:
        opened.append(1)
        return _Recorder()

    LazyStore(open_it)

    assert opened == []


def test_each_method_reaches_the_opened_store_with_its_arguments() -> None:
    inner = _Recorder()
    store = LazyStore(lambda: inner)
    some_id = uuid4()
    when = datetime(2026, 2, 2, tzinfo=UTC)

    assert store.dimensions == 8
    store.upsert([])
    assert store.get([some_id]) == [_ITEM]
    assert store.kind_of(some_id) == "fake"
    assert store.list("fake", limit=5, cursor=some_id) == ([_ITEM], _ITEM.id)
    store.delete([some_id], older_than=when)
    store.delete([some_id])
    assert store.count_kinds() == {"fake": 3}
    assert store.search([1.0], kinds=["fake"], limit=4, min_score=0.1) == [
        Hit(**_ITEM.model_dump(), score=0.5)
    ]

    assert inner.calls == [
        ("upsert", []),
        ("get", [some_id]),
        ("kind_of", some_id),
        ("list", ("fake", 5, some_id)),
        ("delete", ([some_id], when)),
        ("delete", ([some_id], None)),
        ("count_kinds", None),
        ("search", ([1.0], ["fake"], 4, 0.1)),
    ]


def test_the_store_opens_once_across_calls() -> None:
    opened: list[_Recorder] = []

    def open_once() -> _Recorder:
        opened.append(_Recorder())
        return opened[-1]

    store = LazyStore(open_once)
    store.count_kinds()
    store.count_kinds()

    assert len(opened) == 1
    assert len(opened[0].calls) == 2


def test_threads_racing_for_the_first_call_open_the_store_once() -> None:
    opened: list[int] = []
    inside = threading.Event()

    def slow_open() -> _Recorder:
        opened.append(1)
        inside.wait(0.2)
        return _Recorder()

    store = LazyStore(slow_open)
    threads = [threading.Thread(target=store.count_kinds) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert opened == [1]


def test_a_failed_open_is_retried_by_the_next_call() -> None:
    attempts: list[int] = []

    def flaky() -> _Recorder:
        attempts.append(1)
        if len(attempts) == 1:
            msg = "unreachable"
            raise KnowledgeBaseError(msg)
        return _Recorder()

    store = LazyStore(flaky)
    with pytest.raises(KnowledgeBaseError, match="unreachable"):
        store.count_kinds()

    assert store.count_kinds() == {"fake": 3}
    assert len(attempts) == 2
