"""Re-embed: fill the active collection from another embedder's, one page at a time."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from uuid import UUID

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.models import ReembedReport
from tools_knowledge_base.operations.items import memory_item
from tools_knowledge_base.reembed_journal import journal, journal_path, journaled, open_journal
from tools_knowledge_base.store.factory import collection_name, open_store
from tools_knowledge_base.store.protocol import Item, Point, VectorStore

PAGE_SIZE = 32
"""Items per ``embed_documents`` call: TEI rejects more than 32 inputs a request."""


def _pages(source: VectorStore, kind: str) -> Iterator[Sequence[Item]]:
    """``kind``'s items in ``source``, ``PAGE_SIZE`` at a time."""
    items, cursor = source.list(kind, limit=PAGE_SIZE, cursor=None)
    yield items
    while cursor is not None:
        items, cursor = source.list(kind, limit=PAGE_SIZE, cursor=cursor)
        yield items


def _copy_page(
    kb: KnowledgeBase,
    conn: sqlite3.Connection,
    run_key: str,
    kind: MemoryKind,
    items: Sequence[Item],
    too_long: list[UUID],
) -> tuple[int, int, int]:
    """Embed and upsert the items the active collection lacks and no earlier run copied.

    Every id the active collection holds once the page lands is journaled.
    Returns (copied, skipped as held, skipped as deleted since copied).
    """
    held = {item.id for item in kb.store.get([item.id for item in items])}
    already = journaled(conn, run_key, [item.id for item in items])
    deleted = already - held
    fresh: list[tuple[Item, str]] = []
    for item in items:
        if item.id in held or item.id in deleted:
            continue
        text = kind.embed_text(memory_item(kind, item).payload)
        if kb.embedder.count_tokens(text) > kb.embedder.max_input_tokens:
            too_long.append(item.id)
            continue
        fresh.append((item, text))
    if fresh:
        vectors = kb.embedder.embed_documents([text for _, text in fresh])
        kb.store.upsert(
            [
                Point(**dict(item), vector=vector)
                for (item, _), vector in zip(fresh, vectors, strict=True)
            ]
        )
    # After the upsert landed: an id journaled but never copied would be lost for good.
    journal(conn, run_key, (held - already) | {item.id for item, _ in fresh})
    return len(fresh), len(held), len(deleted)


def reembed_memory(kb: KnowledgeBase, source_collection: str) -> ReembedReport:
    """Copy every installed kind's items from ``source_collection``, re-embedded.

    Ids, payloads and ``updated_at`` are kept; an id the active collection already holds
    is skipped, so a second run embeds nothing. An item whose embed text is over the
    active embedder's ``max_input_tokens`` is left out and listed in ``too_long``.

    Each id the active collection holds after a page lands, copied or already there, is
    journaled under the pair (active collection, ``source_collection``) in
    ``reembed-journal.sqlite3`` next to the store (in memory for a store with no local
    directory). A re-run skips a journaled id the active collection no longer holds
    (``skipped_deleted``): it was deleted or reworded away since, and must not come
    back from the source.

    Run with the worker stopped (Backends #changing-model). The accepted cost when that
    is broken between partial runs: an item the worker writes into the active
    collection and that is then deleted, before this run journals it, is copied back
    from the source by the next run.

    Raises:
        KnowledgeBaseError: ``source_collection`` does not exist, or holds items of a
            kind not installed here (nothing is copied: they could not be validated).
    """
    source = open_store(kb.settings, source_collection, dimensions=None)
    installed = set(kb.kinds.names())
    uncopied = {k: n for k, n in sorted(source.count_kinds().items()) if k not in installed}
    if uncopied:
        msg = (
            f"collection {source_collection!r} holds items of kinds not installed, "
            f"which re-embed cannot copy: {uncopied}"
        )
        raise KnowledgeBaseError(msg)
    copied = skipped = deleted = 0
    too_long: list[UUID] = []
    active = collection_name(kb.settings.vector_store.collection_prefix, kb.embedder.vector_space)
    run_key = f"{active}<-{source_collection}"
    with closing(open_journal(journal_path(kb.settings))) as conn:
        for kind in kb.kinds:
            for items in _pages(source, kind.name):
                page_copied, page_skipped, page_deleted = _copy_page(
                    kb, conn, run_key, kind, items, too_long
                )
                copied += page_copied
                skipped += page_skipped
                deleted += page_deleted
    return ReembedReport(
        copied=copied, skipped_existing=skipped, skipped_deleted=deleted, too_long=too_long
    )
