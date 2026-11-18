"""A knowledge base on the testing overlay (SQLite in a temp file, drained writes) with fakes."""

from __future__ import annotations

import atexit
import shutil
import tempfile
from collections.abc import Callable, Sequence
from importlib.metadata import EntryPoint
from pathlib import Path

from fake_embedder import FakeEmbedder
from fake_kind import FakeKind
from stevedore import ExtensionManager
from stevedore.extension import Extension

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import (
    KnowledgeBaseSettings,
    LanceDBSettings,
    SqliteSettings,
    VectorStoreSettings,
    get_settings,
)
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import MEMORY_KINDS, KindRegistry
from tools_knowledge_base.models import WriteAccepted
from tools_knowledge_base.operations import store_memory
from tools_knowledge_base.write_queue import WriteQueue


def lancedb_settings(path: Path) -> KnowledgeBaseSettings:
    """The testing overlay on LanceDB under ``path``: one directory, any number of opens."""
    return get_settings(Environment.TESTING).model_copy(
        update={
            "vector_store": VectorStoreSettings(
                collection_prefix="memory",
                backend="lancedb",
                lancedb=LanceDBSettings(path=path, max_small_fragments=20),
            )
        }
    )


def sqlite_settings(path: Path) -> KnowledgeBaseSettings:
    """The testing overlay on SQLite in the database file ``path``: any number of opens."""
    return get_settings(Environment.TESTING).model_copy(
        update={
            "vector_store": VectorStoreSettings(
                collection_prefix="memory",
                backend="sqlite",
                sqlite=SqliteSettings(path=path),
            )
        }
    )


def temp_sqlite_settings() -> KnowledgeBaseSettings:
    """The testing overlay on SQLite in a database file of its own, removed at exit.

    Every call is a fresh store, as the old in-memory Qdrant was on every open.
    """
    directory = tempfile.mkdtemp(prefix="kb-test-")
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return sqlite_settings(Path(directory) / "knowledge.sqlite3")


def fake_registry(*kinds: MemoryKind) -> KindRegistry:
    """A registry of ``kinds``, the default fake kind when none are given."""
    extensions = [
        Extension(
            kind.name,
            EntryPoint(name=kind.name, value="fake_kind:FakeKind", group=MEMORY_KINDS),
            FakeKind,
            kind,
        )
        for kind in kinds or (FakeKind(),)
    ]
    return KindRegistry(ExtensionManager[MemoryKind].make_test_instance(extensions))


def open_fake_kb(
    *kinds: MemoryKind,
    embedder: FakeEmbedder | None = None,
    writes: WriteQueue | None = None,
    settings: KnowledgeBaseSettings | None = None,
    sleep: Callable[[float], None] | None = None,
) -> KnowledgeBase:
    """A fresh knowledge base; ``writes`` defaults to a queue nothing works but ``drain``.

    ``sleep`` defaults to a no-op, so a write's retries do not wait.
    """
    return open_knowledge_base(
        settings or temp_sqlite_settings(),
        writes=writes or WriteQueue(background=False),
        embedder=embedder or FakeEmbedder(),
        kinds=fake_registry(*kinds),
        sleep=sleep or (lambda _seconds: None),
    )


def stored(
    kb: KnowledgeBase, title: str, tags: Sequence[str] = (), kind: str = "fake"
) -> WriteAccepted:
    """Store a fake payload and drain the queue, so the item is readable on return."""
    accepted = store_memory(kb, kind, {"title": title, "tags": list(tags)})
    kb.writes.drain()
    return accepted
