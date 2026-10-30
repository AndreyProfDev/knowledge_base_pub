"""``/requests/{request_id}``: where a queued write is."""

from __future__ import annotations

from fastapi import APIRouter

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import RequestState
from tools_knowledge_base.operations import get_memory_request


def router(kb: KnowledgeBase) -> APIRouter:
    """The ``/requests`` route, bound to ``kb``."""

    def request(request_id: str) -> RequestState:
        """``queued`` until the worker has run the request, then ``done`` or ``failed``."""
        return get_memory_request(kb, request_id)

    routes = APIRouter(tags=["requests"])
    # No `methods`: FastAPI's default is GET.
    routes.add_api_route(
        "/requests/{request_id}",
        request,
        operation_id="get_memory_request",
        summary="Get memory request",
    )
    return routes
