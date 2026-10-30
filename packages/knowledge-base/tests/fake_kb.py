"""A knowledge base on the testing overlay (Qdrant and huey in memory) with fakes."""

from __future__ import annotations

from collections.abc import Sequence
from importlib.metadata import EntryPoint
from pathlib import Path

from fake_embedder import FakeEmbedder
from fake_kind import FakeKind
from huey import Huey  # pyright: ignore[reportMissingTypeStubs]
from stevedore import ExtensionManager
from stevedore.extension import Extension

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import (
    KnowledgeBaseSettings,
    LanceDBSettings,
    VectorStoreSettings,
    get_settings,
)
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import MEMORY_KINDS, KindRegistry
from tools_knowledge_base.models import WriteAccepted
from tools_knowledge_base.operations import store_memory
from tools_knowledge_base.queue import drain


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
    huey: Huey | None = None,
    settings: KnowledgeBaseSettings | None = None,
) -> KnowledgeBase:
    """A fresh knowledge base; ``huey`` defaults to the testing overlay's ``MemoryHuey``."""
    return open_knowledge_base(
        settings or get_settings(Environment.TESTING),
        huey=huey,
        embedder=embedder or FakeEmbedder(),
        kinds=fake_registry(*kinds),
    )


def stored(
    kb: KnowledgeBase, title: str, tags: Sequence[str] = (), kind: str = "fake"
) -> WriteAccepted:
    """Store a fake payload and drain the queue, so the item is readable on return."""
    accepted = store_memory(kb, kind, {"title": title, "tags": list(tags)})
    drain(kb.huey)
    return accepted
