"""The huey write queue; its tasks are in ``tasks``.

huey ships no type information, so every call into it lives here or in ``tasks``.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal, NamedTuple
from uuid import UUID

from huey import Huey, MemoryHuey, SqliteHuey  # pyright: ignore[reportMissingTypeStubs]
from huey.api import Result, TaskWrapper  # pyright: ignore[reportMissingTypeStubs]
from huey.exceptions import TaskException  # pyright: ignore[reportMissingTypeStubs]
from huey.signals import (  # pyright: ignore[reportMissingTypeStubs]
    SIGNAL_COMPLETE,
    SIGNAL_INTERRUPTED,
)
from pydantic import JsonValue

from tools_knowledge_base.configs.settings import QueueSettings
from tools_knowledge_base.errors import StoredItemInvalid, UnknownRequest

IN_MEMORY = ":memory:"
_HUEY_NAME = "knowledge-base"


def make_huey(config: QueueSettings) -> Huey:
    """The queue file at ``config.path``, its directory created; ``":memory:"`` is in-process.

    ``store_intermediate_errors=False``: a write between retries reads ``queued``, not
    ``failed``; only the last attempt's error becomes the request's result.
    """
    if config.path == IN_MEMORY:
        # SqliteStorage closes the connection that created its tables, and an in-memory
        # SQLite database dies with its connection.
        return MemoryHuey(_HUEY_NAME, store_intermediate_errors=False)
    Path(config.path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteHuey(
        _HUEY_NAME,
        filename=config.path,
        timeout=config.timeout_seconds,
        store_intermediate_errors=False,
    )


def enqueue_write(
    write_memory: TaskWrapper,
    *,
    kind: str,
    item_id: UUID,
    payload: dict[str, JsonValue],
    updated_at: datetime,
    replaces: UUID | None,
) -> str:
    """Queue one ``write_memory``; returns its request id."""
    return issue_request(
        write_memory,
        kind,
        str(item_id),
        payload,
        updated_at.isoformat(),
        None if replaces is None else str(replaces),
    )


def issue_request(task: TaskWrapper, *args: JsonValue) -> str:
    """Queue ``task(*args)``; returns its request id.

    The id is recorded, so its status can tell a queued request from one never issued.
    The task must return non-``None``: huey stores no ``None`` result, so it would read
    ``queued`` forever.
    """
    result: Result = task(*args)  # pyright: ignore[reportUnknownVariableType]
    request_id = str(result.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    huey: Huey = task.huey
    huey.put(_issued_key(request_id), True)  # noqa: FBT003 - a marker; the value is never read  # pyright: ignore[reportUnknownMemberType]  # pragma: no mutate, equivalent: True->False, as request_status reads only whether the key is set
    return request_id


def _issued_key(request_id: str) -> str:
    return f"issued:{request_id}"


def put_value(huey: Huey, key: str, value: str) -> None:
    """Keep ``value`` under ``key`` in huey's key-value storage, beside the results."""
    huey.put(key, value)  # pyright: ignore[reportUnknownMemberType]


def peek_value(huey: Huey, key: str) -> str | None:
    """The value ``put_value`` kept under ``key``, left in place; ``None`` if there is none.

    Raises:
        StoredItemInvalid: ``key`` holds something other than a string.
    """
    value: object = huey.get(key, peek=True)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if value is None or isinstance(value, str):
        return value
    msg = f"key {key!r} holds {type(value).__name__}, not a string"  # pyright: ignore[reportUnknownArgumentType]
    raise StoredItemInvalid(msg)


def request_status(
    huey: Huey, request_id: str
) -> tuple[Literal["failed"], str] | tuple[Literal["queued", "done"], None]:
    """A request's status and, when ``failed``, its last error.

    Raises:
        UnknownRequest: no request with ``request_id`` was ever queued on this queue.
    """
    try:
        result = huey.result(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            request_id, preserve=True
        )
    except TaskException as exc:
        return "failed", str(exc)
    if result is not None:
        return "done", None
    if huey.get(_issued_key(request_id), peek=True) is None:  # pyright: ignore[reportUnknownMemberType]
        msg = f"no request {request_id!r} was queued on this knowledge base"
        raise UnknownRequest(msg)
    return "queued", None


class Drained(NamedTuple):
    """What one ``drain`` did: tasks run, and how many of those did not complete."""

    ran: int
    failed: int


def _enqueue_due(huey: Huey) -> None:
    """Move the due scheduled tasks onto the queue; on Ctrl-C the rest still go on.

    ``read_schedule`` takes every due task off the schedule at once.
    """
    due: list[object] = list(huey.read_schedule())  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    try:
        while due:
            huey.enqueue(due[0])  # pyright: ignore[reportUnknownMemberType]
            del due[0]
    except KeyboardInterrupt:
        for task in due:
            huey.enqueue(task)  # pyright: ignore[reportUnknownMemberType]
        raise


def drain(huey: Huey) -> Drained:
    """Run every due task, the due retries included, until the queue is empty.

    A failed attempt counts once in ``failed`` whether or not a retry is still due.

    Raises:
        KeyboardInterrupt: Ctrl-C while a task was dequeued, in the task body (which huey
            swallows) or in huey's own bookkeeping: the task is put back on the queue
            (re-running a write is safe) and the tasks after it are left unrun.
    """
    _enqueue_due(huey)
    seen: Counter[str] = Counter()

    def _seen(signal: str, *_args: object) -> None:
        seen[signal] += 1

    huey.signal(SIGNAL_COMPLETE, SIGNAL_INTERRUPTED)(_seen)  # pyright: ignore[reportUnknownMemberType]
    ran = 0
    try:
        while (task := huey.dequeue()) is not None:  # pyright: ignore[reportUnknownVariableType]
            try:
                huey.execute(task)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            except KeyboardInterrupt:
                huey.enqueue(task)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                raise
            if seen[SIGNAL_INTERRUPTED]:
                huey.enqueue(task)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                raise KeyboardInterrupt
            ran += 1
    finally:
        huey.disconnect_signal(_seen)  # pyright: ignore[reportUnknownMemberType] - from every signal
    return Drained(ran=ran, failed=ran - seen[SIGNAL_COMPLETE])


def run_consumer(huey: Huey) -> None:
    """Run huey's consumer on ``huey``; it stops gracefully on SIGINT."""
    # One worker, pinned: ``warmup_dump.write_dump`` shares one temp name per item.
    huey.create_consumer(workers=1).run()  # pyright: ignore[reportUnknownMemberType]
