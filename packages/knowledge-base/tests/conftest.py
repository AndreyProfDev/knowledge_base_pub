"""The ``settings`` and ``store`` fixtures: the vector-store suites, once per installed adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from store_adapters import ADAPTERS, COLLECTION, EMBEDDER

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.store.factory import open_store
from tools_knowledge_base.store.protocol import VectorStore


@pytest.fixture(params=sorted(ADAPTERS))
def settings(request: pytest.FixtureRequest, tmp_path: Path) -> KnowledgeBaseSettings:
    name: str = request.param
    built = ADAPTERS[name](tmp_path)
    assert built.vector_store.backend == name
    return built


@pytest.fixture
def store(settings: KnowledgeBaseSettings) -> VectorStore:
    return open_store(settings, COLLECTION, dimensions=EMBEDDER.dimensions)
