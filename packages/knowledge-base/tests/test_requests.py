"""``get_memory_request``: queued until the worker ends a write, then done or failed."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import override
from uuid import uuid4

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.errors import KnowledgeBaseError, UnknownRequest
from tools_knowledge_base.models import RequestState
from tools_knowledge_base.operations import get_memory_request, store_memory
from tools_knowledge_base.queue import drain, enqueue_write, make_huey


class _DownEmbedder(FakeEmbedder):
    """Counts the attempts; every one fails as an unreachable server would."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.attempts += 1
        msg = "embeddings server unreachable"
        raise KnowledgeBaseError(msg)


def test_a_write_reads_queued_then_done() -> None:
    kb = open_fake_kb()
    accepted = store_memory(kb, "fake", {"title": "huey", "tags": []})

    assert get_memory_request(kb, accepted.request_id) == RequestState(
        request_id=accepted.request_id, status="queued"
    )
    drain(kb.huey)

    assert get_memory_request(kb, accepted.request_id).status == "done"
    # preserve=True: reading the status does not consume it.
    assert get_memory_request(kb, accepted.request_id).status == "done"


def test_an_unknown_request_id_raises_naming_it() -> None:
    with pytest.raises(UnknownRequest, match="no request 'no-such-request' was queued"):
        get_memory_request(open_fake_kb(), "no-such-request")


def test_a_write_reads_queued_between_retries_then_failed_with_the_last_error(
    tmp_path: Path,
) -> None:
    testing = get_settings(Environment.TESTING)
    # Each retry is due at once, so the drain runs them all.
    queue = testing.queue.model_copy(
        update={"path": str(tmp_path / "queue.db"), "retry_delay_seconds": 0}
    )
    settings = testing.model_copy(update={"queue": queue})
    embedder = _DownEmbedder()
    kb = open_fake_kb(embedder=embedder, huey=make_huey(queue), settings=settings)
    accepted = store_memory(kb, "fake", {"title": "huey", "tags": []})

    first = kb.huey.dequeue()  # pyright: ignore[reportUnknownVariableType]
    kb.huey.execute(first)  # pyright: ignore[reportUnknownMemberType]
    assert get_memory_request(kb, accepted.request_id).status == "queued"
    drain(kb.huey)

    state = get_memory_request(kb, accepted.request_id)
    assert embedder.attempts == settings.queue.retries + 1
    assert state.status == "failed"
    assert state.error == "KnowledgeBaseError('embeddings server unreachable')"


def test_a_request_for_an_uninstalled_kind_fails_after_one_attempt() -> None:
    kb = open_fake_kb()
    request_id = enqueue_write(
        kb.write_memory,
        kind="uninstalled",
        item_id=uuid4(),
        payload={"title": "huey", "tags": []},
        updated_at=datetime.now(UTC),
        replaces=None,
    )

    assert drain(kb.huey) == (1, 1)

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    assert state.error is not None
    assert "unknown memory kind 'uninstalled'" in state.error


def test_a_payload_its_kind_no_longer_accepts_fails_after_one_attempt() -> None:
    kb = open_fake_kb()
    # As if the kind's model was tightened between the enqueue and the run.
    request_id = enqueue_write(
        kb.write_memory,
        kind="fake",
        item_id=uuid4(),
        payload={"title": "huey"},
        updated_at=datetime.now(UTC),
        replaces=None,
    )

    assert drain(kb.huey) == (1, 1)

    state = get_memory_request(kb, request_id)
    assert state.status == "failed"
    assert state.error is not None
    assert "validation error for FakePayload" in state.error


def test_write_memory_keeps_the_queue_key_messages_queued_before_an_upgrade_carry() -> None:
    task_class = open_fake_kb().write_memory.task_class
    assert f"{task_class.__module__}.{task_class.__name__}" == (
        "tools_knowledge_base.queue.write_memory"
    )
