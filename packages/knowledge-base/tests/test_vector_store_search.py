"""The conformance suite's search half: every installed adapter ranks, scopes and cuts alike."""

from __future__ import annotations

import math

import pytest
from store_adapters import EMBEDDER, point

from tools_knowledge_base.store.protocol import VectorStore


def test_search_ranks_by_cosine_and_scopes_to_kind(store: VectorStore) -> None:
    near, far = point("red apple"), point("blue ocean wave")
    other = point("red apple", kind="other")
    store.upsert([near, far, other])
    query = EMBEDDER.embed_query("red apple")

    scoped = store.search(query, kinds=["fake"], limit=10, min_score=None)
    both = store.search(query, kinds=["fake", "other"], limit=10, min_score=None)
    every = store.search(query, kinds=None, limit=10, min_score=None)

    assert [hit.id for hit in scoped] == [near.id, far.id]
    assert {hit.id for hit in both} == {near.id, far.id, other.id}
    assert {hit.id for hit in every} == {near.id, far.id, other.id}
    assert scoped[0].score == pytest.approx(1.0, abs=1e-5)
    # Pinned to the cosine itself: an L2 score (1 - squared distance) keeps the order.
    cosine = sum(q * f for q, f in zip(query, far.vector, strict=True)) / (
        math.hypot(*query) * math.hypot(*far.vector)
    )
    assert scoped[1].score == pytest.approx(cosine, abs=1e-5)
    assert all(-1.0 - 1e-5 <= hit.score <= 1.0 + 1e-5 for hit in every)
    assert scoped[0].model_dump(exclude={"score"}) == near.model_dump(exclude={"vector"})


def test_search_filters_by_kind_before_the_limit(store: VectorStore) -> None:
    store.upsert([point("red apple", kind="other") for _ in range(3)])
    wanted = point("blue ocean wave")
    store.upsert([wanted])

    hits = store.search(EMBEDDER.embed_query("red apple"), kinds=["fake"], limit=1, min_score=None)

    assert [hit.id for hit in hits] == [wanted.id]


def test_search_drops_hits_under_min_score_and_honours_limit(store: VectorStore) -> None:
    near, far = point("red apple"), point("blue ocean wave")
    store.upsert([near, far])
    query = EMBEDDER.embed_query("red apple")
    far_score = next(
        h.score for h in store.search(query, kinds=None, limit=10, min_score=None) if h.id == far.id
    )

    above = store.search(query, kinds=None, limit=10, min_score=(far_score + 1.0) / 2)
    top = store.search(query, kinds=None, limit=1, min_score=None)

    assert [hit.id for hit in above] == [near.id]
    assert [hit.id for hit in top] == [near.id]
