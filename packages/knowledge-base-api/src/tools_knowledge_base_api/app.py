"""``create_app``: the REST surface over one ``KnowledgeBase``; ``main`` serves it."""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib.metadata import version
from typing import Protocol

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import request_validation_exception_handler as fastapi_422
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import ValidationError

from knowledge_base_config import environment_from_env
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.configs.settings import get_settings as get_kb_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import (
    DumpRemovalNotQueued,
    ItemNotFound,
    UnknownKind,
    UnknownRequest,
    UnknownWarmupRun,
    WarmupDirectoryEmpty,
    WarmupDirectoryMissing,
    WarmupPartiallyQueued,
)
from tools_knowledge_base.readiness import require_embedder_key, require_kinds
from tools_knowledge_base_api.configs.settings import KnowledgeBaseApiSettings, get_settings
from tools_knowledge_base_api.routes import kinds, memory, requests, search, warmup

logger = logging.getLogger(__name__)

_NOT_FOUND = (
    UnknownKind,
    ItemNotFound,
    UnknownRequest,
    UnknownWarmupRun,
    WarmupDirectoryMissing,
    WarmupDirectoryEmpty,
)


async def _not_found(_request: Request, exc: Exception) -> Response:
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)


async def _unavailable(_request: Request, exc: WarmupPartiallyQueued) -> Response:
    """The queue failed partway; ``detail`` names the run and whether it was recorded."""
    logger.error("warm-up run %s failed on the queue", exc.run_id, exc_info=exc)
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


async def _not_queued(_request: Request, exc: DumpRemovalNotQueued) -> Response:
    """The item is gone; ``detail`` says so, so the client does not report the delete failed."""
    logger.error("delete succeeded but its dump removal was not queued", exc_info=exc)
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


async def _request_invalid(request: Request, exc: RequestValidationError) -> Response:
    """FastAPI's own 422, without ``input``: a ``NaN`` body would fail the JSON render as a 500."""
    errors = [
        {key: value for key, value in error.items() if key != "input"} for error in exc.errors()
    ]
    refused = RequestValidationError(errors)
    return await fastapi_422(request, refused)  # pragma: no mutate, equivalent: request unused


async def _invalid(request: Request, exc: ValidationError) -> Response:
    """An operation's ``ValidationError`` as FastAPI's own 422, on a route that takes a body.

    The routes refuse every query parameter the operation would, so one reaching here on a
    body-less route is a server fault (e.g. ``search.top_k`` out of range): re-raised, a 500.
    """
    route = request.scope.get("route")
    if not isinstance(route, APIRoute) or route.body_field is None:
        raise exc
    errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors(include_url=False)]
    # _request_invalid hands request on only to FastAPI's handler, which never reads it.
    refused = RequestValidationError(errors)
    return await _request_invalid(request, refused)  # pragma: no mutate, equivalent: request unused


def create_app(kb: KnowledgeBase, settings: KnowledgeBaseApiSettings | None = None) -> FastAPI:
    """The app over ``kb``, answering only the ``Host`` names ``settings`` allow."""
    settings = settings or get_settings()
    # Distribution names are matched case-blind.
    release = version("tools-knowledge-base-api")  # pragma: no mutate, equivalent: case-blind
    # Equivalent only while the package is at 0.1.0, FastAPI's default: dropping `version`
    # then changes nothing. On a version bump, delete the pragma and test the version.
    app = FastAPI(title="Knowledge Base", version=release)  # pragma: no mutate, equivalent: 0.1.0
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    for error in _NOT_FOUND:
        app.add_exception_handler(error, _not_found)
    app.exception_handler(WarmupPartiallyQueued)(_unavailable)
    app.exception_handler(DumpRemovalNotQueued)(_not_queued)
    app.exception_handler(RequestValidationError)(_request_invalid)
    app.exception_handler(ValidationError)(_invalid)
    for module in (memory, search, requests, kinds, warmup):
        app.include_router(module.router(kb))
    return app


class Serve(Protocol):
    """``uvicorn.run``'s shape, as ``main`` calls it."""

    def __call__(self, app: FastAPI, /, *, host: str, port: int) -> None:
        """Serve ``app`` on ``host:port`` until stopped."""


def main(
    *,
    kb_settings: KnowledgeBaseSettings | None = None,
    open_kb: Callable[[KnowledgeBaseSettings], KnowledgeBase] = open_knowledge_base,
    run: Serve = uvicorn.run,
) -> None:
    """Open the knowledge base ``TOOLS_ENV`` configures and serve it on ``host:port``.

    Raises:
        KnowledgeBaseError: the active embedder has no API key, or the kb has no
            memory kind; nothing is served then, as the MCP server refuses to start.
    """
    settings = get_settings()
    kb_settings = kb_settings or get_kb_settings(environment_from_env())
    require_embedder_key(kb_settings)
    kb = open_kb(kb_settings)
    require_kinds(kb)
    app = create_app(kb, settings)  # pragma: no mutate, equivalent: the default is get_settings()
    run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
