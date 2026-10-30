"""After the queue drains, each id's dump file mirrors the store: its payload, or no file."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb, stored
from huey import MemoryHuey  # pyright: ignore[reportMissingTypeStubs]
from huey.api import Task  # pyright: ignore[reportMissingTypeStubs]
from huey.exceptions import CancelExecution  # pyright: ignore[reportMissingTypeStubs]
from pydantic import JsonValue
from warmup_harness import warmup_settings

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations import delete_memory_item, get_memory_request
from tools_knowledge_base.queue import Drained, drain, enqueue_write
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.tasks import (
    _drop_marker_unless_retried,
    enqueue_forget,
)
from tools_knowledge_base.warmup_dump import dump_file_name

T1 = datetime(2001, 1, 1, tzinfo=UTC)
T2 = datetime(2002, 1, 1, tzinfo=UTC)


def _write(
    kb: KnowledgeBase, item_id: UUID, tag: str, at: datetime, replaces: UUID | None = None
) -> str:
    return enqueue_write(
        kb.write_memory,
        kind="fake",
        item_id=item_id,
        payload={"title": "one", "tags": [tag]},
        updated_at=at,
        replaces=replaces,
    )


def _run_first_attempt_with_no_dump_dir(kb: KnowledgeBase, blocker: Path) -> None:
    # A file where the directory goes: the dump fails after the upsert landed.
    blocker.write_text("not a directory", encoding="utf-8")
    kb.huey.execute(kb.huey.dequeue())  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.parametrize("retries", [1, 2])
def test_a_retry_after_a_failed_dump_does_not_restore_a_deleted_item(
    tmp_path: Path, retries: int
) -> None:
    blocker = tmp_path / "warmup"
    kb = open_fake_kb(
        settings=warmup_settings(blocker, retries=retries, dump=True, due_retries=True)
    )
    item_id = uuid4()
    _write(kb, item_id, "a", T1)
    _run_first_attempt_with_no_dump_dir(kb, blocker)
    delete_memory_item(kb, "fake", item_id)
    if retries == 2:  # a second retry fails its dump too
        _run_first_attempt_with_no_dump_dir(kb, blocker)
    blocker.unlink()

    drain(kb.huey)

    assert kb.store.kind_of(item_id) is None
    assert not blocker.exists() or list(blocker.iterdir()) == []


def test_a_retry_running_after_a_newer_write_dumps_the_newer_payload(tmp_path: Path) -> None:
    blocker = tmp_path / "warmup"
    kb = open_fake_kb(settings=warmup_settings(blocker, retries=1, dump=True, due_retries=True))
    item_id = uuid4()
    _write(kb, item_id, "old", T1)
    _write(kb, item_id, "new", T2)
    _run_first_attempt_with_no_dump_dir(kb, blocker)
    blocker.unlink()

    drain(kb.huey)  # the newer write, then the older one's retry

    text = (blocker / dump_file_name("fake", item_id)).read_text(encoding="utf-8")
    assert "- new" in text


def test_an_older_write_the_store_keeps_out_leaves_the_newer_dump(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    item_id = uuid4()
    _write(kb, item_id, "new", T2)
    _write(kb, item_id, "old", T1)
    drain(kb.huey)

    [dump] = tmp_path.iterdir()
    assert "- new" in dump.read_text(encoding="utf-8")


def test_a_rename_retry_after_its_new_id_was_deleted_leaves_no_file(tmp_path: Path) -> None:
    blocker = tmp_path / "warmup"
    blocker.mkdir()
    kb = open_fake_kb(settings=warmup_settings(blocker, retries=1, dump=True, due_retries=True))
    old = stored(kb, "one").item_id
    new = uuid4()
    _write(kb, new, "a", datetime.now(UTC), replaces=old)
    (blocker / dump_file_name("fake", old)).unlink()
    blocker.rmdir()
    _run_first_attempt_with_no_dump_dir(kb, blocker)
    delete_memory_item(kb, "fake", new)
    blocker.unlink()

    drain(kb.huey)

    assert kb.store.get([old, new]) == []
    assert not blocker.exists() or list(blocker.iterdir()) == []


def _landed(kb: KnowledgeBase, request_id: str) -> bool:
    return kb.huey.get(f"landed:{request_id}", peek=True) is not None  # pyright: ignore[reportUnknownMemberType]


def test_the_last_attempt_drops_its_landed_marker(tmp_path: Path) -> None:
    blocker = tmp_path / "warmup"
    kb = open_fake_kb(settings=warmup_settings(blocker, retries=0, dump=True))
    request_id = _write(kb, uuid4(), "a", T1)
    _run_first_attempt_with_no_dump_dir(kb, blocker)

    assert get_memory_request(kb, request_id).status == "failed"
    assert not _landed(kb, request_id)


def test_a_cancel_after_the_upsert_drops_its_landed_marker(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1, dump=True))
    item_id = uuid4()
    [vector] = FakeEmbedder().embed_documents(["bogus"])
    # A newer stored copy its model rejects: the dump sync after the upsert cancels.
    kb.store.upsert(
        [Point(id=item_id, kind="fake", updated_at=T2, payload={"bogus": 1}, vector=vector)]
    )
    request_id = _write(kb, item_id, "a", T1)
    assert drain(kb.huey) == Drained(ran=1, failed=1)  # cancelled: no retry ran
    assert not _landed(kb, request_id)


def test_a_successful_write_drops_its_landed_marker(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1, dump=True))
    request_id = _write(kb, uuid4(), "a", T1)
    drain(kb.huey)

    assert get_memory_request(kb, request_id).status == "done"
    assert not _landed(kb, request_id)


@pytest.mark.parametrize(
    ("task", "cancel"),
    [
        # huey retries ``CancelExecution()`` (retry=None) while retries remain,
        (Task(retries=1), CancelExecution()),
        # and ``CancelExecution(retry=True)`` even with none left.
        (Task(retries=0), CancelExecution(retry=True)),
    ],
)
def test_a_cancel_that_is_retried_keeps_its_landed_marker(
    task: Task, cancel: CancelExecution
) -> None:
    huey = MemoryHuey("knowledge-base")
    huey.put("landed:x", True)  # noqa: FBT003 - a marker  # pyright: ignore[reportUnknownMemberType]
    _drop_marker_unless_retried(huey, "landed:x", task, cancel)

    assert huey.get("landed:x", peek=True) is True  # pyright: ignore[reportUnknownMemberType]


def test_a_forget_ignores_another_kinds_item_under_the_same_id(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, dump=True))
    item_id = uuid4()
    [vector] = FakeEmbedder().embed_documents(["one"])
    payload: dict[str, JsonValue] = {"title": "one", "tags": []}
    kb.store.upsert(
        [Point(id=item_id, kind="other", updated_at=T1, payload=payload, vector=vector)]
    )
    request_id = enqueue_forget(kb.forget_memory, kind="fake", item_id=item_id)
    drain(kb.huey)

    assert get_memory_request(kb, request_id).status == "done"
    assert list(tmp_path.iterdir()) == []
