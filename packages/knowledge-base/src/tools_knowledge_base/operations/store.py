"""Store and edit: validated at request time, then queued for the worker to embed."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid5

from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.models import WriteAccepted
from tools_knowledge_base.operations.items import stored_item
from tools_knowledge_base.queue import enqueue_write

KB_NAMESPACE = UUID("6f1c3a52-9d4e-4b7a-8c2f-0e5d7b9a1c34")
"""Item ids are ``uuid5(KB_NAMESPACE, f"{kind}:{key}")``: one key, one point."""


def _embed_text_rejected(
    kind: MemoryKind, payload: Mapping[str, object], error: PydanticCustomError
) -> NoReturn:
    details: InitErrorDetails = {"type": error, "input": dict(payload)}
    raise ValidationError.from_exception_data(kind.payload_model.__name__, [details])


def _rejected_reason(kind: MemoryKind, payload: Mapping[str, object], reason: str) -> NoReturn:
    error = PydanticCustomError("embed_text_rejected", "embed text {reason}", {"reason": reason})
    _embed_text_rejected(kind, payload, error)


def _too_long(
    kb: KnowledgeBase, kind: MemoryKind, payload: Mapping[str, object], text: str
) -> None:
    cap = kb.settings.item_limits.for_kind(kind.name)
    if len(text) <= cap:
        return
    error = PydanticCustomError(
        "item_too_long",
        "{kind} item is {length} characters; the {kind} limit is {cap} "
        "(counted over {counted_over}). {hint}",
        {
            "kind": kind.name,
            "length": len(text),
            "cap": cap,
            "counted_over": kind.counted_over,
            "hint": kind.oversize_hint,
        },
    )
    _embed_text_rejected(kind, payload, error)


def validate_payload(
    kb: KnowledgeBase, kind: str, payload: Mapping[str, object]
) -> tuple[MemoryKind, BaseModel]:
    """``payload`` as ``kind``'s model, its embed text within the character and token caps.

    Raises:
        UnknownKind: no installed kind is called ``kind``.
        pydantic.ValidationError: a bad payload, or an empty or over-cap embed text.
    """
    memory_kind = kb.kinds.get(kind)
    model = memory_kind.payload_model.model_validate(payload)
    text = memory_kind.embed_text(model)
    if not text.strip():
        _rejected_reason(memory_kind, payload, "is empty")
    _too_long(kb, memory_kind, payload, text)
    tokens = kb.embedder.count_tokens(text)
    if tokens > kb.embedder.max_input_tokens:
        _rejected_reason(
            memory_kind,
            payload,
            f"is {tokens} tokens, over the embedder's {kb.embedder.max_input_tokens}",
        )
    return memory_kind, model


def item_id_of(kind: MemoryKind, model: BaseModel) -> UUID:
    """The id ``model`` is stored under."""
    return uuid5(KB_NAMESPACE, f"{kind.name}:{kind.key(model)}")


def enqueue_item(
    kb: KnowledgeBase, kind: MemoryKind, model: BaseModel, replaces: UUID | None
) -> WriteAccepted:
    """Queue ``model`` for the worker to embed and write; ``model`` is already validated."""
    item_id = item_id_of(kind, model)
    request_id = enqueue_write(
        kb.write_memory,
        kind=kind.name,
        item_id=item_id,
        payload=model.model_dump(mode="json"),
        updated_at=datetime.now(UTC),
        replaces=replaces,
    )
    return WriteAccepted(request_id=request_id, item_id=item_id, status="queued")


def store_memory(kb: KnowledgeBase, kind: str, payload: Mapping[str, object]) -> WriteAccepted:
    """Queue ``payload`` as an item of ``kind``; re-storing its key updates in place.

    Raises:
        UnknownKind: no installed kind is called ``kind``.
        pydantic.ValidationError: a bad payload, or an empty or over-limit embed text.
        KnowledgeBaseError: the active embedder has no key, so the write is refused.
    """
    memory_kind, model = validate_payload(kb, kind, payload)
    return enqueue_item(kb, memory_kind, model, replaces=None)


def update_memory_item(
    kb: KnowledgeBase, kind: str, item_id: UUID, payload: Mapping[str, object]
) -> WriteAccepted:
    """Queue ``payload`` replacing item ``item_id``; ``item_id`` in the result is the new key's.

    Raises:
        UnknownKind: no installed kind is called ``kind``.
        pydantic.ValidationError: as ``store_memory``.
        KnowledgeBaseError: as ``store_memory``, for a keyless embedder.
        ItemNotFound: no item of ``kind`` has ``item_id``.
    """
    memory_kind, model = validate_payload(kb, kind, payload)
    stored_item(kb, kind, item_id)
    return enqueue_item(kb, memory_kind, model, replaces=item_id)
