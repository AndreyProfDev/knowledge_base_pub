"""CRUD on ``/memory/{kind}``; the body is any JSON object, validated by the operation."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import JsonValue

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import MemoryItem, MemoryPage, WriteAccepted
from tools_knowledge_base.operations import (
    MAX_LIMIT,
    delete_memory_item,
    get_memory_item,
    list_memory_items,
    store_memory,
    update_memory_item,
)

type Payload = Annotated[dict[str, JsonValue], Body()]
# The operation refuses it too; declared here as well so FastAPI's 422 says `query`.
type Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]

_LOCATION: dict[int | str, dict[str, Any]] = {
    status.HTTP_202_ACCEPTED: {
        "headers": {
            "Location": {
                "description": "`/requests/{request_id}`: poll it until `done`.",
                "schema": {"type": "string"},
            }
        }
    }
}
_DELETE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_LOCATION,
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "description": "The item is deleted, but its dump file's removal was not queued.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                    "required": ["detail"],
                }
            }
        },
    },
}


def _accepted(response: Response, accepted: WriteAccepted) -> WriteAccepted:
    """Point ``Location`` at the request's status monitor, as RFC 9110 asks of a 202."""
    url = f"/requests/{accepted.request_id}"
    response.headers["Location"] = url  # pragma: no mutate, equivalent: header names ignore case
    return accepted


def router(kb: KnowledgeBase) -> APIRouter:
    """The ``/memory`` routes, bound to ``kb``."""

    def store(kind: str, payload: Payload, response: Response) -> WriteAccepted:
        """Queue a new item of ``kind``; poll ``Location`` until ``done``."""
        return _accepted(response, store_memory(kb, kind, payload))

    def update(kind: str, item_id: UUID, payload: Payload, response: Response) -> WriteAccepted:
        """Queue ``payload`` replacing item ``item_id``; ``item_id`` answered is the new key's."""
        return _accepted(response, update_memory_item(kb, kind, item_id, payload))

    def get(kind: str, item_id: UUID) -> MemoryItem:
        """Item ``item_id`` of ``kind``."""
        return get_memory_item(kb, kind, item_id)

    def list_items(kind: str, limit: Limit = 50, cursor: UUID | None = None) -> MemoryPage:
        """One page of ``kind``'s items; pass ``next_cursor`` back as ``cursor`` for the next."""
        return list_memory_items(kb, kind, limit=limit, cursor=cursor)

    def delete(kind: str, item_id: UUID, response: Response) -> WriteAccepted:
        """Delete item ``item_id`` at once; poll ``Location``, which removes its dump file."""
        return _accepted(response, delete_memory_item(kb, kind, item_id))

    routes = APIRouter(prefix="/memory", tags=["memory"])
    one, accepted = "/{kind}/{item_id}", status.HTTP_202_ACCEPTED
    add = routes.add_api_route
    post_only = ["POST"]  # pragma: no mutate, equivalent: FastAPI upper-cases route methods
    put_only = ["PUT"]  # pragma: no mutate, equivalent: FastAPI upper-cases route methods
    delete_only = ["DELETE"]  # pragma: no mutate, equivalent: FastAPI upper-cases route methods
    add(
        "/{kind}",
        store,
        methods=post_only,
        status_code=accepted,
        responses=_LOCATION,
        operation_id="store_memory",
        summary="Store memory",
    )
    add(
        one,
        update,
        methods=put_only,
        status_code=accepted,
        responses=_LOCATION,
        operation_id="update_memory_item",
        summary="Update memory item",
    )
    # The two reads pass no `methods`: FastAPI's default is GET.
    add(one, get, operation_id="get_memory_item", summary="Get memory item")
    add(
        "/{kind}",
        list_items,
        operation_id="list_memory_items",
        summary="List memory items",
    )
    add(
        one,
        delete,
        methods=delete_only,
        status_code=accepted,
        responses=_DELETE_RESPONSES,
        operation_id="delete_memory_item",
        summary="Delete memory item",
    )
    return routes
