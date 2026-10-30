"""``KnowledgeBase``: what every operation takes first, opened once per process."""

from __future__ import annotations

from dataclasses import dataclass

from huey import Huey  # pyright: ignore[reportMissingTypeStubs]
from huey.api import TaskWrapper  # pyright: ignore[reportMissingTypeStubs]

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.embeddings import Embedder, OpenAIEmbedder
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.registry import KindRegistry, load_kinds
from tools_knowledge_base.queue import make_huey
from tools_knowledge_base.store.factory import collection_name, open_store
from tools_knowledge_base.store.protocol import VectorStore
from tools_knowledge_base.tasks import register_tasks


@dataclass(frozen=True)
class KnowledgeBase:
    """Settings, kinds, the active embedder's collection, and a huey with both tasks."""

    settings: KnowledgeBaseSettings
    kinds: KindRegistry
    store: VectorStore
    embedder: Embedder
    huey: Huey
    write_memory: TaskWrapper
    forget_memory: TaskWrapper


def open_knowledge_base(
    settings: KnowledgeBaseSettings,
    *,
    huey: Huey | None = None,
    embedder: Embedder | None = None,
    kinds: KindRegistry | None = None,
) -> KnowledgeBase:
    """Open the knowledge base ``settings`` describe; each keyword replaces its default.

    The embedder defaults to ``embeddings.active``'s, the kinds to every installed one,
    the queue to ``queue.path``; the store opens the embedder's own collection.

    Raises:
        KnowledgeBaseError: that collection's vectors are not the embedder's dimension.
    """
    embedder = (
        embedder if embedder is not None else OpenAIEmbedder(settings.embeddings.active_embedder)
    )
    kinds = kinds if kinds is not None else load_kinds()
    huey = huey if huey is not None else make_huey(settings.queue)
    collection = collection_name(settings.vector_store.collection_prefix, embedder.vector_space)
    store = open_store(settings, collection, dimensions=embedder.dimensions)
    if store.dimensions != embedder.dimensions:
        msg = (
            f"collection {collection!r} holds {store.dimensions}-dimension vectors, but "
            f"embedder {embedder.vector_space!r} makes {embedder.dimensions}"
        )
        raise KnowledgeBaseError(msg)
    tasks = register_tasks(huey, settings=settings, store=store, embedder=embedder, kinds=kinds)
    return KnowledgeBase(
        settings=settings,
        kinds=kinds,
        store=store,
        embedder=embedder,
        huey=huey,
        write_memory=tasks.write_memory,
        forget_memory=tasks.forget_memory,
    )
