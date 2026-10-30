"""The worker's huey tasks: ``write_memory`` (embed, upsert, retire, dump) and ``forget_memory``.

The dump runs only on the worker, so ``mcp-server`` and ``knowledge-api`` mount
``warmup.path`` read-only. A worker crash between upsert and dump leaves the item with
no file until its next write.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

from huey import Huey  # pyright: ignore[reportMissingTypeStubs]
from huey.api import Task, TaskWrapper  # pyright: ignore[reportMissingTypeStubs]
from huey.exceptions import CancelExecution  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel, JsonValue, ValidationError

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, WarmupSettings
from tools_knowledge_base.embeddings import Embedder
from tools_knowledge_base.errors import UnknownKind
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.queue import issue_request
from tools_knowledge_base.store.protocol import Point, VectorStore
from tools_knowledge_base.warmup_dump import dump_file_name, dump_holds, remove_dump, write_dump


class Tasks(NamedTuple):
    """What ``register_tasks`` registered."""

    write_memory: TaskWrapper
    forget_memory: TaskWrapper


def _validated(
    kinds: KindRegistry, kind: str, payload: dict[str, JsonValue]
) -> tuple[MemoryKind, BaseModel]:
    try:
        memory_kind = kinds.get(kind)
    except UnknownKind as exc:
        # Its package was uninstalled since the enqueue: no retry can succeed.
        raise CancelExecution(False, str(exc)) from exc  # noqa: FBT003 - huey's signature
    try:
        return memory_kind, memory_kind.payload_model.model_validate(payload)
    except ValidationError as exc:
        # The kind's model changed since the enqueue: no retry can succeed either.
        raise CancelExecution(False, str(exc)) from exc  # noqa: FBT003 - huey's signature


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
            raise CancelExecution(False, msg)  # noqa: FBT003 - huey's signature


def register_tasks(
    huey: Huey,
    *,
    settings: KnowledgeBaseSettings,
    store: VectorStore,
    embedder: Embedder,
    kinds: KindRegistry,
) -> Tasks:
    """Register both tasks on ``huey``, over this process's store, embedder and kinds.

    Once per ``huey`` instance: huey's registry raises ``ValueError`` on a second.
    A dump failure raises ``WarmupDumpFailed``, so huey retries; the retry skips the
    landed upsert and re-syncs the files to the store.
    """
    queue = settings.queue
    warmup = settings.warmup

    def task(func: Callable[..., str], *, context: bool = False) -> TaskWrapper:
        # huey keys a queued message on ``func.__module__``; messages queued before the
        # tasks moved here from ``queue`` carry that key.
        func.__module__ = "tools_knowledge_base.queue"
        return huey.task(  # pyright: ignore[reportUnknownMemberType]
            retries=queue.retries,
            retry_delay=queue.retry_delay_seconds,
            retry_backoff=queue.retry_backoff,  # pyright: ignore[reportArgumentType] - int-defaulted
            context=context,
        )(func)

    def write_memory(
        kind: str,
        item_id: str,
        payload: dict[str, JsonValue],
        updated_at: str,
        replaces: str | None = None,
        *,
        task: Task,
    ) -> str:
        memory_kind, model = _validated(kinds, kind, payload)
        written_id = UUID(item_id)
        retired = None if replaces is None or replaces == item_id else UUID(replaces)
        # Before the store, so a refused write never lands.
        _refuse_stale(warmup, kind, retired, (written_id, model.model_dump(mode="json")))
        written_at = datetime.fromisoformat(updated_at)
        # huey keeps ``task.id`` across retries. Once the upsert landed a retry skips it:
        # a delete since then would otherwise be undone. A SIGKILL after ``put`` or a revoke
        # between retries leaks the key: SqliteHuey's ``put_if_empty`` takes no TTL.
        landed = f"landed:{task.id}"  # pyright: ignore[reportUnknownMemberType]
        try:
            if huey.get(landed, peek=True) is None:  # pyright: ignore[reportUnknownMemberType]
                [vector] = embedder.embed_documents([memory_kind.embed_text(model)])
                point = Point(
                    id=written_id, kind=kind, updated_at=written_at, payload=payload, vector=vector
                )
                store.upsert([point])
                huey.put(landed, True)  # noqa: FBT003 - a marker  # pyright: ignore[reportUnknownMemberType]  # pragma: no mutate, equivalent: True->False, as the retry reads only whether the key is set
            # Upsert before delete: a failure between them leaves both points, never neither.
            if retired is not None:
                store.delete([retired], older_than=written_at)
            if warmup.dump:
                # After the store, so a write that never lands is never dumped; the new
                # file before the old one goes, so a failure leaves both, never neither.
                for synced in (written_id, retired):
                    _sync_dump(store, warmup.path, kinds, kind, synced)
        except Exception as exc:
            _drop_marker_unless_retried(huey, landed, task, exc)
            raise
        huey.get(landed)  # pyright: ignore[reportUnknownMemberType] - pops the marker
        return item_id

    @task
    def forget_memory(kind: str, item_id: str) -> str:
        # The worker's own flag decides: it is the process that writes the dump.
        _refuse_stale(warmup, kind, UUID(item_id))
        if warmup.dump:
            _sync_dump(store, warmup.path, kinds, kind, UUID(item_id))
        return item_id

    return Tasks(write_memory=task(write_memory, context=True), forget_memory=forget_memory)


def _drop_marker_unless_retried(huey: Huey, landed: str, task: Task, exc: Exception) -> None:
    # Mirrors huey 3.4's ``Huey._execute``: with no retry to read it, the marker goes.
    retries = bool(task.retries)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    if isinstance(exc, CancelExecution):
        retried = retries if exc.retry is None else bool(exc.retry)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    else:
        retried = retries
    if not retried:
        huey.get(landed)  # pyright: ignore[reportUnknownMemberType] - pops the marker


def _sync_dump(
    store: VectorStore, root: Path, kinds: KindRegistry, kind: str, item_id: UUID | None
) -> None:
    # The one dump rule: the file mirrors the store's copy now, or is absent with it. Not
    # the task's payload: an older write the store refused, or an item deleted since, would
    # be restored. Idempotent, so a retry or a forget in any order converges.
    if item_id is None:
        return
    held = [item for item in store.get([item_id]) if item.kind == kind]
    if not held:
        remove_dump(root, kind, item_id)
        return
    _, model = _validated(kinds, kind, held[0].payload)
    write_dump(root, kind, item_id, model.model_dump(mode="json"))


def enqueue_forget(forget_memory: TaskWrapper, *, kind: str, item_id: UUID) -> str:
    """Queue the removal of item ``item_id``'s dump file; returns its request id.

    Kept if the item is stored again. With the worker's ``warmup.dump`` off the
    request fails if the file exists, since warm-up would restore it.
    """
    return issue_request(forget_memory, kind, str(item_id))
