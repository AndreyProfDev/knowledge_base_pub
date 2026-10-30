"""Core's ``settings`` and ``store`` fixtures, for the Qdrant adapter only."""

from __future__ import annotations

from pathlib import Path

import pytest
from store_adapters import ADAPTERS, COLLECTION, EMBEDDER

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.store.factory import open_store
from tools_knowledge_base.store.protocol import VectorStore


@pytest.fixture
def settings(tmp_path: Path) -> KnowledgeBaseSettings:
    return ADAPTERS["qdrant"](tmp_path)


@pytest.fixture
def store(settings: KnowledgeBaseSettings) -> VectorStore:
    return open_store(settings, COLLECTION, dimensions=EMBEDDER.dimensions)
