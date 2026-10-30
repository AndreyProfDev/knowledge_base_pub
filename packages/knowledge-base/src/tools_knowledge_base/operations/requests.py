"""Request status: where a queued write is, read off huey's result store."""

from __future__ import annotations

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import RequestState
from tools_knowledge_base.queue import request_status


def get_memory_request(kb: KnowledgeBase, request_id: str) -> RequestState:
    """``done`` once the worker wrote it, ``failed`` (with the error) after its last retry.

    Anything else this queue issued reads ``queued``.

    Raises:
        UnknownRequest: ``request_id`` was never issued on this queue.
    """
    status, error = request_status(kb.huey, request_id)
    return RequestState(request_id=request_id, status=status, error=error)
