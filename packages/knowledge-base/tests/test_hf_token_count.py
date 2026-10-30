"""``tokenizer: huggingface`` counts with a Hub tokenizer, special tokens included."""

from __future__ import annotations

from pydantic import SecretStr
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from tokenizers.processors import TemplateProcessing

from tools_knowledge_base.configs.settings import EmbedderSettings
from tools_knowledge_base.embeddings import OpenAIEmbedder

_UNKNOWN = "[UNK]"
_VOCAB = {_UNKNOWN: 0, "[CLS]": 1, "[SEP]": 2, "hello": 3, "world": 4, "passage": 5, ":": 6}


def _tokenizer() -> Tokenizer:
    # In memory, no download: one token per word, wrapped in [CLS] ... [SEP] as BERT is.
    tokenizer = Tokenizer(WordLevel(_VOCAB, unk_token=_UNKNOWN))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.post_processor = TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    return tokenizer


def _embedder(
    document_prefix: str = "", tokenizer: Tokenizer | None = None, loads: list[str] | None = None
) -> OpenAIEmbedder:
    config = EmbedderSettings(
        base_url="http://embeddings.invalid/v1",
        model="hf-test",
        dimensions=3,
        max_input_tokens=8,
        tokenizer="huggingface",
        document_prefix=document_prefix,
        api_key=SecretStr("unused"),
    )
    loaded = _tokenizer() if tokenizer is None else tokenizer

    def load(model: str) -> Tokenizer:
        assert model == "hf-test"
        if loads is not None:
            loads.append(model)
        return loaded

    return OpenAIEmbedder(config, load_tokenizer=load)


def test_special_tokens_are_counted() -> None:
    assert _embedder().count_tokens("hello world") == 4


def test_the_tokenizer_is_loaded_once() -> None:
    loads: list[str] = []
    embedder = _embedder(loads=loads)
    embedder.count_tokens("hello")
    embedder.count_tokens("world")
    assert loads == ["hf-test"]


def test_the_document_prefix_is_counted() -> None:
    assert _embedder("passage: ").count_tokens("hello world") == 6


def test_a_truncating_tokenizer_still_counts_the_whole_document() -> None:
    truncating = _tokenizer()
    truncating.enable_truncation(max_length=3)  # pyright: ignore[reportUnknownMemberType]
    assert _embedder(tokenizer=truncating).count_tokens("hello world") == 4


def test_a_padding_tokenizer_still_counts_only_the_document() -> None:
    padding = _tokenizer()
    padding.enable_padding(length=16)  # pyright: ignore[reportUnknownMemberType]
    assert _embedder(tokenizer=padding).count_tokens("hello world") == 4
