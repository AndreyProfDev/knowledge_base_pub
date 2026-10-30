from __future__ import annotations

import pytest
from stevedore.exception import NoMatches

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.store.factory import collection_name, open_store


@pytest.mark.parametrize(
    ("vector_space", "expected"),
    [
        ("text-embedding-3-small-1536", "memory-text-embedding-3-small-1536"),
        ("BAAI/bge-m3-1024", "memory-BAAI_bge-m3-1024"),
        ("a b:c_d.e-8", "memory-a_b_c_d.e-8"),
    ],
)
def test_collection_name_keeps_lancedb_table_characters(vector_space: str, expected: str) -> None:
    assert collection_name("memory", vector_space) == expected


def test_a_backend_with_no_installed_adapter_names_the_installed_ones() -> None:
    settings = get_settings(Environment.TESTING)
    # model_copy skips validation, so the backend can name an adapter nobody installs.
    vector_store = settings.vector_store.model_copy(update={"backend": "not-installed"})
    settings = settings.model_copy(update={"vector_store": vector_store})

    with pytest.raises(KnowledgeBaseError) as raised:
        open_store(settings, "memory-fake-8", dimensions=8)

    assert str(raised.value) == (
        "vector store backend 'not-installed' is not installed "
        "(installed: ['lancedb', 'qdrant']); "
        "install tools-knowledge-base-not-installed or pick an installed backend"
    )
    assert isinstance(raised.value.__cause__, NoMatches)
