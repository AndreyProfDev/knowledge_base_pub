"""``/warmup``: load the configured warm-up files, then follow the run's writes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.constants import REF_PREFIX
from pydantic import ValidationError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import WarmupProgress, WarmupReport
from tools_knowledge_base.operations import get_warmup_progress, warmup_memory

_DETAIL = {
    "application/json": {
        "schema": {
            "type": "object",
            "properties": {"detail": {"type": "string"}},
            "required": ["detail"],
        }
    }
}
_WARMUP_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "description": "The warm-up directory is missing, unreadable or holds no items.",
        "content": _DETAIL,
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "A bad file or item; `loc` is (file, kind, index, ...). Nothing queued.",
        "content": {"application/json": {"schema": {"$ref": f"{REF_PREFIX}HTTPValidationError"}}},
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "The queue failed partway; `detail` names the run and what failed.",
        "content": _DETAIL,
    },
}
_PROGRESS_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "No run `run_id` was recorded.", "content": _DETAIL},
}


def router(kb: KnowledgeBase) -> APIRouter:
    """The ``/warmup`` routes, bound to ``kb``."""

    def warmup() -> WarmupReport:
        """Queue every item not stored unchanged. Any bad file or item: 422, nothing queued."""
        try:
            return warmup_memory(kb)
        except ValidationError as exc:
            # Body-less, so ``_invalid`` would make it a 500; ``loc`` is (file, kind, index, ...).
            # Its errors are all warm-up's own PydanticCustomError, which has no url to include.
            errors = exc.errors(include_url=False)  # pragma: no mutate, equivalent: url-less errors
            raise RequestValidationError(errors) from exc

    def progress(run_id: str) -> WarmupProgress:
        """A request between retries counts as pending: a failing item fails after ~150 s."""
        return get_warmup_progress(kb, run_id)

    routes = APIRouter(tags=["warmup"])
    post_only = ["POST"]  # pragma: no mutate, equivalent: FastAPI upper-cases route methods
    routes.add_api_route(
        "/warmup",
        warmup,
        methods=post_only,
        responses=_WARMUP_ERRORS,
        operation_id="warmup_memory",
        summary="Warmup memory",
    )
    # No `methods`: FastAPI's default is GET.
    routes.add_api_route(
        "/warmup/{run_id}",
        progress,
        responses=_PROGRESS_ERRORS,
        operation_id="get_warmup_progress",
        summary="Get warmup progress",
    )
    return routes
