"""Search, store, items and re-embed: refusal titles and inputs, the default page size,
re-embed's token boundary, journal and paging."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import override

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb, stored
from fake_kind import FakeKind
from pydantic import ValidationError

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.limits import MAX_LIMIT
from tools_knowledge_base.operations import (
    delete_memory_item,
    list_memory_items,
    reembed_memory,
    search_memory,
    store_memory,
)

KINDS = (FakeKind(), FakeKind("other"))
SOURCE = "memory-fake-a"


def _model_a(settings: KnowledgeBaseSettings) -> KnowledgeBase:
    return open_fake_kb(*KINDS, settings=settings, embedder=FakeEmbedder("fake-a", 8, 16))


def _model_b(settings: KnowledgeBaseSettings) -> KnowledgeBase:
    return open_fake_kb(*KINDS, settings=settings, embedder=FakeEmbedder("fake-b", 12, 4))


class _ShortEmbedder(FakeEmbedder):
    """Returns one vector fewer than it was given texts."""

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return super().embed_documents(texts)[:-1]


@pytest.mark.parametrize(
    ("query", "top_k", "min_score"),
    [(" ", None, None), ("sky", 0, None), ("sky", MAX_LIMIT + 1, None), ("sky", None, math.inf)],
)
def test_search_refusals_are_titled_search_memory(
    query: str, top_k: int | None, min_score: float | None
) -> None:
    with pytest.raises(ValidationError) as refused:
        search_memory(open_fake_kb(), query, top_k=top_k, min_score=min_score)

    assert refused.value.title == "search_memory"


def test_a_non_finite_min_score_is_echoed_as_the_refused_input() -> None:
    with pytest.raises(ValidationError) as refused:
        search_memory(open_fake_kb(), "sky", min_score=math.nan)

    [error] = refused.value.errors()
    assert (error["loc"], math.isnan(error["input"])) == (("min_score",), True)


@pytest.mark.parametrize("limit", [0, MAX_LIMIT + 1])
def test_list_refusals_are_titled_list_memory_items(limit: int) -> None:
    with pytest.raises(ValidationError) as refused:
        list_memory_items(open_fake_kb(), "fake", limit=limit)

    assert refused.value.title == "list_memory_items"


def test_a_list_page_holds_fifty_items_by_default() -> None:
    kb = open_fake_kb()
    for n in range(51):
        stored(kb, f"item{n}")

    page = list_memory_items(kb, "fake")

    assert (len(page.items), page.next_cursor is not None) == (50, True)


def test_an_empty_embed_text_echoes_the_payload_as_the_refused_input() -> None:
    payload: dict[str, object] = {"title": "", "tags": []}

    with pytest.raises(ValidationError) as refused:
        store_memory(open_fake_kb(), "fake", payload)

    [error] = refused.value.errors()
    assert (error["type"], error["loc"], error["input"]) == ("embed_text_rejected", (), payload)


def test_reembed_copies_an_item_of_exactly_the_token_limit(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    four = stored(_model_a(settings), "four", ["a", "b", "c"])

    report = reembed_memory(_model_b(settings), SOURCE)

    assert (report.copied, report.too_long) == (1, [])
    assert [item.id for item in list_memory_items(_model_b(settings), "fake").items] == [
        four.item_id
    ]


def test_reembed_copies_the_items_after_a_too_long_one(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    model_a = _model_a(settings)
    long = stored(model_a, "long", ["one", "two", "three", "four"])
    short = {stored(model_a, f"short{n}").item_id for n in range(8)}

    report = reembed_memory(_model_b(settings), SOURCE)

    assert (report.copied, report.too_long) == (8, [long.item_id])
    assert {item.id for item in list_memory_items(_model_b(settings), "fake").items} == short


def test_reembed_refuses_an_embedder_returning_too_few_vectors(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    stored(_model_a(settings), "sky", ["blue"])
    stored(_model_a(settings), "sea", ["green"])
    model_b = open_fake_kb(*KINDS, settings=settings, embedder=_ShortEmbedder("fake-b", 12, 4))

    with pytest.raises(ValueError, match="zip"):
        reembed_memory(model_b, SOURCE)


def test_a_third_reembed_still_skips_an_item_deleted_after_the_first(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    gone = stored(_model_a(settings), "sea", ["green"])
    model_b = _model_b(settings)
    reembed_memory(model_b, SOURCE)
    delete_memory_item(model_b, "fake", gone.item_id)
    reembed_memory(model_b, SOURCE)

    report = reembed_memory(model_b, SOURCE)

    assert (report.copied, report.skipped_deleted) == (0, 1)
    assert list_memory_items(model_b, "fake").items == []


def test_the_journal_of_one_source_does_not_skip_items_of_another(tmp_path: Path) -> None:
    settings = lancedb_settings(tmp_path)
    sky = stored(_model_a(settings), "sky", ["blue"])
    stored(open_fake_kb(*KINDS, settings=settings, embedder=FakeEmbedder("fake-c")), "sky")
    model_b = _model_b(settings)
    reembed_memory(model_b, SOURCE)
    delete_memory_item(model_b, "fake", sky.item_id)

    report = reembed_memory(model_b, "memory-fake-c")

    assert (report.copied, report.skipped_deleted) == (1, 0)
    assert [item.id for item in list_memory_items(model_b, "fake").items] == [sky.item_id]
