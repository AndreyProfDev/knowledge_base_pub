"""The write and forget jobs: refusals that never retry, stale dumps and the landed upsert."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import override
from uuid import uuid4

import yaml
from dump_harness import Reading, ReadingKind, RefusingStore
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb, stored
from warmup_harness import BoomEmbedder, warmup_settings
from write_harness import Sleeps, submit_forget, submit_write

from tools_knowledge_base.operations import get_memory_request, store_memory
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.warmup_dump import dump_file_name

_SEEN = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
_READING = Reading(title="gauge", count=3, pinned=True, seen=_SEEN)


class _CountingStore(RefusingStore):
    """``inner``, but ``upsert`` lands and counts."""

    upserts = 0

    @override
    def upsert(self, points: Sequence[Point]) -> None:
        self.upserts += 1
        self.inner.upsert(points)


def test_a_write_that_keeps_failing_is_tried_three_times_with_the_delays_between(
    tmp_path: Path,
) -> None:
    sleeps = Sleeps()
    kb = open_fake_kb(embedder=BoomEmbedder(), settings=warmup_settings(tmp_path), sleep=sleeps)
    accepted = store_memory(kb, "fake", {"title": "boom", "tags": []})

    kb.writes.drain()

    assert sleeps.calls == [1.0, 2.0]
    assert get_memory_request(kb, accepted.request_id).status == "failed"


def _refused(sleeps: Sleeps, kb_error: str | None, expected: str) -> None:
    """The write failed with ``expected`` in its error, after one attempt: no sleep."""
    assert sleeps.calls == []
    assert kb_error is not None
    assert expected in kb_error


def test_a_write_of_an_uninstalled_kind_is_never_retried(tmp_path: Path) -> None:
    sleeps = Sleeps()
    kb = open_fake_kb(settings=warmup_settings(tmp_path), sleep=sleeps)
    request_id = submit_write(kb, uuid4(), {"title": "one", "tags": []}, kind="gone")
    kb.writes.drain()

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    _refused(sleeps, state.error, "WriteRefused: unknown memory kind 'gone'")


def test_a_payload_its_kind_rejects_is_never_retried(tmp_path: Path) -> None:
    sleeps = Sleeps()
    kb = open_fake_kb(settings=warmup_settings(tmp_path), sleep=sleeps)
    request_id = submit_write(kb, uuid4(), {"title": "one"})
    kb.writes.drain()

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    _refused(sleeps, state.error, "validation error for FakePayload")


def test_a_stale_dump_refusal_is_never_retried(tmp_path: Path) -> None:
    sleeps = Sleeps()
    kb = open_fake_kb(settings=warmup_settings(tmp_path), sleep=sleeps)
    item_id = uuid4()
    (tmp_path / dump_file_name("fake", item_id)).write_text("title: old\n", encoding="utf-8")
    request_id = submit_forget(kb, item_id)
    kb.writes.drain()

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    _refused(sleeps, state.error, "warmup.dump is off")


def test_a_rename_checks_the_new_ids_file_when_the_old_id_has_none(tmp_path: Path) -> None:
    sleeps = Sleeps()
    kb = open_fake_kb(settings=warmup_settings(tmp_path), sleep=sleeps)
    old = stored(kb, "one").item_id
    new = uuid4()
    (tmp_path / dump_file_name("fake", new)).write_text("title: other\n", encoding="utf-8")
    request_id = submit_write(kb, new, {"title": "one", "tags": []}, replaces=old)
    kb.writes.drain()

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    _refused(sleeps, state.error, "warmup.dump is off")


def test_a_write_replacing_nothing_checks_no_other_file(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    (tmp_path / "fake-None.yaml").write_text("title: other\n", encoding="utf-8")
    request_id = submit_write(kb, uuid4(), {"title": "one", "tags": []})
    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "done"


def test_the_dump_file_holds_json_values(tmp_path: Path) -> None:
    kb = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=True))
    store_memory(kb, "reading", _READING.model_dump(mode="json"))
    kb.writes.drain()

    [file] = tmp_path.iterdir()
    document = yaml.safe_load(file.read_text(encoding="utf-8"))
    assert document["reading"][0]["seen"] == "2024-01-02T03:04:05Z"


def test_a_dump_file_holding_the_written_payload_does_not_refuse_the_write(tmp_path: Path) -> None:
    source = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=True))
    accepted = store_memory(source, "reading", _READING.model_dump(mode="json"))
    source.writes.drain()

    off = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=False))
    request_id = submit_write(
        off, accepted.item_id, _READING.model_dump(mode="json"), kind="reading"
    )
    off.writes.drain()

    assert get_memory_request(off, request_id).status == "done"


def test_a_write_replacing_itself_retires_nothing_and_refuses_no_matching_file(
    tmp_path: Path,
) -> None:
    source = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=True))
    accepted = store_memory(source, "reading", _READING.model_dump(mode="json"))
    source.writes.drain()

    off = open_fake_kb(ReadingKind(), settings=warmup_settings(tmp_path, dump=False))
    request_id = submit_write(
        off,
        accepted.item_id,
        _READING.model_dump(mode="json"),
        kind="reading",
        replaces=accepted.item_id,
    )
    off.writes.drain()

    assert get_memory_request(off, request_id).status == "done"


def test_a_write_with_the_dump_on_succeeds_at_the_first_attempt(tmp_path: Path) -> None:
    sleeps = Sleeps()
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True), sleep=sleeps)
    item_id = uuid4()
    request_id = submit_write(kb, item_id, {"title": "one", "tags": []})

    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "done"
    assert sleeps.calls == []
    assert (tmp_path / dump_file_name("fake", item_id)).is_file()


def test_a_stored_copy_its_model_rejects_names_the_item_in_the_error(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    item_id = uuid4()
    [vector] = FakeEmbedder().embed_documents(["bogus"])
    newer = datetime(2002, 1, 1, tzinfo=UTC)
    kb.store.upsert(
        [Point(id=item_id, kind="fake", updated_at=newer, payload={"bogus": 1}, vector=vector)]
    )
    request_id = submit_write(kb, item_id, {"title": "one", "tags": []})
    kb.writes.drain()

    assert f"fake item {item_id}:" in (get_memory_request(kb, request_id).error or "")


def test_a_retry_after_the_upsert_landed_only_retires_and_dumps(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    old = stored(kb, "one").item_id
    store = _CountingStore(kb.store)
    new = uuid4()
    blocked = tmp_path / dump_file_name("fake", new)
    blocked.mkdir()  # the new file cannot be written: the first attempt fails after the upsert

    def unblock() -> None:
        blocked.rmdir()
        (tmp_path / dump_file_name("fake", old)).unlink()

    sleeps = Sleeps(unblock)
    kb = replace(kb, store=store, sleep=sleeps)
    request_id = submit_write(kb, new, {"title": "one", "tags": []}, replaces=old)

    kb.writes.drain()

    assert get_memory_request(kb, request_id).status == "done"
    assert (sleeps.calls, store.upserts) == ([1.0], 1)
    assert (tmp_path / dump_file_name("fake", new)).is_file()
    # The old copy is newer than the write: the store keeps it, so its file is synced back.
    assert [item.id for item in kb.store.get([old])] == [old]
    assert (tmp_path / dump_file_name("fake", old)).is_file()
