"""A throwaway memory kind: core is tested against it, never a shipped kind."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FakePayload(BaseModel):
    """One fake item; ``title`` is its identity."""

    # An argument meant for the item id, left in the payload, fails instead of vanishing.
    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="What the item is called.", max_length=40)
    tags: list[str]


def _payload(payload: BaseModel) -> FakePayload:
    assert isinstance(payload, FakePayload)
    return payload


class FakeKind:
    """Keyed by ``title``; embeds the title and its tags."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.payload_model: type[BaseModel] = FakePayload
        self.counted_over = "title and tags"
        self.oversize_hint = "Split the tags across several fake items."

    def key(self, payload: BaseModel) -> str:
        return _payload(payload).title

    def embed_text(self, payload: BaseModel) -> str:
        fake = _payload(payload)
        return " ".join([fake.title, *fake.tags])

    def render(self, payload: BaseModel) -> str:
        fake = _payload(payload)
        return f"{fake.title} [{', '.join(fake.tags)}]"
