"""``/search``: semantic search over every kind, or one."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AfterValidator

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import MemoryHit
from tools_knowledge_base.operations import MAX_LIMIT, not_blank, search_memory

# The operation refuses these too; declared here as well so FastAPI's 422 says `query`.
type Q = Annotated[str, Query(), AfterValidator(not_blank)]
type TopK = Annotated[int | None, Query(ge=1, le=MAX_LIMIT)]
type MinScore = Annotated[float | None, Query(allow_inf_nan=False)]


def router(kb: KnowledgeBase) -> APIRouter:
    """The ``/search`` route, bound to ``kb``."""

    def search(
        q: Q, kind: str | None = None, top_k: TopK = None, min_score: MinScore = None
    ) -> list[MemoryHit]:
        """Hits for ``q``, best first; ``top_k`` and ``min_score`` default to the settings'."""
        return search_memory(kb, q, kind=kind, top_k=top_k, min_score=min_score)

    routes = APIRouter(tags=["search"])
    # No `methods`: FastAPI's default is GET.
    routes.add_api_route("/search", search, operation_id="search_memory", summary="Search memory")
    return routes
