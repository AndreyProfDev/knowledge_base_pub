"""``warmup_memory`` writes in ``PAGE_SIZE`` batches and stops at the first batch that fails."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_embedder import FakeEmbedder
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from warmup_harness import (
    FailOnCallEmbedder,
    ShortEmbedder,
    fake_items,
    warmup_settings,
    write_yaml,
)

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import WarmupPartiallyWritten
from tools_knowledge_base.models import WarmupKindCounts
from tools_knowledge_base.operations import warmup_memory
from tools_knowledge_base.operations.reembed import PAGE_SIZE
from tools_knowledge_base.operations.warmup_files import load_warmup_items
from tools_knowledge_base.warmup_dump import dump_file_name

_TOTAL = 2 * PAGE_SIZE + 6


def _titles(count: int) -> list[str]:
    return [f"item {n:03}" for n in range(count)]


def _kb(path: Path, embedder: FakeEmbedder, *, dump: bool = False) -> KnowledgeBase:
    write_yaml(path / "a.yaml", {"fake": fake_items(*_titles(_TOTAL))})
    settings = warmup_settings(path, dump=dump)
    return open_fake_kb(FakeKind("fake"), embedder=embedder, settings=settings)


def _stored_ids(kb: KnowledgeBase) -> set[object]:
    ids = [item.item_id for item in load_warmup_items(kb).items]
    return {item.id for item in kb.store.get(ids)}


def test_changed_items_are_embedded_in_page_sized_batches_and_a_rerun_embeds_none(
    tmp_path: Path,
) -> None:
    embedder = FakeEmbedder()
    kb = _kb(tmp_path, embedder)
    before = datetime.now(UTC)

    first = warmup_memory(kb)

    assert embedder.batch_sizes == [PAGE_SIZE, PAGE_SIZE, 6]
    assert first.kinds == {"fake": WarmupKindCounts(written=_TOTAL, unchanged=0)}
    assert first.total_written == _TOTAL
    ids = [item.item_id for item in load_warmup_items(kb).items]
    stamps = {item.updated_at for item in kb.store.get(ids)}
    assert all(before <= stamp <= datetime.now(UTC) for stamp in stamps)

    second = warmup_memory(kb)

    assert embedder.batch_sizes == [PAGE_SIZE, PAGE_SIZE, 6]
    assert second.kinds == {"fake": WarmupKindCounts(written=0, unchanged=_TOTAL)}
    assert second.total_written == 0


def test_a_failing_second_batch_keeps_the_first_with_its_dump_files_and_a_rerun_writes_the_rest(
    tmp_path: Path,
) -> None:
    kb = _kb(tmp_path, FailOnCallEmbedder(2), dump=True)
    first_batch = load_warmup_items(kb).items[:PAGE_SIZE]

    with pytest.raises(WarmupPartiallyWritten) as raised:
        warmup_memory(kb)

    assert str(raised.value) == (
        "warm-up stopped at fake batch 2 after writing 32 items: "
        "OSError: embeddings server unreachable"
    )
    assert isinstance(raised.value.__cause__, OSError)
    assert _stored_ids(kb) == {item.item_id for item in first_batch}
    assert sorted(entry.name for entry in tmp_path.glob("fake-*.yaml")) == sorted(
        dump_file_name("fake", item.item_id) for item in first_batch
    )

    rerun = warmup_memory(replace(kb, embedder=FakeEmbedder()))

    assert rerun.kinds == {
        "fake": WarmupKindCounts(written=_TOTAL - PAGE_SIZE, unchanged=PAGE_SIZE)
    }
    assert len(_stored_ids(kb)) == _TOTAL


def test_a_stored_item_with_no_dump_file_is_rewritten_so_its_file_appears(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(FakeKind("fake"), settings=warmup_settings(tmp_path, dump=False))
    warmup_memory(kb)
    assert not list(tmp_path.glob("fake-*.yaml"))

    report = warmup_memory(replace(kb, settings=warmup_settings(tmp_path, dump=True)))

    assert report.kinds == {"fake": WarmupKindCounts(written=2, unchanged=0)}
    assert len(list(tmp_path.glob("fake-*.yaml"))) == 2
    again = warmup_memory(replace(kb, settings=warmup_settings(tmp_path, dump=True)))
    assert again.total_written == 0


def test_the_error_names_the_kind_and_counts_the_items_written_across_kinds(
    tmp_path: Path,
) -> None:
    write_yaml(
        tmp_path / "a.yaml", {"fake": fake_items("one", "two"), "other": fake_items("three")}
    )
    kb = open_fake_kb(
        FakeKind("fake"),
        FakeKind("other"),
        embedder=FailOnCallEmbedder(2),
        settings=warmup_settings(tmp_path),
    )

    with pytest.raises(WarmupPartiallyWritten) as raised:
        warmup_memory(kb)

    assert str(raised.value) == (
        "warm-up stopped at other batch 1 after writing 2 items: "
        "OSError: embeddings server unreachable"
    )


def test_an_embedder_returning_too_few_vectors_writes_nothing_of_the_batch(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(
        FakeKind("fake"), embedder=ShortEmbedder(), settings=warmup_settings(tmp_path)
    )

    with pytest.raises(WarmupPartiallyWritten) as raised:
        warmup_memory(kb)

    assert str(raised.value) == (
        "warm-up stopped at fake batch 1 after writing 0 items: "
        "ValueError: zip() argument 2 is shorter than argument 1"
    )
    assert _stored_ids(kb) == set()
