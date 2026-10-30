"""One suite every installed ``VectorStore`` adapter passes, opened through ``open_store``.

The fixtures are ``conftest.py``'s, one run per adapter; search is ``test_vector_store_search.py``.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from stevedore import ExtensionManager
from store_adapters import ADAPTERS, EMBEDDER, T0, point

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.store.factory import VECTOR_STORES, open_store
from tools_knowledge_base.store.protocol import VectorStore


def test_every_installed_adapter_has_a_row() -> None:
    assert sorted(ExtensionManager(VECTOR_STORES).names()) == sorted(ADAPTERS)


def test_a_new_collection_reports_its_dimensions(store: VectorStore) -> None:
    assert store.dimensions == EMBEDDER.dimensions


def test_a_missing_collection_without_dimensions_is_refused(
    settings: KnowledgeBaseSettings,
) -> None:
    with pytest.raises(KnowledgeBaseError, match="does not exist"):
        _ = open_store(settings, "memory-absent-8", dimensions=None)


def test_upsert_overwrites_newer_and_leaves_older_in_one_batch(store: VectorStore) -> None:
    newer, older = point("newer one"), point("older one")
    store.upsert([newer, older])

    store.upsert(
        [
            point("newer two", point_id=newer.id, at=T0 + timedelta(seconds=1)),
            point("older two", point_id=older.id, at=T0 - timedelta(seconds=1)),
            point("same time", point_id=older.id, at=T0),
        ]
    )

    titles = {item.id: item.payload["title"] for item in store.get([newer.id, older.id])}
    assert titles == {newer.id: "newer two", older.id: "older one"}


def test_one_batch_with_two_newer_writes_of_an_id_keeps_the_newest(store: VectorStore) -> None:
    first = point("first")
    store.upsert([first])

    store.upsert(
        [
            point("newest", point_id=first.id, at=T0 + timedelta(seconds=2)),
            point("newer", point_id=first.id, at=T0 + timedelta(seconds=1)),
        ]
    )

    assert [item.payload["title"] for item in store.get([first.id])] == ["newest"]


def test_one_batch_with_two_same_time_writes_of_a_new_id_keeps_the_first(
    store: VectorStore,
) -> None:
    first = point("first")
    store.upsert([first, point("second", point_id=first.id)])

    assert [item.payload["title"] for item in store.get([first.id])] == ["first"]


def test_delete_older_than_spares_a_point_updated_exactly_then(store: VectorStore) -> None:
    boundary = point("boundary")
    store.upsert([boundary])

    store.delete([boundary.id], older_than=T0)

    assert [item.id for item in store.get([boundary.id])] == [boundary.id]


def test_an_empty_upsert_writes_nothing(store: VectorStore) -> None:
    store.upsert([])

    assert store.list("fake", limit=10, cursor=None) == ([], None)


def test_get_returns_the_stored_fields_of_existing_ids_only(store: VectorStore) -> None:
    alpha = point("alpha")
    store.upsert([alpha])

    items = store.get([alpha.id, uuid4()])

    assert len(items) == 1
    assert items[0].model_dump() == alpha.model_dump(exclude={"vector"})


def test_list_pages_one_kind_through_its_cursor(store: VectorStore) -> None:
    fakes = [point(f"fake {i}") for i in range(5)]
    store.upsert([*fakes, point("other", kind="other")])

    seen: list[UUID] = []
    cursor: UUID | None = None
    pages = 0
    for _ in range(10):  # a cursor that never ends fails instead of hanging
        page, cursor = store.list("fake", limit=2, cursor=cursor)
        pages += 1
        assert len(page) <= 2
        seen.extend(item.id for item in page)
        if cursor is None:
            break

    assert pages == 3
    assert sorted(seen) == sorted(p.id for p in fakes)


def test_kind_of_names_a_points_kind_and_none_for_an_absent_id(store: VectorStore) -> None:
    other = point("other", kind="other")
    store.upsert([other])

    assert (store.kind_of(other.id), store.kind_of(uuid4())) == ("other", None)


def test_count_kinds_counts_every_point_by_kind(store: VectorStore) -> None:
    assert store.count_kinds() == {}

    store.upsert([*(point(f"fake {i}") for i in range(3)), point("other", kind="other")])

    assert store.count_kinds() == {"fake": 3, "other": 1}


def test_delete_removes_the_ids(store: VectorStore) -> None:
    gone, kept = point("gone"), point("kept")
    store.upsert([gone, kept])

    store.delete([gone.id])

    assert [item.id for item in store.get([gone.id, kept.id])] == [kept.id]


def test_delete_older_than_spares_a_newer_point(store: VectorStore) -> None:
    old, new = point("old", at=T0), point("new", at=T0 + timedelta(seconds=2))
    store.upsert([old, new])

    store.delete([old.id, new.id], older_than=T0 + timedelta(seconds=1))

    assert [item.id for item in store.get([old.id, new.id])] == [new.id]
