"""A drained write embeds and upserts; search, get, list and delete read it."""

from __future__ import annotations

import dataclasses
from uuid import uuid4

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import fake_registry, open_fake_kb
from fake_kind import FakeKind, FakePayload
from stevedore import ExtensionManager

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import ItemNotFound, UnknownKind
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    list_memory_items,
    search_memory,
    store_memory,
)


def _stored(kb: KnowledgeBase, title: str, tags: list[str], kind: str = "fake") -> None:
    store_memory(kb, kind, {"title": title, "tags": tags})


def test_draining_embeds_the_kind_text_and_stores_the_item() -> None:
    embedder = FakeEmbedder()
    kb = open_fake_kb(embedder=embedder)
    accepted = store_memory(kb, "fake", {"title": "celery", "tags": ["queue", "sqlite"]})

    kb.writes.drain()

    assert embedder.documents == ["celery queue sqlite"]
    item = get_memory_item(kb, "fake", accepted.item_id)
    assert item.payload == FakePayload(title="celery", tags=["queue", "sqlite"])
    assert item.kind == "fake"
    kb.writes.drain()


def test_two_queued_writes_of_one_key_leave_one_item_the_last_requested() -> None:
    kb = open_fake_kb()
    _stored(kb, "celery", ["first"])
    _stored(kb, "celery", ["second"])

    kb.writes.drain()

    page = list_memory_items(kb, "fake")
    assert [item.payload for item in page.items] == [FakePayload(title="celery", tags=["second"])]


def test_search_ranks_by_shared_words_and_scopes_to_a_kind() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("other"))
    _stored(kb, "queue", ["celery", "sqlite"])
    _stored(kb, "vectors", ["qdrant", "cosine"])
    _stored(kb, "queue", ["celery"], kind="other")
    kb.writes.drain()

    every = search_memory(kb, "celery sqlite queue")
    scoped = search_memory(kb, "celery sqlite queue", kind="fake", top_k=1)

    assert [(hit.kind, hit.payload.model_dump()["title"]) for hit in every[:2]] == [
        ("fake", "queue"),
        ("other", "queue"),
    ]
    assert every[0].score == pytest.approx(1.0)
    assert len(every) == 3
    assert [(hit.kind, hit.score) for hit in scoped] == [("fake", every[0].score)]


def test_search_takes_the_settings_top_k_and_an_explicit_floor() -> None:
    kb = open_fake_kb()
    for index in range(kb.settings.search.top_k + 1):
        _stored(kb, f"item{index}", [])
    kb.writes.drain()

    assert len(search_memory(kb, "item0")) == kb.settings.search.top_k
    assert [hit.score for hit in search_memory(kb, "item0", min_score=0.99)] == [pytest.approx(1.0)]


def test_search_defaults_to_the_embedders_floor() -> None:
    kb = open_fake_kb(embedder=FakeEmbedder(min_score=0.99))
    _stored(kb, "alpha", [])
    _stored(kb, "beta", [])
    kb.writes.drain()

    assert len(search_memory(kb, "alpha")) == 1


def test_a_kind_no_longer_installed_takes_none_of_the_top_k_places() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("gone"))
    _stored(kb, "sky green", [])
    _stored(kb, "sky blue", [], kind="gone")
    kb.writes.drain()
    reopened = dataclasses.replace(kb, kinds=fake_registry(FakeKind("fake")))

    [hit] = search_memory(reopened, "sky blue", top_k=1)
    assert hit.kind == "fake"


def test_search_with_no_kind_installed_finds_nothing() -> None:
    kb = open_fake_kb()
    _stored(kb, "sky", [])
    kb.writes.drain()
    empty = KindRegistry(ExtensionManager[MemoryKind].make_test_instance([]))

    assert search_memory(dataclasses.replace(kb, kinds=empty), "sky") == []


def test_search_of_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(UnknownKind):
        search_memory(open_fake_kb(), "anything", kind="nope")


def test_list_pages_with_the_cursor() -> None:
    kb = open_fake_kb()
    for title in ("a", "b", "c"):
        _stored(kb, title, [])
    kb.writes.drain()

    first = list_memory_items(kb, "fake", limit=2)
    assert first.next_cursor is not None
    rest = list_memory_items(kb, "fake", limit=2, cursor=first.next_cursor)

    titles = {item.payload.model_dump()["title"] for item in [*first.items, *rest.items]}
    assert titles == {"a", "b", "c"}
    assert rest.next_cursor is None
    with pytest.raises(UnknownKind):
        list_memory_items(kb, "nope")


def test_delete_removes_the_item_and_rejects_other_kinds_ids() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("other"))
    kept = store_memory(kb, "other", {"title": "kept", "tags": []})
    gone = store_memory(kb, "fake", {"title": "gone", "tags": []})
    kb.writes.drain()

    with pytest.raises(ItemNotFound, match=f"no fake item has id {kept.item_id}"):
        delete_memory_item(kb, "fake", kept.item_id)
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "fake", kept.item_id)
    delete_memory_item(kb, "fake", gone.item_id)

    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "fake", gone.item_id)
    with pytest.raises(ItemNotFound):
        delete_memory_item(kb, "fake", uuid4())
    assert get_memory_item(kb, "other", kept.item_id).payload.model_dump()["title"] == "kept"
