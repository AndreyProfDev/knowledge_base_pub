"""``get_memory_request``: queued until the queue runs a write, then done or failed."""

from __future__ import annotations

from collections.abc import Sequence
from typing import override

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from write_harness import Sleeps

from tools_knowledge_base.errors import KnowledgeBaseError, UnknownRequest
from tools_knowledge_base.models import RequestState
from tools_knowledge_base.operations import get_memory_request, store_memory


class _DownEmbedder(FakeEmbedder):
    """Counts the attempts; the first ``failures`` fail as an unreachable server would."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.attempts = 0
        self.failures = failures

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.attempts += 1
        if self.attempts <= self.failures:
            msg = "embeddings server unreachable"
            raise KnowledgeBaseError(msg)
        return super().embed_documents(texts)


def test_a_write_reads_queued_then_done() -> None:
    kb = open_fake_kb()
    accepted = store_memory(kb, "fake", {"title": "celery", "tags": []})

    assert get_memory_request(kb, accepted.request_id) == RequestState(
        request_id=accepted.request_id, status="queued"
    )
    kb.writes.drain()

    assert get_memory_request(kb, accepted.request_id).status == "done"
    # Reading the status does not consume it.
    assert get_memory_request(kb, accepted.request_id).status == "done"


def test_an_unknown_request_id_raises_naming_it() -> None:
    with pytest.raises(UnknownRequest, match="request no-such-request was not issued by this"):
        get_memory_request(open_fake_kb(), "no-such-request")


def test_a_write_fails_with_the_last_error_after_three_attempts_and_two_sleeps() -> None:
    embedder = _DownEmbedder(failures=3)
    sleeps = Sleeps()
    kb = open_fake_kb(embedder=embedder, sleep=sleeps)
    accepted = store_memory(kb, "fake", {"title": "celery", "tags": []})

    assert get_memory_request(kb, accepted.request_id).status == "queued"
    kb.writes.drain()

    state = get_memory_request(kb, accepted.request_id)
    assert (embedder.attempts, sleeps.calls) == (3, [1.0, 2.0])
    assert state.status == "failed"
    assert state.error == "KnowledgeBaseError: embeddings server unreachable"


def test_a_write_that_fails_once_lands_after_one_sleep() -> None:
    embedder = _DownEmbedder(failures=1)
    sleeps = Sleeps()
    kb = open_fake_kb(embedder=embedder, sleep=sleeps)
    accepted = store_memory(kb, "fake", {"title": "celery", "tags": []})

    kb.writes.drain()

    assert get_memory_request(kb, accepted.request_id).status == "done"
    assert (embedder.attempts, sleeps.calls) == (2, [1.0])
    assert [item.id for item in kb.store.get([accepted.item_id])] == [accepted.item_id]
