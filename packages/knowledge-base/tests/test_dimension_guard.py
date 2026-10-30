"""Startup refuses a misconfiguration before the first request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb
from omegaconf import OmegaConf
from pydantic import ValidationError

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import (
    EmbedderSettings,
    EmbeddingsSettings,
    KnowledgeBaseSettings,
    VectorStoreSettings,
    get_settings,
)
from tools_knowledge_base.errors import KnowledgeBaseError


def _embeddings_data() -> dict[str, Any]:
    return get_settings(Environment.TESTING).embeddings.model_dump()


def test_the_testing_overlay_runs_qdrant_in_memory() -> None:
    settings = get_settings(Environment.TESTING)

    assert settings.vector_store.backend == "qdrant"
    assert settings.vector_store.qdrant is not None
    assert settings.vector_store.qdrant.location == ":memory:"


def test_the_local_overlay_runs_lancedb_under_data() -> None:
    # Its vector store block only: the full overlay resolves the real OPEN_AI_API_KEY.
    configs = KnowledgeBaseSettings.yaml_directory
    merged = OmegaConf.merge(
        OmegaConf.load(configs / "base" / "knowledge_base.yaml"),
        OmegaConf.load(configs / "local" / "knowledge_base.yaml"),
    )
    store = VectorStoreSettings.model_validate(OmegaConf.to_container(merged.vector_store))

    assert store.backend == "lancedb"
    assert store.lancedb is not None
    assert store.lancedb.path == Path("data/lancedb")


def test_active_embedder_is_the_block_active_names() -> None:
    embeddings = EmbeddingsSettings.model_validate(_embeddings_data() | {"active": "openai-small"})

    assert embeddings.active_embedder.model == "text-embedding-3-small"
    assert embeddings.active_embedder.dimensions == 1536


def test_an_active_embedder_naming_no_block_fails_validation() -> None:
    data = _embeddings_data()
    data["active"] = "missing"
    data["embedders"]["openai-small"]["api_key"] = "sk-must-not-leak"

    with pytest.raises(ValidationError, match=r"embeddings\.active 'missing' names no configured"):
        EmbeddingsSettings.model_validate(data)
    with pytest.raises(ValidationError) as raised:
        EmbeddingsSettings.model_validate(data)
    assert "sk-must-not-leak" not in str(raised.value)


def test_a_settings_error_does_not_echo_the_api_key() -> None:
    data = get_settings(Environment.TESTING).model_dump()
    embedder = data["embeddings"]["embedders"]["openai-small"]
    embedder["api_key"] = "sk-must-not-leak"
    del embedder["model"]

    with pytest.raises(ValidationError) as raised:
        KnowledgeBaseSettings.model_validate(data)

    assert "embedders.openai-small.model" in str(raised.value)
    assert "sk-must-not-leak" not in str(raised.value)
    # Each model holding a key hides its own input too: the outermost one decides.
    with pytest.raises(ValidationError) as raised:
        EmbedderSettings.model_validate(embedder)
    assert "sk-must-not-leak" not in str(raised.value)


def test_the_api_key_is_masked_in_the_settings_repr() -> None:
    data = _embeddings_data()
    data["embedders"]["openai-small"]["api_key"] = "sk-must-not-leak"

    embeddings = EmbeddingsSettings.model_validate(data)

    assert "sk-must-not-leak" not in repr(embeddings)
    assert embeddings.embedders["openai-small"].api_key.get_secret_value() == "sk-must-not-leak"


def test_a_collection_of_another_dimension_is_refused_at_open(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-8", dimensions=8))

    with pytest.raises(KnowledgeBaseError, match="holds 8-dimension vectors, but embedder"):
        open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-8", dimensions=16))


def test_a_collection_of_the_embedders_dimension_reopens(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    open_fake_kb(settings=settings)

    assert open_fake_kb(settings=settings).store.dimensions == FakeEmbedder().dimensions


@pytest.mark.parametrize("backend", ["lancedb", "qdrant"])
def test_a_backend_without_its_settings_block_fails_validation(backend: str) -> None:
    with pytest.raises(ValidationError, match=f"vector_store.{backend} is unset"):
        VectorStoreSettings.model_validate({"collection_prefix": "memory", "backend": backend})
