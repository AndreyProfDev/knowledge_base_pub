"""``SqliteStore`` ranks and scores like the Qdrant adapter, which searches exactly at this size."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from store_adapters import ADAPTERS, T0

from tools_knowledge_base.store.factory import open_store
from tools_knowledge_base.store.protocol import Hit, Point

# Query (2, 0): by cosine A (1.0), C (0.707), B (0.6), D (-0.894); by an unnormalised dot
# product B (6) would outrank A (0.2), so a missing normalisation flips the order.
_VECTORS = {"a": [0.1, 0.0], "b": [3.0, 4.0], "c": [1.0, 1.0], "d": [-2.0, 1.0]}
_QUERY = [2.0, 0.0]
_IDS = {name: UUID(int=n) for n, name in enumerate(_VECTORS, start=1)}


def _search(name: str, tmp_path: Path, *, min_score: float | None) -> list[Hit]:
    store = open_store(ADAPTERS[name](tmp_path), "memory-fake-2", dimensions=2)
    store.upsert(
        [
            Point(
                id=_IDS[key],
                kind="fake",
                updated_at=T0,
                payload={"title": key, "tags": []},
                vector=vector,
            )
            for key, vector in _VECTORS.items()
        ]
    )
    return store.search(_QUERY, kinds=None, limit=10, min_score=min_score)


@pytest.mark.parametrize("min_score", [None, 0.6])
def test_same_ids_in_the_same_order_with_the_same_scores(
    tmp_path: Path, min_score: float | None
) -> None:
    qdrant = _search("qdrant", tmp_path / "qdrant", min_score=min_score)
    sqlite = _search("sqlite", tmp_path / "sqlite", min_score=min_score)

    assert [hit.id for hit in sqlite] == [hit.id for hit in qdrant]
    assert [hit.score for hit in sqlite] == pytest.approx([hit.score for hit in qdrant], abs=1e-5)
    expected = ["a", "c", "b"] if min_score else ["a", "c", "b", "d"]
    assert [hit.id for hit in sqlite] == [_IDS[key] for key in expected]
