"""Model switch: each fake model has its own collection; re-embed copies A's into B's."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb, stored
from fake_kind import FakeKind, FakePayload

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    list_memory_items,
    reembed_memory,
    search_memory,
    update_memory_item,
)
from tools_knowledge_base.queue import drain
from tools_knowledge_base.store.protocol import Point

KINDS = (FakeKind(), FakeKind("other"))
SOURCE = "memory-fake-a"


def _model_a(settings: KnowledgeBaseSettings) -> KnowledgeBase:
    return open_fake_kb(*KINDS, settings=settings, embedder=FakeEmbedder("fake-a", 8, 16))


def _model_b(settings: KnowledgeBaseSettings) -> KnowledgeBase:
    return open_fake_kb(*KINDS, settings=settings, embedder=FakeEmbedder("fake-b", 12, 4))


def test_items_stored_under_one_model_are_absent_under_another(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    stored(_model_a(settings), "sky", ["blue"])

    assert list_memory_items(_model_b(settings), "fake").items == []


def test_reembed_refuses_a_source_holding_a_kind_not_installed(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    model_a = open_fake_kb(
        *KINDS, FakeKind("gone"), settings=settings, embedder=FakeEmbedder("fake-a", 8, 16)
    )
    stored(model_a, "sky", ["blue"])
    stored(model_a, "old", [], kind="gone")
    stored(model_a, "older", [], kind="gone")
    model_b = _model_b(settings)

    with pytest.raises(KnowledgeBaseError, match=r"'memory-fake-a' .* cannot copy: \{'gone': 2\}"):
        reembed_memory(model_b, SOURCE)

    assert list_memory_items(model_b, "fake").items == []


def test_reembed_copies_every_kind_keeping_ids_and_payloads(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    model_a = _model_a(settings)
    sky = stored(model_a, "sky", ["blue"])
    grass = stored(model_a, "grass", ["green"], kind="other")
    long = stored(model_a, "long", ["one", "two", "three", "four"])
    stored(model_a, "kept", ["from-a"])
    model_b = _model_b(settings)
    kept = stored(model_b, "kept", ["from-b"])

    report = reembed_memory(model_b, SOURCE)

    assert (report.copied, report.skipped_existing, report.too_long) == (2, 1, [long.item_id])
    [hit] = search_memory(model_b, "sky blue", kind="fake", top_k=1)
    assert (hit.id, hit.payload) == (sky.item_id, FakePayload(title="sky", tags=["blue"]))
    assert get_memory_item(model_b, "other", grass.item_id).payload.model_dump()["title"] == (
        "grass"
    )
    assert get_memory_item(model_b, "fake", kept.item_id).payload == FakePayload(
        title="kept", tags=["from-b"]
    )


def test_a_second_reembed_copies_nothing(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    stored(_model_a(settings), "sky", ["blue"])
    embedder_b = FakeEmbedder("fake-b", 12, 4)
    model_b = open_fake_kb(*KINDS, settings=settings, embedder=embedder_b)
    reembed_memory(model_b, SOURCE)
    embedded = len(embedder_b.documents)

    report = reembed_memory(model_b, SOURCE)

    assert (report.copied, report.skipped_existing, report.too_long) == (0, 1, [])
    assert len(embedder_b.documents) == embedded


def test_reembed_rerun_does_not_resurrect_an_item_deleted_between_runs(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    model_a = _model_a(settings)
    kept = stored(model_a, "sky", ["blue"])
    gone = stored(model_a, "sea", ["green"])
    old = stored(model_a, "grass", ["red"])
    model_b = _model_b(settings)
    reembed_memory(model_b, SOURCE)
    delete_memory_item(model_b, "fake", gone.item_id)
    reworded = update_memory_item(model_b, "fake", old.item_id, {"title": "lawn", "tags": []})
    drain(model_b.huey)

    report = reembed_memory(model_b, SOURCE)

    assert (report.copied, report.skipped_existing, report.skipped_deleted) == (0, 1, 2)
    assert {item.id for item in list_memory_items(model_b, "fake").items} == {
        kept.item_id,
        reworded.item_id,
    }


def test_reembed_rerun_does_not_resurrect_an_item_present_before_the_first_run(
    tmp_path: Path,
) -> None:
    settings = lancedb_settings(tmp_path)
    sky = stored(_model_a(settings), "sky", ["blue"])
    model_b = _model_b(settings)
    stored(model_b, "sky", ["blue"])
    reembed_memory(model_b, SOURCE)
    delete_memory_item(model_b, "fake", sky.item_id)

    report = reembed_memory(model_b, SOURCE)

    assert (report.copied, report.skipped_deleted) == (0, 1)
    assert list_memory_items(model_b, "fake").items == []


def test_reembed_rerun_copies_an_item_not_copied_yet(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    model_a = _model_a(settings)
    first = stored(model_a, "sky", ["blue"])
    model_b = _model_b(settings)
    reembed_memory(model_b, SOURCE)
    later = stored(model_a, "sea", ["green"])

    report = reembed_memory(model_b, SOURCE)

    assert (report.copied, report.skipped_existing, report.skipped_deleted) == (1, 1, 0)
    assert {item.id for item in list_memory_items(model_b, "fake").items} == {
        first.item_id,
        later.item_id,
    }


def test_reembed_pages_through_more_than_one_batch(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    model_a = _model_a(settings)
    now = datetime.now(UTC)
    model_a.store.upsert(
        [
            Point(
                id=uuid4(),
                kind="fake",
                updated_at=now,
                payload={"title": f"item{n}", "tags": []},
                vector=model_a.embedder.embed_query(f"item{n}"),
            )
            for n in range(33)
        ]
    )
    embedder = FakeEmbedder("fake-b", 12, 4)

    report = reembed_memory(open_fake_kb(*KINDS, settings=settings, embedder=embedder), SOURCE)

    assert report.copied == 33
    # TEI rejects more than 32 inputs a request.
    assert embedder.batch_sizes == [32, 1]


def test_reembed_from_a_missing_collection_is_refused(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError, match="'memory-nope' does not exist"):
        reembed_memory(_model_b(lancedb_settings(tmp_path)), "memory-nope")
