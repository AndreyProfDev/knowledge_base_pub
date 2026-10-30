"""Warm-up: queue the warm-up files' items that are missing or changed in the store."""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
from collections import Counter
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import WarmupPartiallyQueued
from tools_knowledge_base.models import WarmupKindCounts, WarmupReport
from tools_knowledge_base.operations.store import enqueue_item
from tools_knowledge_base.operations.warmup_files import WarmupItem, load_warmup_items
from tools_knowledge_base.operations.warmup_progress import WarmupRequest, WarmupRun, record_run

_BATCH = 256
logger = logging.getLogger(__name__)


def _digest(model: BaseModel) -> str:
    canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _stored_digests(kb: KnowledgeBase, items: list[WarmupItem]) -> dict[UUID, str]:
    """Each stored item's payload digest; one failing its model is left out, so re-queued."""
    by_id = {item.item_id: item for item in items}
    digests: dict[UUID, str] = {}
    for batch in itertools.batched(by_id, _BATCH):
        for stored in kb.store.get(batch):
            # The id hashes the kind name, so a stored point under it is of the same kind.
            kind = by_id[stored.id].kind
            try:
                model = kind.payload_model.model_validate(stored.payload)
            except ValidationError as exc:
                logger.warning(
                    "warm-up replaces stored %s item %s: its payload fails the model: %s",
                    kind.name,
                    stored.id,
                    exc.errors(include_url=False, include_input=False),
                )
                continue
            digests[stored.id] = _digest(model)
    return digests


def _record_after(exc: BaseException, kb: KnowledgeBase, run_id: str, run: WarmupRun) -> None:
    """Record ``run`` while ``exc`` propagates, noting on ``exc`` whether that worked."""
    try:
        record_run(kb, run_id, run)
    except Exception as record_exc:
        exc.add_note(
            f"warm-up run {run_id} could not be recorded: {type(record_exc).__name__}: {record_exc}"
        )
        return
    exc.add_note(f"warm-up run {run_id} recorded {len(run.requests)} queued requests")


def warmup_memory(kb: KnowledgeBase) -> WarmupReport:
    """Queue every warm-up item not stored unchanged; nothing is deleted.

    Any failure partway still records the run with the requests queued so far. One outside
    ``enqueue_item`` (a bug, ``KeyboardInterrupt``) is re-raised with a note naming the run
    and whether it was recorded.

    Raises:
        WarmupPartiallyQueued: ``enqueue_item`` or recording the run failed; its message names
            the run and says whether it was recorded.
        WarmupDirectoryMissing: ``warmup.path`` is not a directory, or cannot be listed.
        WarmupDirectoryEmpty: ``warmup.path`` holds no items.
        pydantic.ValidationError: any file or item is bad; nothing is queued.
    """
    items, shadowed = load_warmup_items(kb)
    stored = _stored_digests(kb, items)
    unchanged = dict.fromkeys(kb.kinds.names(), 0)
    requests: list[WarmupRequest] = []
    run_id = str(uuid4())
    try:
        for item in items:
            name = item.kind.name
            if stored.get(item.item_id) == _digest(item.model):
                unchanged[name] += 1
                continue
            try:
                accepted = enqueue_item(kb, item.kind, item.model, replaces=None)
            except Exception as exc:
                run = WarmupRun(requests=requests, unchanged=sum(unchanged.values()))
                try:
                    record_run(kb, run_id, run)
                except Exception as record_exc:
                    exc.add_note(f"recording: {type(record_exc).__name__}: {record_exc}")
                    recorded = "and could not be recorded"
                else:
                    recorded = "and was recorded"
                problem = f"stopped after queueing {len(requests)} requests {recorded}"
                raise WarmupPartiallyQueued(run_id, problem, exc) from exc
            requests.append(
                WarmupRequest(request_id=accepted.request_id, item_id=accepted.item_id, kind=name)
            )
    except WarmupPartiallyQueued:
        raise
    except BaseException as exc:
        _record_after(
            exc, kb, run_id, WarmupRun(requests=requests, unchanged=sum(unchanged.values()))
        )
        raise
    try:
        record_run(kb, run_id, WarmupRun(requests=requests, unchanged=sum(unchanged.values())))
    except Exception as exc:
        problem = f"queued {len(requests)} requests but could not be recorded"
        raise WarmupPartiallyQueued(run_id, problem, exc) from exc
    queued = Counter(request.kind for request in requests)
    return WarmupReport(
        run_id=run_id,
        kinds={
            name: WarmupKindCounts(queued=queued[name], unchanged=unchanged[name])
            for name in kb.kinds.names()
        },
        total_queued=len(requests),
        shadowed=shadowed,
    )
