"""A kind with non-string fields, and a store whose upsert fails, for the dump tests."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tools_knowledge_base.store.protocol import Hit, Item, Point, VectorStore


class Reading(BaseModel):
    """Plain YAML scalars load as strings: these fields must survive lax validation."""

    model_config = ConfigDict(extra="forbid")

    title: str
    count: int
    pinned: bool
    seen: datetime


def _reading(payload: BaseModel) -> Reading:
    assert isinstance(payload, Reading)
    return payload


class ReadingKind:
    def __init__(self) -> None:
        self.name = "reading"
        self.payload_model: type[BaseModel] = Reading
        self.counted_over = "title"
        self.oversize_hint = "Shorten the title."

    def key(self, payload: BaseModel) -> str:
        return _reading(payload).title

    def embed_text(self, payload: BaseModel) -> str:
        return _reading(payload).title

    def render(self, payload: BaseModel) -> str:
        return _reading(payload).title


class RefusingStore:
    """``inner``, but every ``upsert`` raises."""

    def __init__(self, inner: VectorStore) -> None:
        self.inner = inner
        self.dimensions = inner.dimensions

    def upsert(self, points: Sequence[Point]) -> None:
        msg = "vector store unreachable"
        raise OSError(msg)

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        return self.inner.get(ids)

    def kind_of(self, item_id: UUID) -> str | None:
        return self.inner.kind_of(item_id)

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        return self.inner.list(kind, limit=limit, cursor=cursor)

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        self.inner.delete(ids, older_than=older_than)

    def count_kinds(self) -> dict[str, int]:
        return self.inner.count_kinds()

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        return self.inner.search(vector, kinds=kinds, limit=limit, min_score=min_score)
