"""The queued jobs: ``write_item`` (embed, upsert, retire, dump) and ``forget_item``.

A crash between upsert and dump leaves the item with no file until its next write.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, JsonValue, ValidationError

from tools_knowledge_base.configs.settings import WarmupSettings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import UnknownKind, WriteRefused
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.warmup_dump import (
    dump_file_name,
    dump_holds,
    sync_dump,
    upsert_and_sync_dump,
)

RETRY_DELAYS = (1.0, 2.0)
"""Seconds slept after a failed attempt; one more attempt follows each, so three in all."""


def _validated(
    kinds: KindRegistry, kind: str, payload: dict[str, JsonValue]
) -> tuple[MemoryKind, BaseModel]:
    try:
        memory_kind = kinds.get(kind)
    except UnknownKind as exc:
        # Its package was uninstalled since the submit: no retry can succeed.
        raise WriteRefused(str(exc)) from exc
    try:
        return memory_kind, memory_kind.payload_model.model_validate(payload)
    except ValidationError as exc:
        # The kind's model changed since the submit: no retry can succeed either.
        raise WriteRefused(str(exc)) from exc


def _refuse_stale(
    warmup: WarmupSettings,
    kind: str,
    gone: UUID | None,
    written: tuple[UUID, dict[str, JsonValue]] | None = None,
) -> None:
    # With the flag off a dump file left from when it was on is never updated, yet it
    # still wins at warm-up: a deleted, renamed or edited item would come back. Allowed:
    # no file for ``gone`` (the retired or forgotten id), and for the written id either no
    # file or one holding exactly this payload (warm-up rebuilding from the dump).
    if warmup.dump:
        return
    checks: list[tuple[UUID, dict[str, JsonValue] | None]] = [] if gone is None else [(gone, None)]
    if written is not None:
        checks.append(written)
    for item_id, payload in checks:
        path = warmup.path / dump_file_name(kind, item_id)
        if not path.exists():
            continue
        if payload is None or not dump_holds(warmup.path, kind, item_id, payload):
            msg = (
                f"dump file {path} holds {kind} item {item_id}; warmup.dump is off;"
                " warm-up would restore this copy"
            )
            raise WriteRefused(msg)


def write_item(
    kb: KnowledgeBase,
    *,
    kind: str,
    item_id: UUID,
    payload: dict[str, JsonValue],
    updated_at: datetime,
    replaces: UUID | None,
) -> None:
    """Embed and upsert the item, retire ``replaces``, sync the dump files.

    A transient error is retried after each of ``RETRY_DELAYS`` (slept through
    ``kb.sleep``); the last attempt's error propagates. A retry whose upsert already
    landed skips the embed and upsert, else a delete since then would be undone.

    Raises:
        WriteRefused: no retry can fix it: unknown kind, payload no longer valid, or
            a stale dump file with ``warmup.dump`` off.
    """
    warmup = kb.settings.warmup
    memory_kind, model = _validated(kb.kinds, kind, payload)
    retired = None if replaces is None or replaces == item_id else replaces
    # Before the store, so a refused write never lands.
    _refuse_stale(warmup, kind, retired, (item_id, model.model_dump(mode="json")))
    root = warmup.path if warmup.dump else None
    landed = False  # pragma: no mutate, equivalent: None is falsy

    def mark_landed() -> None:
        nonlocal landed
        landed = True

    def attempt() -> None:
        if not landed:
            [vector] = kb.embedder.embed_documents([memory_kind.embed_text(model)])
            point = Point(
                id=item_id, kind=kind, updated_at=updated_at, payload=payload, vector=vector
            )
            upsert_and_sync_dump(kb.store, root, kb.kinds, kind, [point], mark_landed)
        elif root is not None:
            sync_dump(kb.store, root, kb.kinds, kind, item_id)
        if retired is not None:
            # Upsert before delete: a failure between them leaves both points, never
            # neither. The new file is already written, so the old one goes last too.
            kb.store.delete([retired], older_than=updated_at)
            if root is not None:
                sync_dump(kb.store, root, kb.kinds, kind, retired)

    for delay in RETRY_DELAYS:
        try:
            attempt()
        except Exception:
            kb.sleep(delay)
        else:
            return
    attempt()


def forget_item(kb: KnowledgeBase, kind: str, item_id: UUID) -> None:
    """Remove item ``item_id``'s dump file, once the store no longer holds it.

    Raises:
        WriteRefused: ``warmup.dump`` is off and the file exists, so warm-up would restore it.
    """
    warmup = kb.settings.warmup
    _refuse_stale(warmup, kind, item_id)
    if warmup.dump:
        sync_dump(kb.store, warmup.path, kb.kinds, kind, item_id)
