"""The queue's file and name, request status reads, drain's signal handlers, the consumer;
startup refusals and registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, override

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb, stored
from fake_kind import FakeKind
from fake_server import keyed_settings
from huey import MemoryHuey, SqliteHuey  # pyright: ignore[reportMissingTypeStubs]
from huey.consumer import Consumer  # pyright: ignore[reportMissingTypeStubs]
from mcp.server import MCPServer
from stevedore import ExtensionManager

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.operations import get_memory_request, store_memory
from tools_knowledge_base.queue import make_huey, run_consumer
from tools_knowledge_base.registration import register


def test_make_huey_creates_every_missing_directory_of_the_queue_file(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "queue.db"
    config = get_settings(Environment.TESTING).queue.model_copy(update={"path": str(path)})

    make_huey(config)

    assert path.parent.is_dir()


def test_the_queue_file_holds_tasks_another_process_queued_under_the_queue_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "queue.db"
    other = SqliteHuey("knowledge-base", filename=str(path))
    store_memory(open_fake_kb(huey=other), "fake", {"title": "elsewhere", "tags": []})
    config = get_settings(Environment.TESTING).queue.model_copy(update={"path": str(path)})

    assert make_huey(config).pending_count() == 1


def test_the_in_memory_queue_carries_the_queue_name() -> None:
    assert make_huey(get_settings(Environment.TESTING).queue).name == "knowledge-base"


def test_reading_a_queued_requests_status_keeps_it_known() -> None:
    kb = open_fake_kb()
    accepted = store_memory(kb, "fake", {"title": "huey", "tags": []})

    assert get_memory_request(kb, accepted.request_id).status == "queued"
    assert get_memory_request(kb, accepted.request_id).status == "queued"


def _receivers(huey: MemoryHuey) -> int:
    return sum(map(len, huey._signal.receivers.values()))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


def test_drain_leaves_no_signal_handler_behind() -> None:
    kb = open_fake_kb()
    assert isinstance(kb.huey, MemoryHuey)
    before = _receivers(kb.huey)
    stored(kb, "one")

    assert _receivers(kb.huey) == before


class _ProbeConsumer(Consumer):
    ran = False

    @override
    def run(self) -> None:
        self.ran = True


class _ProbeHuey(MemoryHuey):
    """Hands out consumers that record ``run`` instead of blocking."""

    def __init__(self) -> None:
        super().__init__("knowledge-base")  # pyright: ignore[reportUnknownMemberType]
        self.consumers: list[_ProbeConsumer] = []

    @override
    def create_consumer(self, **options: Any) -> _ProbeConsumer:
        consumer = _ProbeConsumer(self, **options)
        self.consumers.append(consumer)
        return consumer


def test_the_consumer_runs_one_worker() -> None:
    huey = _ProbeHuey()

    run_consumer(huey)

    [consumer] = huey.consumers
    assert consumer.ran
    assert consumer.workers == 1


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


def test_without_settings_register_refuses_the_environments_keyless_embedder() -> None:
    """pytest's env pins ``TOOLS_ENV=testing``, whose overlay empties the embedder's key."""
    opened: list[KnowledgeBaseSettings] = []

    def _open(given: KnowledgeBaseSettings) -> KnowledgeBase:
        opened.append(given)
        return open_fake_kb()

    with pytest.raises(KnowledgeBaseError) as raised:
        register(MCPServer("test"), open_kb=_open)

    embeddings = get_settings(Environment.TESTING).embeddings
    embedder = embeddings.active_embedder
    assert str(raised.value) == (
        f"active embedder {embeddings.active!r} ({embedder.model} at {embedder.base_url}) "
        "has an empty api_key: set OPEN_AI_API_KEY"
    )
    assert opened == []


def test_every_refused_tool_name_is_listed() -> None:
    kb = open_fake_kb(FakeKind("memory_request"), FakeKind("bad name"))

    with pytest.raises(KnowledgeBaseError) as raised:
        register(MCPServer("test"), settings=keyed_settings(), open_kb=lambda _settings: kb)

    assert str(raised.value) == (
        "knowledge base tool names refused, repeated: 'get_memory_request'; "
        "not a valid MCP tool name: 'store_bad name', 'update_bad name', 'get_bad name', "
        "'list_bad name', 'delete_bad name'"
    )
