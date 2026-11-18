"""After the queue drains, each id's dump file mirrors the store: its payload, or no file."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dump_harness import DeleteFailingOnceStore
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb, stored
from pydantic import JsonValue
from warmup_harness import warmup_settings
from write_harness import T1, T2, Sleeps, submit_forget, submit_write

from tools_knowledge_base.operations import get_memory_request
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.warmup_dump import dump_file_name


def _fake(tag: str) -> dict[str, JsonValue]:
    return {"title": "one", "tags": [tag]}


def test_a_retry_after_a_failed_dump_does_not_restore_a_deleted_item(tmp_path: Path) -> None:
    blocker = tmp_path / "warmup"
    blocker.write_text("not a directory", encoding="utf-8")  # the dump fails after the upsert
    item_id = uuid4()
    kb = open_fake_kb(settings=warmup_settings(blocker, dump=True))

    def delete_meanwhile() -> None:
        kb.store.delete([item_id])
        blocker.unlink()

    kb = replace(kb, sleep=Sleeps(delete_meanwhile))
    submit_write(kb, item_id, _fake("a"))

    kb.writes.drain()

    assert kb.store.kind_of(item_id) is None
    assert not blocker.exists() or list(blocker.iterdir()) == []


def test_an_older_write_the_store_keeps_out_leaves_the_newer_dump(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    item_id = uuid4()
    submit_write(kb, item_id, _fake("new"), at=T2)
    submit_write(kb, item_id, _fake("old"), at=T1)
    kb.writes.drain()

    [dump] = tmp_path.iterdir()
    assert "- new" in dump.read_text(encoding="utf-8")


def test_a_rename_retry_after_its_new_id_was_deleted_leaves_no_file(tmp_path: Path) -> None:
    blocker = tmp_path / "warmup"
    blocker.mkdir()
    kb = open_fake_kb(settings=warmup_settings(blocker, dump=True))
    old = stored(kb, "one").item_id
    new = uuid4()
    (blocker / dump_file_name("fake", old)).unlink()
    blocker.rmdir()
    blocker.write_text("not a directory", encoding="utf-8")  # the dump fails after the upsert

    def delete_meanwhile() -> None:
        kb.store.delete([new])
        blocker.unlink()

    kb = replace(kb, sleep=Sleeps(delete_meanwhile))
    submit_write(kb, new, _fake("a"), at=datetime.now(UTC), replaces=old)

    kb.writes.drain()

    assert kb.store.get([old, new]) == []
    assert not blocker.exists() or list(blocker.iterdir()) == []


def test_a_retry_after_a_failed_retire_with_dump_off_writes_no_file(tmp_path: Path) -> None:
    inner = open_fake_kb()
    old = stored(inner, "one").item_id
    store = DeleteFailingOnceStore(inner.store)
    kb = replace(open_fake_kb(settings=warmup_settings(tmp_path)), store=store)
    new = uuid4()
    submit_write(kb, new, {"title": "a", "tags": []}, at=datetime.now(UTC), replaces=old)

    kb.writes.drain()

    assert (store.kind_of(old), store.kind_of(new), store.deletes) == (None, "fake", 2)
    assert list(tmp_path.iterdir()) == []


def test_a_forget_ignores_another_kinds_item_under_the_same_id(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    item_id = uuid4()
    [vector] = FakeEmbedder().embed_documents(["one"])
    payload: dict[str, JsonValue] = {"title": "one", "tags": []}
    kb.store.upsert(
        [Point(id=item_id, kind="other", updated_at=T1, payload=payload, vector=vector)]
    )
    request_id = submit_forget(kb, item_id)
    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "done"
    assert list(tmp_path.iterdir()) == []
