"""The worker embeds and upserts queued writes; search, get, list and delete read them."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import override
from uuid import uuid4

import click
import pytest
from fake_embedder import FakeEmbedder
from fake_kb import fake_registry, open_fake_kb
from fake_kind import FakeKind, FakePayload
from huey import Huey, MemoryHuey, SqliteHuey  # pyright: ignore[reportMissingTypeStubs]
from huey.storage import SqliteStorage  # pyright: ignore[reportMissingTypeStubs]
from stevedore import ExtensionManager

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import ItemNotFound, KnowledgeBaseError, UnknownKind
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    list_memory_items,
    search_memory,
    store_memory,
)
from tools_knowledge_base.queue import drain, make_huey
from tools_knowledge_base.worker import run_worker


def _stored(kb: KnowledgeBase, title: str, tags: list[str], kind: str = "fake") -> None:
    store_memory(kb, kind, {"title": title, "tags": tags})


def test_draining_embeds_the_kind_text_and_stores_the_item() -> None:
    embedder = FakeEmbedder()
    kb = open_fake_kb(embedder=embedder)
    accepted = store_memory(kb, "fake", {"title": "huey", "tags": ["queue", "sqlite"]})

    assert drain(kb.huey) == (1, 0)

    assert embedder.documents == ["huey queue sqlite"]
    item = get_memory_item(kb, "fake", accepted.item_id)
    assert item.payload == FakePayload(title="huey", tags=["queue", "sqlite"])
    assert item.kind == "fake"
    assert drain(kb.huey) == (0, 0)


def test_two_queued_writes_of_one_key_leave_one_item_the_last_requested() -> None:
    kb = open_fake_kb()
    _stored(kb, "huey", ["first"])
    _stored(kb, "huey", ["second"])

    drain(kb.huey)

    page = list_memory_items(kb, "fake")
    assert [item.payload for item in page.items] == [FakePayload(title="huey", tags=["second"])]


def test_search_ranks_by_shared_words_and_scopes_to_a_kind() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("other"))
    _stored(kb, "queue", ["huey", "sqlite"])
    _stored(kb, "vectors", ["qdrant", "cosine"])
    _stored(kb, "queue", ["huey"], kind="other")
    drain(kb.huey)

    every = search_memory(kb, "huey sqlite queue")
    scoped = search_memory(kb, "huey sqlite queue", kind="fake", top_k=1)

    assert [(hit.kind, hit.payload.model_dump()["title"]) for hit in every[:2]] == [
        ("fake", "queue"),
        ("other", "queue"),
    ]
    assert every[0].score == pytest.approx(1.0)
    assert len(every) == 3
    assert [(hit.kind, hit.score) for hit in scoped] == [("fake", every[0].score)]


def test_search_takes_the_settings_top_k_and_an_explicit_floor() -> None:
    kb = open_fake_kb()
    for index in range(kb.settings.search.top_k + 1):
        _stored(kb, f"item{index}", [])
    drain(kb.huey)

    assert len(search_memory(kb, "item0")) == kb.settings.search.top_k
    assert [hit.score for hit in search_memory(kb, "item0", min_score=0.99)] == [pytest.approx(1.0)]


def test_search_defaults_to_the_embedders_floor() -> None:
    kb = open_fake_kb(embedder=FakeEmbedder(min_score=0.99))
    _stored(kb, "alpha", [])
    _stored(kb, "beta", [])
    drain(kb.huey)

    assert len(search_memory(kb, "alpha")) == 1


def test_a_kind_no_longer_installed_takes_none_of_the_top_k_places() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("gone"))
    _stored(kb, "sky green", [])
    _stored(kb, "sky blue", [], kind="gone")
    drain(kb.huey)
    reopened = dataclasses.replace(kb, kinds=fake_registry(FakeKind("fake")))

    [hit] = search_memory(reopened, "sky blue", top_k=1)
    assert hit.kind == "fake"


def test_search_with_no_kind_installed_finds_nothing() -> None:
    kb = open_fake_kb()
    _stored(kb, "sky", [])
    drain(kb.huey)
    empty = KindRegistry(ExtensionManager[MemoryKind].make_test_instance([]))

    assert search_memory(dataclasses.replace(kb, kinds=empty), "sky") == []


def test_search_of_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(UnknownKind):
        search_memory(open_fake_kb(), "anything", kind="nope")


def test_list_pages_with_the_cursor() -> None:
    kb = open_fake_kb()
    for title in ("a", "b", "c"):
        _stored(kb, title, [])
    drain(kb.huey)

    first = list_memory_items(kb, "fake", limit=2)
    assert first.next_cursor is not None
    rest = list_memory_items(kb, "fake", limit=2, cursor=first.next_cursor)

    titles = {item.payload.model_dump()["title"] for item in [*first.items, *rest.items]}
    assert titles == {"a", "b", "c"}
    assert rest.next_cursor is None
    with pytest.raises(UnknownKind):
        list_memory_items(kb, "nope")


def test_delete_removes_the_item_and_rejects_other_kinds_ids() -> None:
    kb = open_fake_kb(FakeKind("fake"), FakeKind("other"))
    kept = store_memory(kb, "other", {"title": "kept", "tags": []})
    gone = store_memory(kb, "fake", {"title": "gone", "tags": []})
    drain(kb.huey)

    with pytest.raises(ItemNotFound, match=f"no fake item has id {kept.item_id}"):
        delete_memory_item(kb, "fake", kept.item_id)
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "fake", kept.item_id)
    delete_memory_item(kb, "fake", gone.item_id)

    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "fake", gone.item_id)
    with pytest.raises(ItemNotFound):
        delete_memory_item(kb, "fake", uuid4())
    assert get_memory_item(kb, "other", kept.item_id).payload.model_dump()["title"] == "kept"


def test_drain_runs_a_retry_already_due() -> None:
    kb = open_fake_kb()
    due = datetime.now(UTC) - timedelta(seconds=1)
    task = kb.write_memory.s(  # pyright: ignore[reportUnknownMemberType]
        "fake", str(uuid4()), {"title": "late", "tags": []}, due.isoformat(), eta=due
    )
    kb.huey.add_schedule(task)  # pyright: ignore[reportUnknownMemberType]

    assert drain(kb.huey) == (1, 0)
    assert list_memory_items(kb, "fake").items[0].payload.model_dump()["title"] == "late"


def test_make_huey_opens_the_queue_file_creating_its_directory(tmp_path: Path) -> None:
    settings = get_settings(Environment.TESTING)
    path = tmp_path / "data" / "queue.db"
    config = settings.queue.model_copy(update={"path": str(path)})

    huey = make_huey(config)
    kb = open_fake_kb(huey=huey)
    _stored(kb, "on disk", [])

    assert isinstance(huey, SqliteHuey)
    assert path.is_file()
    assert huey.store_intermediate_errors is False
    assert drain(huey) == (1, 0)
    assert len(list_memory_items(kb, "fake").items) == 1


def test_make_huey_keeps_an_in_memory_queue_in_process() -> None:
    huey = make_huey(get_settings(Environment.TESTING).queue)

    assert isinstance(huey, MemoryHuey)
    assert huey.store_intermediate_errors is False


def test_the_queue_settings_reach_the_sqlite_file_and_the_write_task(tmp_path: Path) -> None:
    queue = get_settings(Environment.TESTING).queue
    config = queue.model_copy(update={"path": str(tmp_path / "q.db"), "timeout_seconds": 7})
    huey = make_huey(config)
    task = open_fake_kb(huey=huey).write_memory.s("fake", "id", {}, "at")  # pyright: ignore[reportUnknownMemberType]

    assert isinstance(huey.storage, SqliteStorage)  # pyright: ignore[reportUnknownMemberType]
    assert huey.storage._timeout == 7
    assert (task.retries, task.retry_backoff) == (queue.retries, queue.retry_backoff)


def test_run_worker_once_drains_otherwise_runs_the_consumer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    kb = open_fake_kb()
    _stored(kb, "one", [])
    consumed: list[Huey] = []

    run_worker(kb, once=True, run=consumed.append)
    assert capsys.readouterr().out == "ran 1 task(s), 0 failed\n"
    assert consumed == []
    run_worker(kb, once=False, run=consumed.append)
    assert consumed == [kb.huey]
    assert capsys.readouterr().out == ""


class _DownEmbedder(FakeEmbedder):
    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        msg = "embeddings server unreachable"
        raise KnowledgeBaseError(msg)


def test_run_worker_once_counts_failed_tasks_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    testing = get_settings(Environment.TESTING)
    # Each retry is due at once, so the drain runs them all.
    queue = testing.queue.model_copy(update={"retry_delay_seconds": 0})
    kb = open_fake_kb(
        embedder=_DownEmbedder(), settings=testing.model_copy(update={"queue": queue})
    )
    _stored(kb, "one", [])

    with pytest.raises(click.exceptions.Exit) as exit_info:
        run_worker(kb, once=True)

    assert exit_info.value.exit_code == 1
    retries = queue.retries
    assert capsys.readouterr().out == f"ran {retries + 1} task(s), {retries + 1} failed\n"
