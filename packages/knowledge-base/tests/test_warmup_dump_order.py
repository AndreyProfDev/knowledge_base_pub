"""A delete's dump removal holds when the worker runs it the moment it is queued."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fake_kb import open_fake_kb, stored
from huey import MemoryHuey  # pyright: ignore[reportMissingTypeStubs]
from warmup_harness import warmup_settings

from tools_knowledge_base.operations import delete_memory_item, get_memory_request
from tools_knowledge_base.queue import drain, enqueue_write
from tools_knowledge_base.warmup_dump import dump_file_name


def test_a_forget_run_as_soon_as_queued_still_drops_the_dump(tmp_path: Path) -> None:
    # immediate: the forget runs inside the enqueue, as a live consumer may.
    huey = MemoryHuey("knowledge-base", immediate=True)
    kb = open_fake_kb(huey=huey, settings=warmup_settings(tmp_path, dump=True))
    accepted = stored(kb, "one")
    assert sorted(p.name for p in tmp_path.iterdir()) == [dump_file_name("fake", accepted.item_id)]

    deleted = delete_memory_item(kb, "fake", accepted.item_id)

    assert get_memory_request(kb, deleted.request_id).status == "done"
    assert list(tmp_path.iterdir()) == []


def test_a_rename_older_than_its_retired_item_keeps_that_items_dump(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    kept = stored(kb, "one")
    renamed = stored(kb, "two")
    # A rename stamped before "one" was last written: the store keeps "one", so must the dump.
    enqueue_write(
        kb.write_memory,
        kind="fake",
        item_id=renamed.item_id,
        payload={"title": "two", "tags": []},
        updated_at=datetime(2000, 1, 1, tzinfo=UTC),
        replaces=kept.item_id,
    )
    drain(kb.huey)

    assert kb.store.kind_of(kept.item_id) == "fake"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        dump_file_name("fake", item.item_id) for item in (kept, renamed)
    )
