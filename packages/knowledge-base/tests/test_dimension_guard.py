"""Startup refuses a misconfiguration before the first request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tiktoken
from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb
from omegaconf import OmegaConf
from pydantic import ValidationError

from knowledge_base_config import Environment
from knowledge_base_config.resolvers import register_resolvers
from tools_knowledge_base.configs.settings import (
    EmbedderSettings,
    EmbeddingsSettings,
    KnowledgeBaseSettings,
    VectorStoreSettings,
    WarmupSettings,
    get_settings,
)
from tools_knowledge_base.errors import KnowledgeBaseError


def _embeddings_data() -> dict[str, Any]:
    return get_settings(Environment.TESTING).embeddings.model_dump()


def test_the_testing_overlay_runs_sqlite_in_a_file() -> None:
    settings = get_settings(Environment.TESTING)

    assert settings.vector_store.backend == "sqlite"
    assert settings.vector_store.sqlite is not None
    assert settings.vector_store.sqlite.path.name == "knowledge.sqlite3"
    assert str(settings.vector_store.sqlite.path) != ":memory:"


def test_the_local_overlay_runs_sqlite_under_an_absolute_data_dir() -> None:
    # Its vector store and warmup blocks only: the full overlay resolves the real OPEN_AI_API_KEY.
    register_resolvers()
    configs = KnowledgeBaseSettings.yaml_directory
    merged = OmegaConf.merge(
        OmegaConf.load(configs / "base" / "knowledge_base.yaml"),
        OmegaConf.load(configs / "local" / "knowledge_base.yaml"),
    )
    store = VectorStoreSettings.model_validate(
        OmegaConf.to_container(merged.vector_store, resolve=True)
    )
    warmup = WarmupSettings.model_validate(OmegaConf.to_container(merged.warmup, resolve=True))

    assert store.backend == "sqlite"
    assert store.sqlite is not None
    assert store.sqlite.path.is_absolute()
    assert store.sqlite.path.name == "knowledge.sqlite3"
    assert store.lancedb is not None
    assert store.lancedb.path == store.sqlite.path.parent / "lancedb"
    assert warmup.path == store.sqlite.path.parent / "warmup"
    assert warmup.dump is True


def test_active_embedder_is_the_block_active_names() -> None:
    embeddings = EmbeddingsSettings.model_validate(_embeddings_data() | {"active": "openai-small"})

    assert embeddings.active_embedder.model == "text-embedding-3-small"
    assert embeddings.active_embedder.dimensions == 1536


def test_the_default_active_embedder_is_openai_large() -> None:
    """Unset ``KB_EMBEDDER`` falls back to openai-large: 3072 dimensions, counted with tiktoken."""
    base = OmegaConf.load(KnowledgeBaseSettings.yaml_directory / "base" / "knowledge_base.yaml")
    raw = OmegaConf.to_container(base.embeddings, resolve=False)
    assert isinstance(raw, dict)
    assert raw["active"] == "${oc.env:KB_EMBEDDER,openai-large}"

    embeddings = EmbeddingsSettings.model_validate(_embeddings_data() | {"active": "openai-large"})

    assert embeddings.active_embedder.model == "text-embedding-3-large"
    assert embeddings.active_embedder.dimensions == 3072
    assert embeddings.active_embedder.tokenizer == "tiktoken"
    assert tiktoken.encoding_name_for_model("text-embedding-3-large") == "cl100k_base"


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


def test_a_collection_of_another_dimension_is_refused_at_the_first_store_call(
    tmp_path: Path,
) -> None:
    settings = lancedb_settings(tmp_path)
    open_fake_kb(
        settings=settings, embedder=FakeEmbedder("fake-8", dimensions=8)
    ).store.count_kinds()
    kb = open_fake_kb(settings=settings, embedder=FakeEmbedder("fake-8", dimensions=16))

    with pytest.raises(KnowledgeBaseError, match="holds 8-dimension vectors, but embedder"):
        kb.store.count_kinds()


def test_a_collection_of_the_embedders_dimension_reopens(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    open_fake_kb(settings=settings)

    assert open_fake_kb(settings=settings).store.dimensions == FakeEmbedder().dimensions


@pytest.mark.parametrize("backend", ["lancedb", "qdrant", "sqlite"])
def test_a_backend_without_its_settings_block_fails_validation(backend: str) -> None:
    with pytest.raises(ValidationError, match=f"vector_store.{backend} is unset"):
        VectorStoreSettings.model_validate({"collection_prefix": "memory", "backend": backend})
