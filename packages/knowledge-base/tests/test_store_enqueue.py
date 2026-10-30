"""``store_memory`` validates at request time and only enqueues: the worker embeds."""

from __future__ import annotations

from uuid import uuid5

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from fake_kind import FakeKind, FakePayload
from pydantic import ValidationError

from tools_knowledge_base.errors import UnknownKind
from tools_knowledge_base.operations import list_memory_kinds, store_memory
from tools_knowledge_base.operations.store import KB_NAMESPACE


def test_store_returns_queued_with_the_key_derived_id_and_embeds_nothing() -> None:
    embedder = FakeEmbedder()
    kb = open_fake_kb(embedder=embedder)

    accepted = store_memory(kb, "fake", {"title": "huey", "tags": ["queue"]})

    assert accepted.status == "queued"
    assert accepted.item_id == uuid5(KB_NAMESPACE, "fake:huey")
    assert accepted.request_id
    assert kb.huey.pending_count() == 1
    assert embedder.documents == []
    assert kb.store.get([accepted.item_id]) == []


def test_restoring_a_key_addresses_the_same_item() -> None:
    kb = open_fake_kb()

    first = store_memory(kb, "fake", {"title": "huey", "tags": []})
    second = store_memory(kb, "fake", {"title": "huey", "tags": ["again"]})

    assert first.item_id == second.item_id
    assert first.request_id != second.request_id


def test_the_kind_name_is_part_of_the_id() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("other"))

    fake = store_memory(kb, "fake", {"title": "same", "tags": []})
    other = store_memory(kb, "other", {"title": "same", "tags": []})

    assert fake.item_id != other.item_id


def test_an_unknown_kind_fails_before_enqueue() -> None:
    kb = open_fake_kb()

    with pytest.raises(UnknownKind, match="'nope'"):
        store_memory(kb, "nope", {"title": "t", "tags": []})

    assert kb.huey.pending_count() == 0


def test_a_malformed_payload_fails_before_enqueue() -> None:
    kb = open_fake_kb()

    with pytest.raises(ValidationError, match="tags"):
        store_memory(kb, "fake", {"title": "t"})

    assert kb.huey.pending_count() == 0


def test_an_empty_embed_text_is_one_validation_error_at_the_root() -> None:
    kb = open_fake_kb()

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, "fake", {"title": " ", "tags": []})

    [error] = caught.value.errors()
    assert error["type"] == "embed_text_rejected"
    assert error["loc"] == ()
    assert error["msg"] == "embed text is empty"
    assert caught.value.title == FakePayload.__name__
    assert kb.huey.pending_count() == 0


def test_an_embed_text_over_the_token_limit_is_rejected() -> None:
    kb = open_fake_kb()
    # One title word plus 16 tags is 17 tokens; the fake embedder takes 16.
    payload = {"title": "long", "tags": [f"t{i}" for i in range(16)]}

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, "fake", payload)

    [error] = caught.value.errors()
    assert error["type"] == "embed_text_rejected"
    assert error["msg"] == "embed text is 17 tokens, over the embedder's 16"


def test_an_embed_text_at_the_token_limit_is_accepted() -> None:
    kb = open_fake_kb()

    accepted = store_memory(kb, "fake", {"title": "full", "tags": [f"t{i}" for i in range(15)]})

    assert accepted.status == "queued"


def test_list_memory_kinds_gives_each_payload_schema() -> None:
    kb = open_fake_kb(FakeKind("zeta"), FakeKind("alpha"))

    schemas = list_memory_kinds(kb)

    assert [schema.name for schema in schemas] == ["alpha", "zeta"]
    assert schemas[0].payload_schema == FakePayload.model_json_schema()
    assert schemas[0].payload_schema["required"] == ["title", "tags"]
