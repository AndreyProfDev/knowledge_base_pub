"""The write and forget tasks: retry delay, cancels that never retry and stale dump refusals."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fake_kb import open_fake_kb, stored
from pydantic import JsonValue
from warmup_harness import BoomEmbedder, warmup_settings

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations import get_memory_request, store_memory
from tools_knowledge_base.queue import Drained, drain, enqueue_write
from tools_knowledge_base.tasks import enqueue_forget
from tools_knowledge_base.warmup_dump import dump_file_name

T1 = datetime(2001, 1, 1, tzinfo=UTC)


def _scheduled(kb: KnowledgeBase) -> int:
    return kb.huey.scheduled_count()  # pyright: ignore[reportUnknownVariableType]


def test_a_failed_write_waits_the_retry_delay(tmp_path: Path) -> None:
    kb = open_fake_kb(embedder=BoomEmbedder(), settings=warmup_settings(tmp_path, retries=1))
    accepted = store_memory(kb, "fake", {"title": "boom", "tags": []})

    assert drain(kb.huey) == Drained(ran=1, failed=1)
    assert get_memory_request(kb, accepted.request_id).status == "queued"
    assert _scheduled(kb) == 1


def _write(
    kb: KnowledgeBase,
    item_id: UUID,
    payload: dict[str, JsonValue],
    kind: str = "fake",
    replaces: UUID | None = None,
) -> str:
    return enqueue_write(
        kb.write_memory,
        kind=kind,
        item_id=item_id,
        payload=payload,
        updated_at=T1,
        replaces=replaces,
    )


def _cancelled(kb: KnowledgeBase, request_id: str) -> None:
    """One attempt failed, and no retry is scheduled even with retries and a delay."""
    assert drain(kb.huey) == Drained(ran=1, failed=1)
    assert get_memory_request(kb, request_id).status == "failed"
    assert _scheduled(kb) == 0


def test_a_write_of_an_uninstalled_kind_is_never_retried(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1))
    _cancelled(kb, _write(kb, uuid4(), {"title": "one", "tags": []}, kind="gone"))


def test_a_payload_its_kind_rejects_is_never_retried(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1))
    _cancelled(kb, _write(kb, uuid4(), {"title": "one"}))


def test_a_stale_dump_refusal_is_never_retried(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1))
    item_id = uuid4()
    (tmp_path / dump_file_name("fake", item_id)).write_text("title: old\n", encoding="utf-8")
    _cancelled(kb, enqueue_forget(kb.forget_memory, kind="fake", item_id=item_id))


def test_a_rename_checks_the_new_ids_file_when_the_old_id_has_none(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1))
    old = stored(kb, "one").item_id
    new = uuid4()
    (tmp_path / dump_file_name("fake", new)).write_text("title: other\n", encoding="utf-8")
    request_id = _write(kb, new, {"title": "one", "tags": []}, replaces=old)
    drain(kb.huey)

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    assert state.error is not None
    assert "warmup.dump is off" in state.error


def test_a_write_replacing_nothing_checks_no_other_file(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path, retries=1))
    (tmp_path / "fake-None.yaml").write_text("title: other\n", encoding="utf-8")
    request_id = _write(kb, uuid4(), {"title": "one", "tags": []})
    drain(kb.huey)

    assert get_memory_request(kb, request_id).status == "done"
