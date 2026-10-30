"""Open the configured adapter's collection, through stevedore."""

from __future__ import annotations

import re
from typing import cast

from stevedore import DriverManager, ExtensionManager
from stevedore.exception import NoMatches

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.store.protocol import VectorStore

VECTOR_STORES = "tools_knowledge_base.vector_stores"

_NOT_IN_TABLE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def collection_name(prefix: str, vector_space: str) -> str:
    """The collection for an embedder's vector space, in LanceDB's table-name alphabet.

    Example:
        >>> collection_name("memory", "BAAI/bge-m3-1024")
        'memory-BAAI_bge-m3-1024'
    """
    return f"{prefix}-{_NOT_IN_TABLE_NAME.sub('_', vector_space)}"


def open_store(
    settings: KnowledgeBaseSettings, collection: str, *, dimensions: int | None
) -> VectorStore:
    """Open ``collection`` on the ``vector_store.backend`` adapter.

    A missing collection is created at ``dimensions``; with ``None`` the adapter raises
    ``KnowledgeBaseError`` instead.

    Raises:
        KnowledgeBaseError: no installed adapter has that name.
    """
    backend = settings.vector_store.backend
    try:
        manager: DriverManager[VectorStore] = DriverManager(
            VECTOR_STORES,
            name=backend,
            invoke_on_load=True,
            invoke_args=(settings, collection),
            invoke_kwds={"dimensions": dimensions},
        )
    except NoMatches as exc:
        # A list, so that no installed backend reads as installed: [].
        installed = sorted(ExtensionManager(VECTOR_STORES).names())
        msg = (
            f"vector store backend {backend!r} is not installed (installed: {installed}); "
            f"install tools-knowledge-base-{backend} or pick an installed backend"
        )
        raise KnowledgeBaseError(msg) from exc
    # invoke_on_load=True makes the driver the adapter instance, never its class.
    return cast("VectorStore", manager.driver)  # pragma: no mutate, equivalent: type-only
