"""``KnowledgeBaseSettings`` — queue, embedders, search defaults and the vector store."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from knowledge_base_config import BaseSettings, Environment, load_settings
from tools_knowledge_base.limits import MAX_LIMIT


class QueueSettings(BaseModel):
    """The huey write queue and its retry policy."""

    model_config = ConfigDict(frozen=True)

    path: str
    retries: int
    retry_delay_seconds: int
    retry_backoff: float
    timeout_seconds: float


class EmbedderSettings(BaseModel):
    """One OpenAI-compatible ``/v1/embeddings`` model."""

    # The input holds api_key: a validation error must not echo it.
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    base_url: str
    model: str
    dimensions: int
    max_input_tokens: int
    tokenizer: Literal["tiktoken", "huggingface"]
    document_prefix: str = ""
    query_prefix: str = ""
    min_score: float | None = None
    api_key: SecretStr


class EmbeddingsSettings(BaseModel):
    """Every configured embedder by name, and the one ``active`` picks."""

    # The input holds every embedder's api_key: a validation error must not echo it.
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    active: str
    embedders: dict[str, EmbedderSettings]

    @model_validator(mode="after")
    def _active_is_configured(self) -> Self:
        if self.active not in self.embedders:
            msg = (
                f"embeddings.active {self.active!r} names no configured embedder; "
                f"configured: {sorted(self.embedders)}"
            )
            raise ValueError(msg)
        return self

    @property
    def active_embedder(self) -> EmbedderSettings:
        """The settings block ``active`` names."""
        return self.embedders[self.active]


class SearchSettings(BaseModel):
    """Search defaults."""

    model_config = ConfigDict(frozen=True)

    top_k: int = Field(ge=1, le=MAX_LIMIT)


class ItemLimitsSettings(BaseModel):
    """Per-kind cap on an item's embed text, in characters; a name not installed is ignored."""

    model_config = ConfigDict(frozen=True)

    default_max_chars: int = Field(ge=1)
    max_chars: dict[str, Annotated[int, Field(ge=1)]]

    def for_kind(self, kind: str) -> int:
        """``kind``'s cap, ``default_max_chars`` when it has no entry."""
        return self.max_chars.get(kind, self.default_max_chars)


class WarmupSettings(BaseModel):
    """The ``*.yaml``/``*.yml`` files' directory ``warmup_memory`` loads; never a caller's path."""

    model_config = ConfigDict(frozen=True)

    path: Path
    # The worker writes every stored item into ``path``.
    dump: bool


class LanceDBSettings(BaseModel):
    """The LanceDB adapter: a directory of tables."""

    model_config = ConfigDict(frozen=True)

    path: Path
    max_small_fragments: int


class QdrantSettings(BaseModel):
    """The Qdrant adapter: ``":memory:"`` or a server URL."""

    model_config = ConfigDict(frozen=True)

    location: str


class VectorStoreSettings(BaseModel):
    """Which adapter stores the points, and that adapter's block."""

    model_config = ConfigDict(frozen=True)

    collection_prefix: str
    backend: Literal["lancedb", "qdrant"]
    lancedb: LanceDBSettings | None = None
    qdrant: QdrantSettings | None = None

    @model_validator(mode="after")
    def _backend_block_present(self) -> Self:
        if getattr(self, self.backend) is None:
            msg = (
                f"vector_store.backend is {self.backend!r} but vector_store.{self.backend} is unset"
            )
            raise ValueError(msg)
        return self


class KnowledgeBaseSettings(BaseSettings):
    """Configuration for the knowledge base."""

    # The input holds api_key: a validation error must not echo it.
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    yaml_directory: ClassVar[Path] = Path(__file__).parent

    queue: QueueSettings
    embeddings: EmbeddingsSettings
    search: SearchSettings
    item_limits: ItemLimitsSettings
    warmup: WarmupSettings
    vector_store: VectorStoreSettings


def get_settings(env: Environment) -> KnowledgeBaseSettings:
    """Load settings for ``env``.

    Example:
        >>> get_settings(Environment.TESTING).vector_store.backend
        'qdrant'
    """
    return load_settings(KnowledgeBaseSettings, env=env)
