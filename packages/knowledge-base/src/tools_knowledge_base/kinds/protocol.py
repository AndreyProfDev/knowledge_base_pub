"""``MemoryKind`` — everything a kind supplies for the shared flow to handle it."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class MemoryKind(Protocol):
    """A memory kind; core does every store, edit, get, list and delete itself."""

    name: str
    payload_model: type[BaseModel]
    counted_over: str
    """What ``embed_text`` is made of, as the character cap's error and tool text name it."""
    oversize_hint: str
    """What a caller over the character cap should do instead."""

    def key(self, payload: BaseModel) -> str:
        """Natural key; equal keys address the same point."""
        ...

    def embed_text(self, payload: BaseModel) -> str:
        """The text embedded for this payload."""
        ...

    def render(self, payload: BaseModel) -> str:
        """Human-readable form for CLI output."""
        ...
