"""Importable facade — the shape notebooks and scripts use.

from tools_knowledge_base import api as kb

kb.store("knowledge", {"category": "fact", "content": "the sky is blue"})
kb.search("sky colour")

Every call takes an optional ``kb=``; without it, the process-wide knowledge base for
``TOOLS_ENV`` is opened on first use. Writes are queued: ``knowledge-base-worker``
embeds them.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from uuid import UUID

from knowledge_base_config import environment_from_env
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.models import (
    KindSchema,
    MemoryHit,
    MemoryItem,
    MemoryPage,
    RequestState,
    WarmupProgress,
    WarmupReport,
    WriteAccepted,
)
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    get_memory_request,
    get_warmup_progress,
    list_memory_items,
    list_memory_kinds,
    search_memory,
    store_memory,
    update_memory_item,
    warmup_memory,
)


@lru_cache(maxsize=1)
def knowledge_base() -> KnowledgeBase:
    """Return the process-wide knowledge base, opened from ``TOOLS_ENV`` on first use."""
    return open_knowledge_base(get_settings(environment_from_env()))


def reset() -> None:
    """Drop the cached knowledge base so the next call re-opens it."""
    knowledge_base.cache_clear()


def store(
    kind: str, payload: Mapping[str, object], *, kb: KnowledgeBase | None = None
) -> WriteAccepted:
    """Queue a new item. Example: ``store("knowledge", {"category": "fact", "content": "…"})``."""
    return store_memory(kb or knowledge_base(), kind, payload)


def update(
    kind: str, item_id: UUID, payload: Mapping[str, object], *, kb: KnowledgeBase | None = None
) -> WriteAccepted:
    """Queue item ``item_id``'s replacement; the result's ``item_id`` is the new key's."""
    return update_memory_item(kb or knowledge_base(), kind, item_id, payload)


def search(
    query: str,
    *,
    kind: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    kb: KnowledgeBase | None = None,
) -> list[MemoryHit]:
    """The items nearest ``query``, best first. Example: ``search("sky colour", top_k=3)``."""
    return search_memory(kb or knowledge_base(), query, kind=kind, top_k=top_k, min_score=min_score)


def get(kind: str, item_id: UUID, *, kb: KnowledgeBase | None = None) -> MemoryItem:
    """Item ``item_id`` of ``kind``."""
    return get_memory_item(kb or knowledge_base(), kind, item_id)


def items(
    kind: str,
    *,
    limit: int = 50,
    cursor: UUID | None = None,
    kb: KnowledgeBase | None = None,
) -> MemoryPage:
    """One page of ``kind``'s items; pass ``next_cursor`` back for the next."""
    return list_memory_items(kb or knowledge_base(), kind, limit=limit, cursor=cursor)


def delete(kind: str, item_id: UUID, *, kb: KnowledgeBase | None = None) -> WriteAccepted:
    """Delete item ``item_id`` of ``kind``; poll the request removing its dump file."""
    return delete_memory_item(kb or knowledge_base(), kind, item_id)


def request(request_id: str, *, kb: KnowledgeBase | None = None) -> RequestState:
    """Where queued request ``request_id`` is: ``queued``, ``done`` or ``failed``.

    Raises:
        UnknownRequest: ``request_id`` was never issued on this queue.
    """
    return get_memory_request(kb or knowledge_base(), request_id)


def kinds(*, kb: KnowledgeBase | None = None) -> list[KindSchema]:
    """Every installed kind and its payload's JSON Schema."""
    return list_memory_kinds(kb or knowledge_base())


def warmup(*, kb: KnowledgeBase | None = None) -> WarmupReport:
    """Queue every item in ``warmup.path`` not already stored unchanged.

    Raises:
        WarmupDirectoryMissing: ``warmup.path`` is not a directory, or cannot be listed.
        WarmupDirectoryEmpty: ``warmup.path`` holds no items.
        pydantic.ValidationError: any file or item is bad; nothing is queued.
        WarmupPartiallyQueued: the queue failed partway; the message says whether the run was
            recorded.
    """
    return warmup_memory(kb or knowledge_base())


def warmup_progress(run_id: str, *, kb: KnowledgeBase | None = None) -> WarmupProgress:
    """How far the worker is through warm-up run ``run_id``.

    Raises:
        UnknownWarmupRun: no run ``run_id`` was recorded on this queue.
        StoredItemInvalid: the run's record is not a run, or names a request never issued.
    """
    return get_warmup_progress(kb or knowledge_base(), run_id)


__all__ = [
    "delete",
    "get",
    "items",
    "kinds",
    "knowledge_base",
    "request",
    "reset",
    "search",
    "store",
    "update",
    "warmup",
    "warmup_progress",
]


def __dir__() -> list[str]:
    """Keep `kb.<TAB>` to the things worth calling."""
    return list(__all__)
