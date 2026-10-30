"""The facade's page size, the default kinds, and the stored-item error's message."""

from __future__ import annotations

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from fake_kind import FakePayload

from knowledge_base_config import Environment
from tools_knowledge_base import api
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import open_knowledge_base
from tools_knowledge_base.errors import StoredItemInvalid, stored_as
from tools_knowledge_base.kinds.registry import load_kinds
from tools_knowledge_base.operations import store_memory
from tools_knowledge_base.queue import drain


def test_the_facade_lists_pages_of_50_by_default() -> None:
    kb = open_fake_kb()
    for i in range(51):
        store_memory(kb, "fake", {"title": f"item {i}", "tags": []})
    drain(kb.huey)

    page = api.items("fake", kb=kb)

    assert len(page.items) == 50
    assert page.next_cursor is not None


def test_opening_without_kinds_loads_every_installed_one() -> None:
    kb = open_knowledge_base(get_settings(Environment.TESTING), embedder=FakeEmbedder())

    assert kb.kinds.names() == load_kinds().names()


def test_a_stored_item_error_names_where_and_the_errors_without_links() -> None:
    with pytest.raises(StoredItemInvalid) as error:
        stored_as(FakePayload, {"title": "sky"}, "item 7")

    message = str(error.value)
    assert message.startswith("item 7: [")
    assert "'tags'" in message
    assert "errors.pydantic.dev" not in message
