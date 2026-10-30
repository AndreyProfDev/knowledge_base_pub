"""A page size or ``top_k`` outside ``1..MAX_LIMIT``, a blank query or a non-finite
``min_score`` is refused before it reaches either adapter."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fake_kb import lancedb_settings, open_fake_kb, stored
from pydantic import ValidationError

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, get_settings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations import MAX_LIMIT, list_memory_items, search_memory


@pytest.fixture(params=["qdrant", "lancedb"])
def kb(request: pytest.FixtureRequest, tmp_path: Path) -> KnowledgeBase:
    # The testing overlay is qdrant :memory:; lancedb gets its own directory.
    settings = lancedb_settings(tmp_path) if request.param == "lancedb" else None
    kb = open_fake_kb(settings=settings)
    stored(kb, "sky")
    return kb


def _refusal(raised: pytest.ExceptionInfo[ValidationError]) -> tuple[str, tuple[str, ...], object]:
    [error] = raised.value.errors()
    return error["type"], tuple(str(part) for part in error["loc"]), error["input"]


@pytest.mark.parametrize("limit", [0, -1])
def test_a_list_limit_below_one_is_a_validation_error(kb: KnowledgeBase, limit: int) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1") as raised:
        list_memory_items(kb, "fake", limit=limit)

    assert _refusal(raised) == ("greater_than_equal", ("limit",), limit)


@pytest.mark.parametrize("top_k", [0, -1])
def test_a_search_top_k_below_one_is_a_validation_error(kb: KnowledgeBase, top_k: int) -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1") as raised:
        search_memory(kb, "sky", top_k=top_k)

    assert _refusal(raised) == ("greater_than_equal", ("top_k",), top_k)


def test_a_list_limit_above_the_maximum_is_a_validation_error(kb: KnowledgeBase) -> None:
    with pytest.raises(ValidationError) as raised:
        list_memory_items(kb, "fake", limit=2**63 - 1)

    assert _refusal(raised) == ("less_than_equal", ("limit",), 2**63 - 1)


def test_a_search_top_k_above_the_maximum_is_a_validation_error(kb: KnowledgeBase) -> None:
    with pytest.raises(ValidationError) as raised:
        search_memory(kb, "sky", top_k=MAX_LIMIT + 1)

    assert _refusal(raised) == ("less_than_equal", ("top_k",), MAX_LIMIT + 1)


@pytest.mark.parametrize("top_k", [0, MAX_LIMIT + 1])
def test_a_configured_top_k_out_of_range_is_refused_on_load(top_k: int) -> None:
    configured = get_settings(Environment.TESTING).model_dump(mode="json")
    configured["search"]["top_k"] = top_k

    with pytest.raises(ValidationError, match=r"search\.top_k"):
        KnowledgeBaseSettings.model_validate(configured)


@pytest.mark.parametrize("top_k", [1, MAX_LIMIT])
def test_a_configured_top_k_at_either_bound_loads(top_k: int) -> None:
    configured = get_settings(Environment.TESTING).model_dump(mode="json")
    configured["search"]["top_k"] = top_k

    assert KnowledgeBaseSettings.model_validate(configured).search.top_k == top_k


def test_the_maximum_itself_is_served(kb: KnowledgeBase) -> None:
    assert list_memory_items(kb, "fake", limit=MAX_LIMIT).items
    assert search_memory(kb, "sky", top_k=MAX_LIMIT)


@pytest.mark.parametrize("query", ["", "  \n"])
def test_a_blank_search_query_is_a_validation_error(kb: KnowledgeBase, query: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank") as raised:
        search_memory(kb, query)

    assert _refusal(raised) == ("blank_query", ("query",), query)


@pytest.mark.parametrize("min_score", [math.nan, math.inf])
def test_a_non_finite_min_score_is_a_validation_error(kb: KnowledgeBase, min_score: float) -> None:
    with pytest.raises(ValidationError) as raised:
        search_memory(kb, "sky", min_score=min_score)

    [error] = raised.value.errors()
    assert (error["type"], error["loc"]) == ("finite_number", ("min_score",))
