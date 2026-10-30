"""A warm-up run's record, and its progress derived from each recorded request's status."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import StoredItemInvalid, UnknownRequest, UnknownWarmupRun
from tools_knowledge_base.models import WarmupFailure, WarmupProgress
from tools_knowledge_base.queue import peek_value, put_value, request_status

FAILURES_SHOWN = 50


class WarmupRequest(BaseModel):
    """One write a run queued."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    item_id: UUID
    kind: str


class WarmupRun(BaseModel):
    """What a run queued, and how many items it left unchanged."""

    model_config = ConfigDict(frozen=True)

    requests: list[WarmupRequest]
    unchanged: int


def _run_key(run_id: str) -> str:
    return f"warmup:{run_id}"


def record_run(kb: KnowledgeBase, run_id: str, run: WarmupRun) -> None:
    """Keep ``run`` on the queue's storage under ``run_id``; it never expires."""
    put_value(kb.huey, _run_key(run_id), run.model_dump_json())


def get_warmup_progress(kb: KnowledgeBase, run_id: str) -> WarmupProgress:
    """How many of run ``run_id``'s writes are done, failed and pending.

    A failing write stays pending through its retries: about 150 s with the base queue
    settings before it counts as failed.

    Raises:
        UnknownWarmupRun: no run ``run_id`` was recorded on this queue.
        StoredItemInvalid: the run's record is not a run, or names a request never issued.
    """
    raw = peek_value(kb.huey, _run_key(run_id))
    if raw is None:
        msg = f"no warm-up run {run_id!r} was recorded on this knowledge base"
        raise UnknownWarmupRun(msg)
    try:
        run = WarmupRun.model_validate_json(raw)
    except ValidationError as exc:
        msg = (
            f"warm-up run {run_id!r}'s record: {exc.errors(include_url=False, include_input=False)}"
        )
        raise StoredItemInvalid(msg) from exc
    done = 0
    failures: list[WarmupFailure] = []
    for request in run.requests:
        try:
            status = request_status(kb.huey, request.request_id)
        except UnknownRequest as exc:
            msg = f"warm-up run {run_id!r} records request {request.request_id!r}, never issued"
            raise StoredItemInvalid(msg) from exc
        if status[0] == "done":
            done += 1
        elif status[0] == "failed":
            failures.append(
                WarmupFailure(
                    request_id=request.request_id,
                    item_id=request.item_id,
                    kind=request.kind,
                    error=status[1],
                )
            )
    total = len(run.requests)
    pending = total - done - len(failures)
    return WarmupProgress(
        run_id=run_id,
        total=total,
        done=done,
        failed=len(failures),
        pending=pending,
        unchanged=run.unchanged,
        finished=pending == 0,
        failures=failures[:FAILURES_SHOWN],
        failures_truncated=len(failures) > FAILURES_SHOWN,
    )
