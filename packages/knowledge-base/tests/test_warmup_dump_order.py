"""Writes land in submit order: a delete after an update leaves neither item nor file."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fake_kb import open_fake_kb, stored
from warmup_harness import warmup_settings
from write_harness import submit_write

from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_request,
    update_memory_item,
)
from tools_knowledge_base.warmup_dump import dump_file_name


def test_an_update_then_a_delete_submitted_back_to_back_leave_nothing(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    accepted = stored(kb, "one")
    assert sorted(p.name for p in tmp_path.iterdir()) == [dump_file_name("fake", accepted.item_id)]

    edit = update_memory_item(kb, "fake", accepted.item_id, {"title": "one", "tags": ["x"]})
    deleted = delete_memory_item(kb, "fake", accepted.item_id)

    assert edit.item_id == accepted.item_id
    assert get_memory_request(kb, edit.request_id).status == "done"
    assert get_memory_request(kb, deleted.request_id).status == "done"
    assert kb.store.kind_of(accepted.item_id) is None
    assert list(tmp_path.iterdir()) == []


def test_a_rename_older_than_its_retired_item_keeps_that_items_dump(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    kept = stored(kb, "one")
    renamed = stored(kb, "two")
    # A rename stamped before "one" was last written: the store keeps "one", so must the dump.
    submit_write(
        kb,
        renamed.item_id,
        {"title": "two", "tags": []},
        at=datetime(2000, 1, 1, tzinfo=UTC),
        replaces=kept.item_id,
    )
    kb.writes.drain()

    assert kb.store.kind_of(kept.item_id) == "fake"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        dump_file_name("fake", item.item_id) for item in (kept, renamed)
    )
