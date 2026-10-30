"""``VectorStore`` and the records it moves: ``Point`` in, ``Item`` and ``Hit`` out."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue


class Item(BaseModel):
    """A stored point without its vector; ``payload`` is the kind's payload as JSON."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    kind: str
    updated_at: AwareDatetime
    payload: dict[str, JsonValue]


class Point(Item):
    """What ``upsert`` writes: an item and its embedding."""

    vector: list[float]


class Hit(Item):
    """A search result: an item and its cosine score."""

    score: float


class VectorStore(Protocol):
    """One collection of points, partitioned by ``kind``."""

    dimensions: int
    """Of the opened collection or index."""

    def upsert(self, points: Sequence[Point]) -> None:
        """Write each point; one whose stored twin has an equal or newer ``updated_at`` is left."""
        ...

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        """The points among ``ids`` that exist, in any order."""
        ...

    def kind_of(self, item_id: UUID) -> str | None:
        """The ``kind`` of point ``item_id``, ``None`` if absent; no other field is read."""
        ...

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        """One page of ``kind``'s points from ``cursor``, and the first id of the next page."""
        ...

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        """Delete ``ids``; with ``older_than``, only points updated before it."""
        ...

    def count_kinds(self) -> dict[str, int]:
        """How many points each ``kind`` holds; kinds with no points are absent."""
        ...

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        """The nearest points by cosine score, best first, scoped to ``kinds`` when set."""
        ...
