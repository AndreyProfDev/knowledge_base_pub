"""Get, list and delete: one store call each, scoped to one kind."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import DumpRemovalNotQueued, ItemNotFound, stored_as
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.limits import MAX_LIMIT
from tools_knowledge_base.models import MemoryItem, MemoryPage, WriteAccepted
from tools_knowledge_base.store.protocol import Item
from tools_knowledge_base.tasks import enqueue_forget
from tools_knowledge_base.warmup_dump import dump_file_name


def memory_item(kind: MemoryKind, item: Item) -> MemoryItem:
    """``item`` with its payload validated back into ``kind``'s model.

    Raises:
        StoredItemInvalid: the stored payload fails the model. Not ``ValidationError``,
            which callers read as a refusal of their own input.
    """
    where = f"stored {kind.name} item {item.id} fails its payload model"
    payload = stored_as(kind.payload_model, item.payload, where)
    return MemoryItem(id=item.id, kind=item.kind, updated_at=item.updated_at, payload=payload)


def refuse(
    operation: str,
    name: str,
    value: object,
    error_type: str | PydanticCustomError,
    ctx: dict[str, object] | None = None,
) -> NoReturn:
    """Raise pydantic's ``ValidationError``, the one caller-input error, at ``loc`` ``(name,)``."""
    details: InitErrorDetails = {"type": error_type, "loc": (name,), "input": value}
    if ctx is not None:
        details["ctx"] = ctx
    raise ValidationError.from_exception_data(operation, [details])


def require_limit(operation: str, name: str, value: int) -> None:
    """Refuse ``value`` outside ``1..MAX_LIMIT``.

    Raises:
        pydantic.ValidationError: ``value`` is below 1 or above ``MAX_LIMIT``.
    """
    if value < 1:
        refuse(operation, name, value, "greater_than_equal", {"ge": 1})
    if value > MAX_LIMIT:
        refuse(operation, name, value, "less_than_equal", {"le": MAX_LIMIT})


def stored_item(kb: KnowledgeBase, kind: str, item_id: UUID) -> Item:
    """The stored item ``item_id`` of ``kind``.

    Raises:
        ItemNotFound: absent, or an item of another kind.
    """
    for item in kb.store.get([item_id]):
        if item.kind == kind:
            return item
    msg = f"no {kind} item has id {item_id}"
    raise ItemNotFound(msg)


def get_memory_item(kb: KnowledgeBase, kind: str, item_id: UUID) -> MemoryItem:
    """Item ``item_id`` of ``kind``.

    Raises:
        UnknownKind: no installed kind is called ``kind``.
        ItemNotFound: no item of ``kind`` has ``item_id``.
        StoredItemInvalid: its stored payload fails ``kind``'s model.
    """
    memory_kind = kb.kinds.get(kind)
    return memory_item(memory_kind, stored_item(kb, kind, item_id))


def list_memory_items(
    kb: KnowledgeBase, kind: str, *, limit: int = 50, cursor: UUID | None = None
) -> MemoryPage:
    """One page of ``kind``'s items from ``cursor``; pass ``next_cursor`` for the next.

    Raises:
        pydantic.ValidationError: ``limit`` is outside ``1..MAX_LIMIT``.
        UnknownKind: no installed kind is called ``kind``.
        StoredItemInvalid: a stored payload on the page fails ``kind``'s model.
    """
    require_limit("list_memory_items", "limit", limit)
    memory_kind = kb.kinds.get(kind)
    items, next_cursor = kb.store.list(kind, limit=limit, cursor=cursor)
    return MemoryPage(
        items=[memory_item(memory_kind, item) for item in items], next_cursor=next_cursor
    )


def delete_memory_item(kb: KnowledgeBase, kind: str, item_id: UUID) -> WriteAccepted:
    """Delete item ``item_id`` of ``kind``; returns the request removing its dump file.

    Only its ``kind`` is read, so a corrupt item goes too. The store delete is
    immediate; the dump file is removed by the worker, the one process mounting
    ``warmup.path`` writable. Poll the request: until it is ``done`` the file can
    bring the item back at the next warm-up.

    Raises:
        UnknownKind: no installed kind is called ``kind``.
        ItemNotFound: no item of ``kind`` has ``item_id``.
        DumpRemovalNotQueued: the item is deleted, but queueing the removal failed.
    """
    kb.kinds.get(kind)
    if kb.store.kind_of(item_id) != kind:
        msg = f"no {kind} item has id {item_id}"
        raise ItemNotFound(msg)
    # Delete before enqueue: the worker skips the removal while the item is still stored.
    kb.store.delete([item_id])
    try:
        request_id = enqueue_forget(kb.forget_memory, kind=kind, item_id=item_id)
    except Exception as exc:
        msg = (
            f"{kind} item {item_id} deleted; dump file {dump_file_name(kind, item_id)} not"
            f" scheduled for removal: {type(exc).__name__}: {exc}"
        )
        raise DumpRemovalNotQueued(msg) from exc
    return WriteAccepted(request_id=request_id, item_id=item_id, status="queued")
