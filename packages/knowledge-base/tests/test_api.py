"""The ``api`` facade: each call reaches its operation, on ``kb=`` or the cached one."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind, FakePayload
from warmup_harness import fake_items, warmup_settings, write_yaml

from tools_knowledge_base import api
from tools_knowledge_base.errors import ItemNotFound, UnknownRequest, UnknownWarmupRun
from tools_knowledge_base.queue import drain


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    api.reset()
    yield
    api.reset()


def test_the_facade_stores_searches_edits_lists_and_deletes() -> None:
    kb = open_fake_kb()
    stored = api.store("fake", {"title": "sky", "tags": ["blue"]}, kb=kb)
    assert api.request(stored.request_id, kb=kb).status == "queued"
    drain(kb.huey)

    [hit] = api.search("sky blue", kind="fake", top_k=1, kb=kb)
    edit = api.update("fake", stored.item_id, {"title": "sky by day", "tags": []}, kb=kb)
    drain(kb.huey)

    assert hit.id == stored.item_id
    assert api.request(stored.request_id, kb=kb).status == "done"
    assert api.get("fake", edit.item_id, kb=kb).payload == FakePayload(title="sky by day", tags=[])
    assert [item.id for item in api.items("fake", kb=kb).items] == [edit.item_id]
    deleted = api.delete("fake", edit.item_id, kb=kb)
    drain(kb.huey)
    assert deleted.item_id == edit.item_id
    assert api.request(deleted.request_id, kb=kb).status == "done"
    with pytest.raises(ItemNotFound):
        api.get("fake", edit.item_id, kb=kb)
    assert [kind.name for kind in api.kinds(kb=kb)] == ["fake"]


def test_search_passes_kind_top_k_and_min_score_through() -> None:
    kb = open_fake_kb(FakeKind(), FakeKind("other"))
    fake = stored(kb, "red apple")
    other = stored(kb, "red apple", kind="other")

    assert len(api.search("red apple", top_k=1, min_score=-1.0, kb=kb)) == 1
    assert [hit.id for hit in api.search("red apple", kind="other", kb=kb)] == [other.item_id]
    assert [hit.id for hit in api.search("red apple", kind="fake", kb=kb)] == [fake.item_id]
    # Exact matches score 1.0: only a floor that reached the store drops them.
    assert api.search("red apple", min_score=1.5, kb=kb) == []


def test_items_pages_through_limit_and_cursor() -> None:
    kb = open_fake_kb()
    ids = {stored(kb, title).item_id for title in ("a", "b")}

    first = api.items("fake", limit=1, kb=kb)
    second = api.items("fake", limit=1, cursor=first.next_cursor, kb=kb)

    assert first.next_cursor is not None
    assert len(first.items) == 1
    assert second.next_cursor is None
    assert {item.id for item in [*first.items, *second.items]} == ids


def test_without_kb_the_facade_opens_one_knowledge_base_per_process() -> None:
    with pytest.raises(UnknownRequest, match="'unknown'"):
        api.request("unknown")
    assert api.knowledge_base() is api.knowledge_base()

    opened = api.knowledge_base()
    api.reset()

    assert api.knowledge_base() is not opened


def test_warmup_queues_and_its_progress_follows(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    report = api.warmup(kb=kb)
    drain(kb.huey)

    progress = api.warmup_progress(report.run_id, kb=kb)

    assert (report.total_queued, progress.done, progress.finished) == (1, 1, True)
    with pytest.raises(UnknownWarmupRun):
        api.warmup_progress("nope", kb=kb)


def test_dir_lists_only_the_public_calls() -> None:
    assert dir(api) == api.__all__
