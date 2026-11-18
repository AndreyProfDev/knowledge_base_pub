"""A write dumps every item it stores into ``warmup.path``, and drops deleted or renamed ones."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from dump_harness import Reading, ReadingKind, RefusingStore
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind, FakePayload
from warmup_harness import warmup_settings
from write_harness import submit_forget, submit_write

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    get_memory_request,
    list_memory_items,
    store_memory,
    update_memory_item,
    warmup_memory,
)
from tools_knowledge_base.operations.warmup_files import load_warmup_items
from tools_knowledge_base.warmup_dump import dump_file_name

_SEEN = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


def _kb(path: Path) -> KnowledgeBase:
    return open_fake_kb(FakeKind("fake"), settings=warmup_settings(path, dump=True))


def _files(path: Path) -> list[str]:
    return sorted(entry.name for entry in path.iterdir()) if path.exists() else []


def test_a_stored_item_is_dumped_and_loads_back_without_errors(tmp_path: Path) -> None:
    kb = _kb(tmp_path / "warmup")

    accepted = stored(kb, "one", ["a"])

    assert _files(tmp_path / "warmup") == [dump_file_name("fake", accepted.item_id)]
    [item] = load_warmup_items(kb).items
    assert (item.item_id, item.model) == (accepted.item_id, FakePayload(title="one", tags=["a"]))


def test_a_dump_rebuilds_an_empty_store_and_rewarms_as_unchanged(tmp_path: Path) -> None:
    settings = warmup_settings(tmp_path, dump=True)
    payload = Reading(title="gauge", count=3, pinned=True, seen=_SEEN)
    source = open_fake_kb(ReadingKind(), settings=settings)
    accepted = store_memory(source, "reading", payload.model_dump(mode="json"))
    source.writes.drain()

    rebuilt = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=True))
    assert list_memory_items(rebuilt, "reading").items == []
    assert warmup_memory(rebuilt).total_written == 1

    assert get_memory_item(rebuilt, "reading", accepted.item_id).payload == payload
    assert warmup_memory(rebuilt).total_written == 0


def test_a_write_refused_before_the_store_leaves_no_dump(tmp_path: Path) -> None:
    kb = _kb(tmp_path / "warmup")
    request_id = submit_write(kb, uuid4(), {}, kind="uninstalled", at=_SEEN)

    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "failed"
    assert _files(tmp_path / "warmup") == []


def test_a_failed_upsert_leaves_no_dump(tmp_path: Path) -> None:
    # Pins "never dump the queued payload". Dump-before-upsert reddens the stored-is-dumped tests.
    kb = _kb(tmp_path / "warmup")
    kb = replace(kb, store=RefusingStore(kb.store))
    request_id = submit_write(kb, uuid4(), {"title": "one", "tags": []}, at=_SEEN)

    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "failed"
    assert _files(tmp_path / "warmup") == []


def test_a_dump_that_cannot_be_written_fails_the_request(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("", encoding="utf-8")
    kb = _kb(not_a_dir)

    accepted = store_memory(kb, "fake", {"title": "one", "tags": []})
    kb.writes.drain()

    state = get_memory_request(kb, accepted.request_id)
    assert state.status == "failed"
    assert f"cannot write dump file {not_a_dir}" in (state.error or "")


def test_a_rename_then_a_delete_drop_the_dump_files(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    first = stored(kb, "one")

    renamed = update_memory_item(kb, "fake", first.item_id, {"title": "two", "tags": []})
    kb.writes.drain()
    assert _files(tmp_path) == [dump_file_name("fake", renamed.item_id)]

    deleted = delete_memory_item(kb, "fake", renamed.item_id)
    assert deleted.status == "done"
    assert _files(tmp_path) == []


def test_a_forget_for_an_item_stored_again_keeps_its_dump(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    accepted = stored(kb, "one")

    request_id = submit_forget(kb, accepted.item_id)
    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "done"
    assert _files(tmp_path) == [dump_file_name("fake", accepted.item_id)]


def test_a_dump_file_that_cannot_be_removed_fails_the_delete_request(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    accepted = stored(kb, "one")
    dump = tmp_path / dump_file_name("fake", accepted.item_id)
    dump.unlink()
    dump.mkdir()  # unlink() refuses a directory

    deleted = delete_memory_item(kb, "fake", accepted.item_id)

    state = get_memory_request(kb, deleted.request_id)
    assert (deleted.status, state.status) == ("failed", "failed")
    assert (state.error or "").startswith(f"WarmupDumpFailed: cannot remove dump file {dump}")
    assert list_memory_items(kb, "fake").items == []  # the item is gone all the same


def _stale_dump(path: Path, item_id: UUID) -> Path:
    stale = path / dump_file_name("fake", item_id)
    stale.write_text("fake: []\n", encoding="utf-8")
    return stale


def _failed_on(kb: KnowledgeBase, request_id: str, stale: Path) -> None:
    kb.writes.drain()
    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    assert f"dump file {stale} holds fake item" in (state.error or "")
    assert "warmup.dump is off; warm-up would restore this copy" in (state.error or "")
    assert stale.exists()


def test_a_delete_with_the_workers_dump_off_over_a_dump_file_fails(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    accepted = stored(kb, "one")
    stale = _stale_dump(tmp_path, accepted.item_id)

    deleted = delete_memory_item(kb, "fake", accepted.item_id)

    _failed_on(kb, deleted.request_id, stale)


def test_a_store_with_the_workers_dump_off_over_a_dump_file_fails(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    accepted = store_memory(kb, "fake", {"title": "one", "tags": []})
    stale = _stale_dump(tmp_path, accepted.item_id)

    _failed_on(kb, accepted.request_id, stale)
    assert list_memory_items(kb, "fake").items == []


def test_a_rename_with_the_workers_dump_off_over_the_old_dump_file_fails(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    first = stored(kb, "one")
    stale = _stale_dump(tmp_path, first.item_id)

    renamed = update_memory_item(kb, "fake", first.item_id, {"title": "two", "tags": []})

    _failed_on(kb, renamed.request_id, stale)
    assert [item.id for item in list_memory_items(kb, "fake").items] == [first.item_id]


def test_writes_with_the_workers_dump_off_and_no_dump_file_succeed(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    first = stored(kb, "one")

    renamed = update_memory_item(kb, "fake", first.item_id, {"title": "two", "tags": []})
    kb.writes.drain()
    deleted = delete_memory_item(kb, "fake", renamed.item_id)

    assert get_memory_request(kb, renamed.request_id).status == "done"
    assert get_memory_request(kb, deleted.request_id).status == "done"
    assert _files(tmp_path) == []
