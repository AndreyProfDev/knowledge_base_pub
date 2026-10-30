from __future__ import annotations

import json

import httpx2
import pytest
import tiktoken
from pydantic import SecretStr
from tokenizers import Tokenizer

from tools_knowledge_base.configs.settings import EmbedderSettings
from tools_knowledge_base.embeddings import OpenAIEmbedder
from tools_knowledge_base.errors import KnowledgeBaseError

_CONFIG = EmbedderSettings(
    base_url="https://embeddings.invalid/v1",
    model="e5-test",
    dimensions=3,
    max_input_tokens=8,
    tokenizer="tiktoken",
    document_prefix="passage: ",
    query_prefix="query: ",
    min_score=0.5,
    api_key=SecretStr("test-key"),
)

# One token per byte: no download, and a count that is easy to read off. The special
# token makes ``encode`` raise on it, as a real tiktoken encoding does.
_BYTES = tiktoken.Encoding(
    name="bytes",
    pat_str=r"\S+|\s+",
    mergeable_ranks={bytes([i]): i for i in range(256)},
    special_tokens={"<|endoftext|>": 256},
)


def _no_hub(model: str) -> Tokenizer:
    """A tiktoken embedder that reaches for a Hub tokenizer fails here, not on the network."""
    pytest.fail(f"tiktoken config loaded the Hub tokenizer {model!r}")


class _Server:
    """Answers ``/v1/embeddings`` with one vector of ``length`` per input."""

    def __init__(self, length: int = 3, *, reverse: bool = False, drop: int = 0) -> None:
        self.length = length
        self.reverse = reverse
        self.drop = drop
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        inputs: list[str] = json.loads(request.content)["input"]
        data = [
            {"object": "embedding", "index": i, "embedding": [float(i + 1)] * self.length}
            for i in range(len(inputs) - self.drop)
        ]
        if self.reverse:
            data.reverse()
        usage = {"prompt_tokens": 1, "total_tokens": 1}
        return httpx2.Response(
            200, json={"object": "list", "data": data, "model": "e5-test", "usage": usage}
        )

    def body(self, index: int = -1) -> dict[str, object]:
        return json.loads(self.requests[index].content)


def _embedder(server: _Server, config: EmbedderSettings = _CONFIG) -> OpenAIEmbedder:
    http_client = httpx2.Client(transport=httpx2.MockTransport(server))
    return OpenAIEmbedder(config, http_client=http_client, encoding=_BYTES, load_tokenizer=_no_hub)


def test_documents_go_to_the_configured_server_prefixed_with_dimensions() -> None:
    server = _Server()

    vectors = _embedder(server).embed_documents(["sky", "sea"])

    assert vectors == [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]]
    assert str(server.requests[0].url) == "https://embeddings.invalid/v1/embeddings"
    assert server.requests[0].headers["authorization"] == "Bearer test-key"
    body = server.body()
    assert body["model"] == "e5-test"
    assert body["dimensions"] == 3
    assert body["input"] == ["passage: sky", "passage: sea"]


def test_a_query_takes_the_query_prefix() -> None:
    server = _Server()

    assert _embedder(server).embed_query("sky") == [1.0, 1.0, 1.0]
    assert server.body()["input"] == ["query: sky"]


def test_vectors_out_of_order_are_put_back_in_input_order() -> None:
    vectors = _embedder(_Server(reverse=True)).embed_documents(["sky", "sea"])

    assert vectors == [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]]


def test_fewer_vectors_than_inputs_raises() -> None:
    with pytest.raises(KnowledgeBaseError, match=r"answered 2 inputs with 1 embeddings at .*\[0\]"):
        _embedder(_Server(drop=1)).embed_documents(["sky", "sea"])


def test_an_empty_api_key_is_refused_before_any_request() -> None:
    server = _Server()
    keyless_config = _CONFIG.model_copy(update={"api_key": SecretStr("")})
    # Builds without a request or a raise, so keyless get/list/delete can open the base.
    assert OpenAIEmbedder(keyless_config).vector_space == "e5-test-3"
    keyless = _embedder(server, keyless_config)

    with pytest.raises(KnowledgeBaseError, match=r"e5-test at https://embeddings.invalid/v1"):
        keyless.count_tokens("sky")
    with pytest.raises(KnowledgeBaseError, match="has no api_key"):
        keyless.embed_query("sky")
    assert server.requests == []


def test_a_vector_of_the_wrong_length_raises() -> None:
    with pytest.raises(KnowledgeBaseError, match=r"returned a 4-dimension vector; configured .* 3"):
        _embedder(_Server(length=4)).embed_documents(["sky"])


def test_tokens_are_counted_on_the_prefixed_document() -> None:
    embedder = _embedder(_Server())

    assert embedder.count_tokens("sky") == len("passage: sky")
    assert embedder.count_tokens("<|endoftext|>") == len("passage: <|endoftext|>")


def test_the_embedder_carries_its_settings() -> None:
    embedder = _embedder(_Server())

    assert embedder.vector_space == "e5-test-3"
    assert (embedder.dimensions, embedder.max_input_tokens, embedder.min_score) == (3, 8, 0.5)


def test_a_refused_request_is_a_knowledge_base_error() -> None:
    def refuse(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "invalid api key"}})

    http_client = httpx2.Client(transport=httpx2.MockTransport(refuse))
    embedder = OpenAIEmbedder(_CONFIG, http_client=http_client, encoding=_BYTES)

    with pytest.raises(KnowledgeBaseError, match=r"e5-test at .* failed: .*401") as raised:
        embedder.embed_query("sky")

    assert "test-key" not in str(raised.value)
