"""With the worker's ``warmup.dump`` off, only a dump file holding the written payload passes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml
from dump_harness import Reading, ReadingKind
from fake_kb import open_fake_kb, stored
from warmup_harness import warmup_settings

from tools_knowledge_base.models import RequestState
from tools_knowledge_base.operations import (
    get_memory_item,
    get_memory_request,
    list_memory_items,
    store_memory,
    update_memory_item,
    warmup_memory,
)
from tools_knowledge_base.queue import drain
from tools_knowledge_base.warmup_dump import dump_file_name

_SEEN = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_a_flag_off_worker_rebuilds_a_store_from_the_dump(tmp_path: Path) -> None:
    payload = Reading(title="gauge", count=3, pinned=True, seen=_SEEN)
    source = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=True))
    accepted = store_memory(source, "reading", payload.model_dump(mode="json"))
    drain(source.huey)
    dump = tmp_path / dump_file_name("reading", accepted.item_id)
    before = dump.read_bytes()

    rebuilt = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path))
    assert warmup_memory(rebuilt).total_queued == 1
    assert drain(rebuilt.huey).failed == 0

    assert get_memory_item(rebuilt, "reading", accepted.item_id).payload == payload
    assert dump.read_bytes() == before


def test_a_flag_off_edit_over_its_own_dump_file_fails(tmp_path: Path) -> None:
    on = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    first = stored(on, "one")
    off = open_fake_kb(settings=warmup_settings(tmp_path))
    stored(off, "one")  # same key, same payload: the file holds it

    edited = update_memory_item(off, "fake", first.item_id, {"title": "one", "tags": ["x"]})
    drain(off.huey)

    state = get_memory_request(off, edited.request_id)
    assert state.status == "failed"
    assert "warmup.dump is off; warm-up would restore this copy" in (state.error or "")


def test_a_flag_off_write_over_an_unreadable_dump_path_fails(tmp_path: Path) -> None:
    off = open_fake_kb(settings=warmup_settings(tmp_path))
    accepted = store_memory(off, "fake", {"title": "one", "tags": []})
    (tmp_path / dump_file_name("fake", accepted.item_id)).mkdir()
    drain(off.huey)

    _assert_refused(get_memory_request(off, accepted.request_id))


def test_a_flag_off_write_over_an_invalid_dump_file_fails(tmp_path: Path) -> None:
    off = open_fake_kb(settings=warmup_settings(tmp_path))
    accepted = store_memory(off, "fake", {"title": "one", "tags": []})
    path = tmp_path / dump_file_name("fake", accepted.item_id)
    path.write_bytes(b"fake: [\n\xff")
    drain(off.huey)

    _assert_refused(get_memory_request(off, accepted.request_id))
    path.write_text("fake: [", encoding="utf-8")
    again = store_memory(off, "fake", {"title": "one", "tags": []})
    drain(off.huey)

    _assert_refused(get_memory_request(off, again.request_id))


def test_a_flag_off_rename_fails_even_when_the_old_file_holds_the_old_payload(
    tmp_path: Path,
) -> None:
    on = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    first = stored(on, "one")
    off = open_fake_kb(settings=warmup_settings(tmp_path))
    stored(off, "one")

    renamed = update_memory_item(off, "fake", first.item_id, {"title": "two", "tags": []})
    drain(off.huey)

    _assert_refused(get_memory_request(off, renamed.request_id))
    assert [item.id for item in list_memory_items(off, "fake").items] == [first.item_id]
    assert (tmp_path / dump_file_name("fake", first.item_id)).exists()


def test_a_flag_off_rebuild_accepts_a_reindented_dump(tmp_path: Path) -> None:
    on = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    first = stored(on, "one", tags=["a", "b"])
    dump = tmp_path / dump_file_name("fake", first.item_id)
    before = dump.read_text(encoding="utf-8")
    reindented = yaml.safe_dump(yaml.safe_load(before), indent=4, width=10, sort_keys=True)
    assert reindented != before
    dump.write_text(reindented, encoding="utf-8")
    off = open_fake_kb(settings=warmup_settings(tmp_path))

    assert warmup_memory(off).total_queued == 1
    assert drain(off.huey).failed == 0


def _assert_refused(state: RequestState) -> None:
    assert state.status == "failed"
    assert "warmup.dump is off; warm-up would restore this copy" in (state.error or "")
