"""Warm-up: embed and write the warm-up files' items that are missing or changed in the store."""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ValidationError

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import WarmupPartiallyWritten
from tools_knowledge_base.models import WarmupKindCounts, WarmupReport
from tools_knowledge_base.operations.reembed import PAGE_SIZE
from tools_knowledge_base.operations.warmup_files import WarmupItem, load_warmup_items
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.warmup_dump import dump_holds, upsert_and_sync_dump

_BATCH = 256
logger = logging.getLogger(__name__)


def _digest(model: BaseModel) -> str:
    canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _stored_digests(kb: KnowledgeBase, items: list[WarmupItem]) -> dict[UUID, str]:
    """Each stored item's payload digest; one failing its model is left out, so rewritten."""
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


def _write_batch(kb: KnowledgeBase, batch: Sequence[WarmupItem]) -> None:
    """Embed ``batch`` (one kind) in one call, upsert it, then sync its dump files."""
    kind = batch[0].kind
    updated_at = datetime.now(UTC)
    vectors = kb.embedder.embed_documents([kind.embed_text(item.model) for item in batch])
    points = [
        Point(
            id=item.item_id,
            kind=kind.name,
            updated_at=updated_at,
            payload=item.model.model_dump(mode="json"),
            vector=vector,
        )
        for item, vector in zip(batch, vectors, strict=True)
    ]
    warmup = kb.settings.warmup
    upsert_and_sync_dump(
        kb.store, warmup.path if warmup.dump else None, kb.kinds, kind.name, points
    )


def warmup_memory(kb: KnowledgeBase) -> WarmupReport:
    """Write every warm-up item not stored unchanged, ``PAGE_SIZE`` per embedding call.

    Nothing is deleted. The first batch that fails stops the run; the batches before it
    stay written and a rerun skips them as unchanged.

    Raises:
        WarmupDirectoryMissing: ``warmup.path`` is not a directory, or cannot be listed.
        WarmupDirectoryEmpty: ``warmup.path`` holds no items.
        pydantic.ValidationError: any file or item is bad; nothing is written.
        WarmupPartiallyWritten: a batch failed to embed or write.
    """
    items, shadowed = load_warmup_items(kb)
    stored = _stored_digests(kb, items)
    warmup = kb.settings.warmup
    # A stored item whose dump file is missing or stale (a batch died between upsert and
    # dump) is rewritten too, else a rerun would skip it and leave the dump short.
    changed = [
        item
        for item in items
        if stored.get(item.item_id) != _digest(item.model)
        or (
            warmup.dump
            and not dump_holds(
                warmup.path, item.kind.name, item.item_id, item.model.model_dump(mode="json")
            )
        )
    ]
    written: Counter[str] = Counter()
    for name in kb.kinds.names():
        of_kind = [item for item in changed if item.kind.name == name]
        for number, batch in enumerate(itertools.batched(of_kind, PAGE_SIZE), start=1):
            try:
                _write_batch(kb, batch)
            except Exception as exc:
                raise WarmupPartiallyWritten(written.total(), name, number, exc) from exc
            written[name] += len(batch)
    return WarmupReport(
        kinds={
            name: WarmupKindCounts(
                written=written[name],
                unchanged=sum(1 for item in items if item.kind.name == name) - written[name],
            )
            for name in kb.kinds.names()
        },
        total_written=written.total(),
        shadowed=shadowed,
    )
