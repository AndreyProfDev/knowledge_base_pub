"""``KnowledgeBase``: what every operation takes first, opened once per process."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.embeddings import Embedder, OpenAIEmbedder
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.registry import KindRegistry, load_kinds
from tools_knowledge_base.readiness import require_embedder_key
from tools_knowledge_base.store.factory import collection_name, open_store
from tools_knowledge_base.store.lazy import LazyStore
from tools_knowledge_base.store.protocol import VectorStore
from tools_knowledge_base.write_queue import WriteQueue


@dataclass(frozen=True)
class KnowledgeBase:
    """Settings, kinds, the active embedder's collection, the write queue and its sleep."""

    settings: KnowledgeBaseSettings
    kinds: KindRegistry
    store: VectorStore
    embedder: Embedder
    writes: WriteQueue
    sleep: Callable[[float], None]


def open_knowledge_base(
    settings: KnowledgeBaseSettings,
    *,
    writes: WriteQueue | None = None,
    embedder: Embedder | None = None,
    kinds: KindRegistry | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> KnowledgeBase:
    """Open the knowledge base ``settings`` describe; each keyword replaces its default.

    The embedder defaults to ``embeddings.active``'s, the kinds to every installed one,
    the queue to a ``WriteQueue`` with its own thread; the store is the embedder's own
    collection, opened on its first call. ``sleep`` is what a write's retry waits with.

    The store's first call raises ``KnowledgeBaseError`` when the backend is not installed,
    is unreachable, or holds a collection whose vectors are not the embedder's dimension.
    """
    embedder = (
        embedder
        if embedder is not None
        else OpenAIEmbedder(
            settings.embeddings.active_embedder,
            require_key=partial(require_embedder_key, settings),
        )
    )
    kinds = kinds if kinds is not None else load_kinds()
    writes = writes if writes is not None else WriteQueue()

    def open_checked() -> VectorStore:
        collection = collection_name(settings.vector_store.collection_prefix, embedder.vector_space)
        store = open_store(settings, collection, dimensions=embedder.dimensions)
        if store.dimensions != embedder.dimensions:
            msg = (
                f"collection {collection!r} holds {store.dimensions}-dimension vectors, but "
                f"embedder {embedder.vector_space!r} makes {embedder.dimensions}"
            )
            raise KnowledgeBaseError(msg)
        return store

    return KnowledgeBase(
        settings=settings,
        kinds=kinds,
        store=LazyStore(open_checked),
        embedder=embedder,
        writes=writes,
        sleep=sleep,
    )
