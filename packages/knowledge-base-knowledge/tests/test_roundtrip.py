"""The knowledge kind through the whole flow: store -> worker -> search -> delete."""

from __future__ import annotations

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakePayload
from pydantic import ValidationError

from tools_knowledge_base.errors import ItemNotFound
from tools_knowledge_base.kinds.registry import load_kinds
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    get_memory_request,
    search_memory,
    store_memory,
    update_memory_item,
)
from tools_knowledge_base.queue import drain
from tools_knowledge_base_knowledge.kind import KnowledgeKind, KnowledgePayload


def test_the_installed_entry_point_loads_the_knowledge_kind() -> None:
    kind = load_kinds().get("knowledge")

    assert isinstance(kind, KnowledgeKind)
    assert kind.payload_model is KnowledgePayload


def test_a_fact_is_stored_found_and_deleted() -> None:
    kb = open_fake_kb(KnowledgeKind())
    fact = {"category": "fact", "content": "the sky is blue"}

    accepted = store_memory(kb, "knowledge", fact)
    assert drain(kb.huey) == (1, 0)
    assert get_memory_request(kb, accepted.request_id).status == "done"

    [hit] = search_memory(kb, "sky blue", kind="knowledge")
    assert hit.id == accepted.item_id
    assert hit.payload == KnowledgePayload(category="fact", content="the sky is blue")

    delete_memory_item(kb, "knowledge", accepted.item_id)
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "knowledge", accepted.item_id)


def test_the_content_is_the_key_so_a_category_edit_stays_and_a_reword_moves() -> None:
    kb = open_fake_kb(KnowledgeKind())
    first = store_memory(kb, "knowledge", {"category": "fact", "content": "tea at five"})
    assert drain(kb.huey) == (1, 0)

    kept = update_memory_item(
        kb, "knowledge", first.item_id, {"category": "preference", "content": "tea at five"}
    )
    assert drain(kb.huey) == (1, 0)
    moved = update_memory_item(
        kb, "knowledge", first.item_id, {"category": "preference", "content": "tea at six"}
    )
    assert drain(kb.huey) == (1, 0)

    assert kept.item_id == first.item_id
    assert moved.item_id != first.item_id
    assert get_memory_item(kb, "knowledge", moved.item_id).payload == KnowledgePayload(
        category="preference", content="tea at six"
    )
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "knowledge", first.item_id)


def test_a_bad_category_fails_at_enqueue() -> None:
    kb = open_fake_kb(KnowledgeKind())

    with pytest.raises(ValidationError):
        store_memory(kb, "knowledge", {"category": "rumour", "content": "x"})

    assert kb.huey.pending_count() == 0


def test_render_and_embed_text() -> None:
    kind = KnowledgeKind()
    payload = KnowledgePayload(category="goal", content="run a marathon")

    assert kind.render(payload) == "[goal] run a marathon"
    assert kind.embed_text(payload) == kind.key(payload) == "run a marathon"


def test_another_kinds_payload_is_refused() -> None:
    with pytest.raises(TypeError, match="got a FakePayload payload"):
        KnowledgeKind().key(FakePayload(title="t", tags=[]))
