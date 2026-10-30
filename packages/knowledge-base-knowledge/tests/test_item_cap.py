"""The configured 500-character cap counts the content."""

from __future__ import annotations

import asyncio

import pytest
from fake_kb import open_fake_kb
from fake_server import serve
from pydantic import ValidationError

from tools_knowledge_base.operations import store_memory
from tools_knowledge_base_knowledge.kind import KnowledgeKind


def test_content_of_exactly_the_cap_is_stored_and_one_more_is_rejected() -> None:
    kb = open_fake_kb(KnowledgeKind())

    assert store_memory(kb, "knowledge", {"category": "fact", "content": "x" * 500}).item_id

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, "knowledge", {"category": "fact", "content": "x" * 501})

    assert caught.value.errors()[0]["msg"] == (
        "knowledge item is 501 characters; the knowledge limit is 500 (counted over content). "
        "Store one fact per item: split it into several store_knowledge calls, "
        "each under the limit."
    )


def test_the_store_knowledge_description_states_the_cap() -> None:
    tools = asyncio.run(serve(open_fake_kb(KnowledgeKind())).list_tools())
    [store] = [tool for tool in tools if tool.name == "store_knowledge"]

    assert (store.description or "").endswith(
        "At most 500 characters in total, counted over content."
    )
