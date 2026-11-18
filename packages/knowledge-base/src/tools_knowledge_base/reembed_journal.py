"""Re-embed's resume journal: a small SQLite file next to the store."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings

JOURNAL_NAME = "reembed-journal.sqlite3"
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS journal"
    " (source TEXT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY (source, item_id))"
)
"""A module constant: SQLite ignores the keyword case, so a mutated copy is equivalent."""


def journal_path(settings: KnowledgeBaseSettings) -> Path | None:
    """Where the journal lives for the configured store; None for one with no local directory."""
    store = settings.vector_store
    if store.lancedb is not None and store.backend == "lancedb":
        return store.lancedb.path / JOURNAL_NAME
    if store.sqlite is not None and store.backend == "sqlite":
        return store.sqlite.path.parent / JOURNAL_NAME
    return None


def open_journal(path: Path | None) -> sqlite3.Connection:
    """The journal at ``path``, created if missing; ``None`` is an in-memory one for this run."""
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(":memory:" if path is None else path)
    conn.execute(_CREATE_TABLE)
    return conn


def journaled(conn: sqlite3.Connection, source: str, ids: Iterable[UUID]) -> set[UUID]:
    """Those of ``ids`` an earlier run from ``source`` found in the active collection."""
    return {
        item_id
        for item_id in ids
        if conn.execute(
            "SELECT 1 FROM journal WHERE source = ? AND item_id = ?", (source, str(item_id))
        ).fetchone()
        is not None
    }


def journal(conn: sqlite3.Connection, source: str, ids: Iterable[UUID]) -> None:
    """Record ``ids`` as copied or held, and commit."""
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO journal (source, item_id) VALUES (?, ?)",
            [(source, str(item_id)) for item_id in ids],
        )
