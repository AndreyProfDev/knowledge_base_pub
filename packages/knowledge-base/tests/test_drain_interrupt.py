"""Ctrl-C during ``drain``: the dequeued or due tasks go back on the queue, then it re-raises."""

from __future__ import annotations

from collections.abc import Sequence
from typing import override

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from huey import MemoryHuey  # pyright: ignore[reportMissingTypeStubs]
from huey.api import ChordResult, Result, ResultGroup  # pyright: ignore[reportMissingTypeStubs]
from huey.signals import SIGNAL_EXECUTING  # pyright: ignore[reportMissingTypeStubs]

from tools_knowledge_base.operations import get_memory_request, list_memory_items, store_memory
from tools_knowledge_base.queue import drain


class _InterruptedOnceEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.interrupts = 1

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.interrupts:
            self.interrupts -= 1
            raise KeyboardInterrupt
        return super().embed_documents(texts)


class _InterruptingHuey(MemoryHuey):
    """A ``MemoryHuey`` whose first result write or first enqueue, when armed, is Ctrl-C."""

    def __init__(self) -> None:
        super().__init__("knowledge-base", store_intermediate_errors=False)  # pyright: ignore[reportUnknownMemberType]
        self.interrupt_put_result = 0
        self.interrupt_enqueue = 0

    @override
    def put_result(self, key: object, data: object) -> object:
        if self.interrupt_put_result:
            self.interrupt_put_result -= 1
            raise KeyboardInterrupt
        return super().put_result(key, data)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    @override
    def enqueue(self, task: object) -> ResultGroup | ChordResult | Result | None:
        if self.interrupt_enqueue:
            self.interrupt_enqueue -= 1
            raise KeyboardInterrupt
        return super().enqueue(task)  # pyright: ignore[reportUnknownMemberType]


def test_an_interrupted_task_is_requeued_and_the_rest_left_unrun() -> None:
    embedder = _InterruptedOnceEmbedder()
    kb = open_fake_kb(embedder=embedder)
    first = store_memory(kb, "fake", {"title": "first", "tags": []})
    store_memory(kb, "fake", {"title": "second", "tags": []})

    with pytest.raises(KeyboardInterrupt):
        drain(kb.huey)

    assert kb.huey.pending_count() == 2
    assert list_memory_items(kb, "fake").items == []
    assert get_memory_request(kb, first.request_id).status == "queued"
    assert drain(kb.huey) == (2, 0)
    assert get_memory_request(kb, first.request_id).status == "done"


def test_ctrl_c_in_an_executing_signal_handler_requeues_the_task() -> None:
    kb = open_fake_kb()
    accepted = store_memory(kb, "fake", {"title": "first", "tags": []})
    interrupts = [1]

    def _ctrl_c(_signal: str, _task: object, *_args: object) -> None:
        if interrupts:
            interrupts.pop()
            raise KeyboardInterrupt

    kb.huey.signal(SIGNAL_EXECUTING)(_ctrl_c)  # pyright: ignore[reportUnknownMemberType]

    with pytest.raises(KeyboardInterrupt):
        drain(kb.huey)

    assert kb.huey.pending_count() == 1
    assert drain(kb.huey) == (1, 0)
    assert get_memory_request(kb, accepted.request_id).status == "done"


def test_ctrl_c_while_storing_the_result_requeues_the_task() -> None:
    huey = _InterruptingHuey()
    kb = open_fake_kb(huey=huey)
    accepted = store_memory(kb, "fake", {"title": "first", "tags": []})
    huey.interrupt_put_result = 1

    with pytest.raises(KeyboardInterrupt):
        drain(kb.huey)

    assert kb.huey.pending_count() == 1
    assert get_memory_request(kb, accepted.request_id).status == "queued"
    assert drain(kb.huey) == (1, 0)
    assert get_memory_request(kb, accepted.request_id).status == "done"
    assert len(list_memory_items(kb, "fake").items) == 1


def test_ctrl_c_while_enqueueing_due_tasks_puts_them_all_on_the_queue() -> None:
    huey = _InterruptingHuey()
    kb = open_fake_kb(huey=huey)
    store_memory(kb, "fake", {"title": "first", "tags": []})
    store_memory(kb, "fake", {"title": "second", "tags": []})
    while (task := huey.dequeue()) is not None:  # pyright: ignore[reportUnknownVariableType]
        huey.add_schedule(task)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    huey.interrupt_enqueue = 1

    with pytest.raises(KeyboardInterrupt):
        drain(kb.huey)

    assert (huey.scheduled_count(), huey.pending_count()) == (0, 2)
    assert drain(kb.huey) == (2, 0)
