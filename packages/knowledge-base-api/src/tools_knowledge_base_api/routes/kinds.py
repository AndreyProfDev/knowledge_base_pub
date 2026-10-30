"""``/kinds``: the installed kinds and their payload schemas, for the UI's forms."""

from __future__ import annotations

from fastapi import APIRouter

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import KindSchema
from tools_knowledge_base.operations import list_memory_kinds


def router(kb: KnowledgeBase) -> APIRouter:
    """The ``/kinds`` route, bound to ``kb``."""

    def kinds() -> list[KindSchema]:
        """Every installed kind with its payload's JSON Schema."""
        return list_memory_kinds(kb)

    routes = APIRouter(tags=["kinds"])
    # No `methods`: FastAPI's default is GET.
    routes.add_api_route(
        "/kinds", kinds, operation_id="list_memory_kinds", summary="List memory kinds"
    )
    return routes
