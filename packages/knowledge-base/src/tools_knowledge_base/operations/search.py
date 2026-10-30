"""Search: embed the query, ask the active collection, validate each hit back."""

from __future__ import annotations

import math

from pydantic_core import PydanticCustomError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import MemoryHit
from tools_knowledge_base.operations.items import memory_item, refuse, require_limit

_BLANK = PydanticCustomError("blank_query", "query must not be blank")


def not_blank(query: str) -> str:
    """``query``, unless ``str.strip`` leaves it empty; usable as an ``AfterValidator``.

    Raises:
        PydanticCustomError: ``blank_query``.
    """
    if not query.strip():
        raise _BLANK
    return query


def search_memory(
    kb: KnowledgeBase,
    query: str,
    *,
    kind: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[MemoryHit]:
    """The items nearest ``query``, best first.

    ``kind`` omitted searches every installed kind; points of a kind no longer installed
    are filtered out in the store, so they never take one of the ``top_k`` places.
    ``top_k`` defaults to ``search.top_k`` and ``min_score`` to the active embedder's floor.

    Raises:
        pydantic.ValidationError: ``query`` is blank, ``top_k`` is outside
            ``1..MAX_LIMIT``, or ``min_score`` is not finite.
        UnknownKind: ``kind`` is set and no installed kind has that name.
        StoredItemInvalid: a hit's stored payload fails its kind's model.
    """
    try:
        _ = not_blank(query)
    except PydanticCustomError as blank:
        refuse("search_memory", "query", query, blank)
    limit = top_k if top_k is not None else kb.settings.search.top_k
    require_limit("search_memory", "top_k", limit)
    if min_score is not None and not math.isfinite(min_score):
        refuse("search_memory", "min_score", min_score, "finite_number")
    if kind is None:
        kinds = kb.kinds.names()
    else:
        kb.kinds.get(kind)
        kinds = [kind]
    if not kinds:
        return []
    hits = kb.store.search(
        kb.embedder.embed_query(query),
        kinds=kinds,
        limit=limit,
        min_score=min_score if min_score is not None else kb.embedder.min_score,
    )
    return [
        MemoryHit(**dict(memory_item(kb.kinds.get(hit.kind), hit)), score=hit.score) for hit in hits
    ]
