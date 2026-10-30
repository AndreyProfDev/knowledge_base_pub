"""``knowledge``: an atomic fact about the user, keyed and embedded by its content."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KnowledgePayload(BaseModel):
    """One fact; ``content`` is its identity, so rewording it makes a new item."""

    category: Literal["fact", "preference", "constraint", "goal"]
    content: str = Field(json_schema_extra={"x-long-text": True})


def _knowledge(payload: BaseModel) -> KnowledgePayload:
    if not isinstance(payload, KnowledgePayload):
        msg = f"knowledge kind got a {type(payload).__name__} payload"
        raise TypeError(msg)
    return payload


class KnowledgeKind:
    """The ``knowledge`` ``MemoryKind``: upsert by ``content``."""

    def __init__(self) -> None:
        self.name = "knowledge"
        self.payload_model: type[BaseModel] = KnowledgePayload
        self.counted_over = "content"
        self.oversize_hint = (
            "Store one fact per item: split it into several store_knowledge calls, "
            "each under the limit."
        )

    def key(self, payload: BaseModel) -> str:
        """The content: equal text addresses the same point."""
        return _knowledge(payload).content

    def embed_text(self, payload: BaseModel) -> str:
        """The content alone."""
        return _knowledge(payload).content

    def render(self, payload: BaseModel) -> str:
        """``[category] content``."""
        knowledge = _knowledge(payload)
        return f"[{knowledge.category}] {knowledge.content}"
