"""``LazyStore``: a ``VectorStore`` that opens the real one on its first use."""

from __future__ import annotations

import builtins
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from tools_knowledge_base.store.protocol import Hit, Item, Point, VectorStore


class LazyStore:
    """Opens ``open`` under a lock on the first call and keeps the result for the process.

    A failed open is not kept, so the next call tries again.
    """

    def __init__(self, open_store: Callable[[], VectorStore]) -> None:
        """Remember how to open the store; nothing is opened yet."""
        self._open = open_store
        self._lock = threading.Lock()
        self._store: VectorStore | None = None

    def _opened(self) -> VectorStore:
        with self._lock:
            if self._store is None:
                self._store = self._open()
            return self._store

    @property
    def dimensions(self) -> int:
        """Of the opened collection or index."""
        return self._opened().dimensions

    def upsert(self, points: Sequence[Point]) -> None:
        """Write each point; see ``VectorStore.upsert``."""
        self._opened().upsert(points)

    def get(self, ids: Sequence[UUID]) -> builtins.list[Item]:
        """The points among ``ids`` that exist, in any order."""
        return self._opened().get(ids)

    def kind_of(self, item_id: UUID) -> str | None:
        """The ``kind`` of point ``item_id``, ``None`` if absent."""
        return self._opened().kind_of(item_id)

    def list(
        self, kind: str, *, limit: int, cursor: UUID | None
    ) -> tuple[builtins.list[Item], UUID | None]:
        """One page of ``kind``'s points from ``cursor``, and the first id of the next page."""
        return self._opened().list(kind, limit=limit, cursor=cursor)

    def delete(self, ids: Sequence[UUID], *, older_than: datetime | None = None) -> None:
        """Delete ``ids``; with ``older_than``, only points updated before it."""
        self._opened().delete(ids, older_than=older_than)

    def count_kinds(self) -> dict[str, int]:
        """How many points each ``kind`` holds."""
        return self._opened().count_kinds()

    def search(
        self,
        vector: Sequence[float],
        *,
        kinds: Sequence[str] | None,
        limit: int,
        min_score: float | None,
    ) -> builtins.list[Hit]:
        """The nearest points by cosine score, best first."""
        return self._opened().search(vector, kinds=kinds, limit=limit, min_score=min_score)
