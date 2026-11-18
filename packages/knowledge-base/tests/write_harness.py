"""Queued writes submitted by hand, and a ``sleep`` that records the retry delays."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from pydantic import JsonValue

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.writes import forget_item, write_item

T1 = datetime(2001, 1, 1, tzinfo=UTC)
T2 = datetime(2002, 1, 1, tzinfo=UTC)


class Sleeps:
    """A ``sleep`` that records each delay, then calls ``on_sleep`` if given."""

    def __init__(self, on_sleep: Callable[[], None] | None = None) -> None:
        self.calls: list[float] = []
        self.on_sleep = on_sleep

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.on_sleep is not None:
            self.on_sleep()


def submit_write(
    kb: KnowledgeBase,
    item_id: UUID,
    payload: dict[str, JsonValue],
    *,
    kind: str = "fake",
    at: datetime = T1,
    replaces: UUID | None = None,
) -> str:
    """Queue a ``write_item`` job; returns its request id."""
    return kb.writes.submit(
        partial(
            write_item,
            kb,
            kind=kind,
            item_id=item_id,
            payload=payload,
            updated_at=at,
            replaces=replaces,
        )
    )


def submit_forget(kb: KnowledgeBase, item_id: UUID, kind: str = "fake") -> str:
    """Queue a ``forget_item`` job; returns its request id."""
    return kb.writes.submit(partial(forget_item, kb, kind, item_id))
