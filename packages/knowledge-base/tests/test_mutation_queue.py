"""Request status reads, the opener's defaults, startup refusals and registration."""

from __future__ import annotations

import threading
import time

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import fake_registry, open_fake_kb, temp_sqlite_settings
from fake_kind import FakeKind
from fake_server import call_error, keyed_settings
from mcp.server import MCPServer
from stevedore import ExtensionManager

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry, load_kinds
from tools_knowledge_base.operations import get_memory_request, store_memory
from tools_knowledge_base.registration import register
from tools_knowledge_base.write_queue import THREAD_NAME, WriteQueue


def _threads() -> int:
    return sum(1 for thread in threading.enumerate() if thread.name == THREAD_NAME)


def test_reading_a_queued_requests_status_keeps_it_known() -> None:
    kb = open_fake_kb()
    accepted = store_memory(kb, "fake", {"title": "celery", "tags": []})

    assert get_memory_request(kb, accepted.request_id).status == "queued"
    assert get_memory_request(kb, accepted.request_id).status == "queued"


def test_a_default_opened_kb_sleeps_with_time_and_starts_its_thread_on_the_first_store() -> None:
    kb = open_knowledge_base(temp_sqlite_settings(), embedder=FakeEmbedder(), kinds=fake_registry())
    before = _threads()

    assert kb.sleep is time.sleep
    assert _threads() == before
    accepted = store_memory(kb, "fake", {"title": "first", "tags": []})
    kb.writes.drain()

    assert _threads() == before + 1
    assert get_memory_request(kb, accepted.request_id).status == "done"


def test_a_given_write_queue_is_the_one_the_opened_kb_uses() -> None:
    writes = WriteQueue(background=False)
    kb = open_knowledge_base(
        temp_sqlite_settings(), writes=writes, embedder=FakeEmbedder(), kinds=fake_registry()
    )

    assert kb.writes is writes


def test_registering_opens_no_thread_and_reports_the_writes_still_queued() -> None:
    kb = open_fake_kb(FakeKind("alpha"))
    before = _threads()

    registered = register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _s: kb)

    assert _threads() == before
    assert registered.queued() == 0
    store_memory(kb, "alpha", {"title": "first", "tags": []})
    assert registered.queued() == 1
    kb.writes.drain()
    assert registered.queued() == 0


def test_without_kinds_open_knowledge_base_loads_every_installed_kind() -> None:
    kb = open_knowledge_base(temp_sqlite_settings(), embedder=FakeEmbedder())

    assert kb.kinds.names() == load_kinds().names()


def test_no_installed_kind_names_the_package_to_install() -> None:
    empty = KindRegistry(ExtensionManager[MemoryKind].make_test_instance([]))
    kb = open_knowledge_base(keyed_settings(), embedder=FakeEmbedder(), kinds=empty)

    with pytest.raises(KnowledgeBaseError) as raised:
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)

    assert str(raised.value) == (
        "no memory kinds installed: install a kind package, such as tools-knowledge-base-knowledge"
    )


def test_open_kb_receives_the_settings_register_was_given() -> None:
    settings = keyed_settings()
    opened: list[KnowledgeBaseSettings] = []

    def _open(given: KnowledgeBaseSettings) -> KnowledgeBase:
        opened.append(given)
        return open_fake_kb()

    register(MCPServer("test"), settings=settings, open_kb=_open)

    assert opened == [settings]


def test_without_settings_register_opens_the_environments_keyless_embedder_and_its_call_fails() -> (
    None
):
    """pytest's env pins ``TOOLS_ENV=testing``, whose overlay empties the embedder's key."""
    opened: list[KnowledgeBaseSettings] = []

    def _open(given: KnowledgeBaseSettings) -> KnowledgeBase:
        opened.append(given)
        return open_knowledge_base(given, kinds=fake_registry())

    server = MCPServer("test")
    register(server, open_kb=_open)

    settings = get_settings(Environment.TESTING)
    assert opened == [settings]
    embeddings = settings.embeddings
    embedder = embeddings.active_embedder
    assert call_error(server, "store_fake", title="sky", tags=[]) == (
        f"active embedder {embeddings.active!r} ({embedder.model} at {embedder.base_url}) "
        "has an empty api_key: set OPEN_AI_API_KEY "
        "in the environment or in /nonexistent/kb-testing/.env"
    )


def test_every_refused_tool_name_is_listed() -> None:
    kb = open_fake_kb(FakeKind("memory_request"), FakeKind("bad name"))

    with pytest.raises(KnowledgeBaseError) as raised:
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)

    assert str(raised.value) == (
        "knowledge base tool names refused, repeated: 'get_memory_request'; "
        "not a valid MCP tool name: 'store_bad name', 'update_bad name', 'get_bad name', "
        "'list_bad name', 'delete_bad name'"
    )
