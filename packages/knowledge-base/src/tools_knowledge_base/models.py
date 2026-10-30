"""What operations return: pydantic models, never formatted strings."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SerializeAsAny, WithJsonSchema

# A kind's validated payload: dumped with its own fields, schema'd as an open object.
# A plain alias, not a `type` statement: pydantic would emit that one as a `$ref`.
KindPayload = Annotated[
    SerializeAsAny[BaseModel],
    WithJsonSchema({"type": "object", "additionalProperties": True}),
]

type RequestStatus = Literal["queued", "done", "failed"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class WriteAccepted(_Frozen):
    """A store, edit or delete taken onto the queue; a delete's request removes its dump file."""

    request_id: str
    item_id: UUID
    status: RequestStatus


class MemoryItem(_Frozen):
    """One stored item, its payload validated back into its kind's model."""

    id: UUID
    kind: str
    updated_at: datetime
    payload: KindPayload


class MemoryHit(MemoryItem):
    """A search result: an item plus its cosine score."""

    score: float


class MemoryPage(_Frozen):
    """One page of a kind's items; ``next_cursor`` is ``None`` on the last."""

    items: list[MemoryItem]
    next_cursor: UUID | None


class RequestState(_Frozen):
    """Where a queued write is: ``error`` is set only when it ``failed``."""

    request_id: str
    status: RequestStatus
    error: str | None = None


class ReembedReport(_Frozen):
    """What one re-embed pass did; ``too_long`` lists the ids it left out.

    ``skipped_deleted`` counts source items an earlier run journaled in the active
    collection that are gone from it now (deleted or reworded away), which re-embed must
    not bring back.
    """

    copied: int
    skipped_existing: int
    skipped_deleted: int
    too_long: list[UUID]


class KindSchema(_Frozen):
    """An installed kind, its payload's JSON Schema, and its cap on the whole embed text."""

    name: str
    payload_schema: dict[str, Any]
    max_chars: int


class WarmupKindCounts(_Frozen):
    """One kind's share of a warm-up run."""

    queued: int
    unchanged: int


class WarmupShadow(_Frozen):
    """A hand-written item dropped for its differing dump copy; both as ``file:kind[index]``."""

    hand_written: str
    dump: str


class WarmupReport(_Frozen):
    """A warm-up run, validated and queued; ``kinds`` lists every installed kind.

    ``shadowed`` lists each hand-written copy whose payload differs from the dump copy
    that was queued instead; an identical one is not listed.
    """

    run_id: str
    kinds: dict[str, WarmupKindCounts]
    total_queued: int
    shadowed: list[WarmupShadow]


class WarmupFailure(_Frozen):
    """A write a warm-up run queued that failed its last retry."""

    request_id: str
    item_id: UUID
    kind: str
    error: str


class WarmupProgress(_Frozen):
    """How far the worker is through a warm-up run's writes.

    ``pending`` includes writes between retries; ``failures`` holds the first 50.
    """

    run_id: str
    total: int
    done: int
    failed: int
    pending: int
    unchanged: int
    finished: bool
    failures: list[WarmupFailure]
    failures_truncated: bool
