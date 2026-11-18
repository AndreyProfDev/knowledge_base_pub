"""The one upsert-then-dump write the worker and warm-up share."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from fake_kind import FakeKind

from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.warmup_dump import dump_file_name, upsert_and_sync_dump


def _point() -> Point:
    return Point(
        id=uuid4(),
        kind="fake",
        updated_at=datetime(2024, 1, 2, tzinfo=UTC),
        payload={"title": "one", "tags": []},
        vector=FakeEmbedder().embed_documents(["one"])[0],
    )


def test_it_upserts_calls_back_with_the_point_stored_then_dumps_it(tmp_path: Path) -> None:
    kb = open_fake_kb(FakeKind("fake"))
    point = _point()
    seen: list[str | None] = []

    def on_upserted() -> None:
        seen.append(kb.store.kind_of(point.id))
        seen.append(None if list(tmp_path.iterdir()) else "no file yet")

    upsert_and_sync_dump(kb.store, tmp_path, kb.kinds, "fake", [point], on_upserted)

    assert seen == ["fake", "no file yet"]
    assert [p.name for p in tmp_path.iterdir()] == [dump_file_name("fake", point.id)]


def test_it_leaves_the_files_alone_with_no_root(tmp_path: Path) -> None:
    kb = open_fake_kb(FakeKind("fake"))
    point = _point()

    upsert_and_sync_dump(kb.store, None, kb.kinds, "fake", [point], lambda: None)

    assert kb.store.kind_of(point.id) == "fake"
    assert list(tmp_path.iterdir()) == []
