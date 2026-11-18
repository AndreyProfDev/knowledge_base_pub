"""Request status: where a queued write is, read off this process's write queue."""

from __future__ import annotations

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import RequestState


def get_memory_request(kb: KnowledgeBase, request_id: str) -> RequestState:
    """``done`` once the write ran, ``failed`` (with the error) after its last attempt.

    Anything else this process issued reads ``queued``.

    Raises:
        UnknownRequest: this process never issued ``request_id``.
    """
    status, error = kb.writes.status(request_id)
    return RequestState(request_id=request_id, status=status, error=error)
