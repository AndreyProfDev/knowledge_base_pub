"""The re-embed journal: which backend owns it, its exact schema and statements, its run key."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb, sqlite_settings, stored
from fake_kind import FakeKind

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.operations import reembed_memory
from tools_knowledge_base.reembed_journal import (
    JOURNAL_NAME,
    journal,
    journal_path,
    journaled,
    open_journal,
)

ID = UUID(int=1)


def _traced(conn: sqlite3.Connection) -> list[str]:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    return statements


def test_the_journal_path_needs_both_the_backend_and_its_settings(tmp_path: Path) -> None:
    lance = lancedb_settings(tmp_path)
    sqlite = sqlite_settings(tmp_path / "kb" / "store.sqlite3")
    mixed: list[KnowledgeBaseSettings] = [
        lance.model_copy(
            update={
                "vector_store": lance.vector_store.model_copy(
                    update={"backend": "sqlite", "sqlite": None}
                )
            }
        ),
        sqlite.model_copy(
            update={
                "vector_store": sqlite.vector_store.model_copy(
                    update={"backend": "lancedb", "lancedb": None}
                )
            }
        ),
    ]

    assert [journal_path(settings) for settings in mixed] == [None, None]


def test_the_journal_path_ignores_the_other_backends_settings(tmp_path: Path) -> None:
    lance = lancedb_settings(tmp_path)
    sqlite = sqlite_settings(tmp_path / "kb" / "store.sqlite3")
    both_lance = lance.model_copy(
        update={
            "vector_store": lance.vector_store.model_copy(
                update={"sqlite": sqlite.vector_store.sqlite}
            )
        }
    )
    both_sqlite = sqlite.model_copy(
        update={
            "vector_store": sqlite.vector_store.model_copy(
                update={"lancedb": lance.vector_store.lancedb}
            )
        }
    )

    assert journal_path(both_lance) == tmp_path / JOURNAL_NAME
    assert journal_path(both_sqlite) == tmp_path / "kb" / JOURNAL_NAME


def test_open_journal_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / JOURNAL_NAME

    with closing(open_journal(path)):
        pass

    assert path.is_file()


def test_the_journal_table_is_created_with_this_exact_schema() -> None:
    with closing(open_journal(None)) as conn:
        [(schema,)] = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'journal'")

    assert schema == (
        "CREATE TABLE journal (source TEXT NOT NULL, item_id TEXT NOT NULL,"
        " PRIMARY KEY (source, item_id))"
    )


def test_the_journal_statements_are_exactly_these() -> None:
    with closing(open_journal(None)) as conn:
        statements = _traced(conn)
        journal(conn, "src", [ID])
        journaled(conn, "src", [ID])

    item = "00000000-0000-0000-0000-000000000001"
    insert = f"INSERT OR IGNORE INTO journal (source, item_id) VALUES ('src', '{item}')"  # noqa: S608
    select = f"SELECT 1 FROM journal WHERE source = 'src' AND item_id = '{item}'"  # noqa: S608
    assert insert in statements
    assert select in statements


def test_the_run_key_names_the_prefixed_active_collection_and_the_source(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    stored(open_fake_kb(FakeKind(), settings=settings, embedder=FakeEmbedder("fake-a", 8, 16)), "s")
    active = open_fake_kb(FakeKind(), settings=settings, embedder=FakeEmbedder("fake-b", 12, 4))

    reembed_memory(active, "memory-fake-a")

    with closing(sqlite3.connect(tmp_path / JOURNAL_NAME)) as conn:
        sources = {row[0] for row in conn.execute("SELECT source FROM journal")}
    assert sources == {"memory-fake-b<-memory-fake-a"}
