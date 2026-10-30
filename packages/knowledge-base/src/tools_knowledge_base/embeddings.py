"""``Embedder`` and its one implementation, the OpenAI-compatible ``/v1/embeddings`` client."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cached_property
from typing import TYPE_CHECKING, Protocol

import tiktoken
from openai import OpenAI, OpenAIError
from tokenizers import Tokenizer

from tools_knowledge_base.configs.settings import EmbedderSettings
from tools_knowledge_base.errors import KnowledgeBaseError

if TYPE_CHECKING:
    import httpx2


class Embedder(Protocol):
    """One embedding model; ``vector_space`` names its collection."""

    vector_space: str
    dimensions: int
    max_input_tokens: int
    min_score: float | None

    def count_tokens(self, text: str) -> int:
        """Tokens in ``text`` as a document, its prefix included.

        Raises:
            KnowledgeBaseError: the embedder has no key, so no write may be accepted.
        """
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, each with the document prefix prepended.

        Raises:
            KnowledgeBaseError: no key, or the embedding server refused or failed.
        """
        ...

    def embed_query(self, text: str) -> list[float]:
        """The vector of ``text`` with the query prefix prepended.

        Raises:
            KnowledgeBaseError: no key, or the embedding server refused or failed.
        """
        ...


class OpenAIEmbedder:
    """An OpenAI-compatible server (OpenAI, TEI), counted with tiktoken or a Hub tokenizer."""

    def __init__(
        self,
        config: EmbedderSettings,
        *,
        http_client: httpx2.Client | None = None,
        encoding: tiktoken.Encoding | None = None,
        load_tokenizer: Callable[[str], Tokenizer] = Tokenizer.from_pretrained,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._injected_encoding = encoding
        self._load_tokenizer = load_tokenizer
        self.vector_space = f"{config.model}-{config.dimensions}"
        self.dimensions = config.dimensions
        self.max_input_tokens = config.max_input_tokens
        self.min_score = config.min_score

    @cached_property
    def _encoding(self) -> tiktoken.Encoding:
        # Loaded on first count, not at construction: the first load downloads.
        return self._injected_encoding or tiktoken.encoding_for_model(self._config.model)

    @cached_property
    def _hf_tokenizer(self) -> Tokenizer:
        # The Hub repo's own tokenizer.json, which TEI tokenizes with too; fetched once.
        # Tests inject the loader, so the settings below are applied to their tokenizer too.
        tokenizer = self._load_tokenizer(self._config.model)
        # A repo's tokenizer.json may enable truncation or padding: either would make
        # count_tokens report the clipped or padded length, not the document's, and the
        # max_input_tokens guard would pass an over-long input or refuse a short one.
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return tokenizer

    @cached_property
    def _client(self) -> OpenAI:
        # Built on first embed, after _require_key: an empty key makes OpenAI() raise (or
        # read OPENAI_API_KEY instead), and get/list/delete must open without a key.
        # Tests inject only the transport, so base_url and api_key are still read here.
        return OpenAI(
            base_url=self._config.base_url,
            api_key=self._config.api_key.get_secret_value(),
            http_client=self._http_client,
        )

    def _require_key(self) -> None:
        """Refuse an empty key before any request, and before a write is accepted."""
        if not self._config.api_key.get_secret_value():
            msg = (
                f"embedder {self._config.model} at {self._config.base_url} has no api_key: "
                "set OPEN_AI_API_KEY"
            )
            raise KnowledgeBaseError(msg)

    def count_tokens(self, text: str) -> int:
        """Tokens in the prefixed document, as the configured ``tokenizer`` counts them.

        tiktoken's ``encode_ordinary`` never raises on specials; a Hub tokenizer counts
        its special tokens (``add_special_tokens`` defaults on), as the server does.
        Every write counts before it is queued, so this is where a keyless embedder is
        refused: ``KnowledgeBaseError`` here, not a 401 in the worker.

        Raises:
            KnowledgeBaseError: ``api_key`` is empty.
        """
        self._require_key()
        document = self._config.document_prefix + text
        if self._config.tokenizer == "huggingface":
            return len(self._hf_tokenizer.encode(document).ids)
        return len(self._encoding.encode_ordinary(document))

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` as documents in one request."""
        return self._embed([self._config.document_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        """Embed ``text`` as a query."""
        return self._embed([self._config.query_prefix + text])[0]

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        self._require_key()
        try:
            response = self._client.embeddings.create(
                model=self._config.model, input=inputs, dimensions=self._config.dimensions
            )
        except OpenAIError as exc:
            # A refused key, an unreachable server, a rejected input: typed as this
            # package's error, so the CLI exits 1 with the message instead of a traceback.
            msg = f"embedder {self._config.model} at {self._config.base_url} failed: {exc}"
            raise KnowledgeBaseError(msg) from exc
        data = sorted(response.data, key=lambda item: item.index)
        indexes = [item.index for item in data]
        if indexes != list(range(len(inputs))):
            msg = (
                f"{self._config.model} answered {len(inputs)} inputs with "
                f"{len(data)} embeddings at indexes {indexes}"
            )
            raise KnowledgeBaseError(msg)
        vectors = [item.embedding for item in data]
        for vector in vectors:
            if len(vector) != self.dimensions:
                msg = (
                    f"{self._config.model} returned a {len(vector)}-dimension vector; "
                    f"configured dimensions is {self.dimensions}"
                )
                raise KnowledgeBaseError(msg)
        return vectors
