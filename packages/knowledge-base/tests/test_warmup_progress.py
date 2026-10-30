"""``get_warmup_progress``: derived from each recorded request's status on every read."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fake_kb import open_fake_kb
from warmup_harness import BoomEmbedder, fake_items, warmup_settings, write_yaml

from tools_knowledge_base.errors import StoredItemInvalid, UnknownWarmupRun
from tools_knowledge_base.operations import get_warmup_progress, warmup_memory
from tools_knowledge_base.operations.warmup_progress import WarmupRequest, WarmupRun, record_run
from tools_knowledge_base.queue import drain, put_value


def test_a_run_reads_pending_until_drained_then_finished(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two", "three")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    run_id = warmup_memory(kb).run_id

    progress = get_warmup_progress(kb, run_id)
    assert (progress.total, progress.done, progress.failed, progress.pending) == (3, 0, 0, 3)
    assert not progress.finished

    drain(kb.huey)
    progress = get_warmup_progress(kb, run_id)
    assert (progress.total, progress.done, progress.failed, progress.pending) == (3, 3, 0, 0)
    assert progress.finished
    assert progress.failures == []


def test_a_failed_write_counts_as_failed_with_its_error(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "boom")})
    kb = open_fake_kb(embedder=BoomEmbedder(), settings=warmup_settings(tmp_path, retries=0))
    report = warmup_memory(kb)
    drain(kb.huey)

    progress = get_warmup_progress(kb, report.run_id)

    assert (progress.done, progress.failed, progress.pending) == (1, 1, 0)
    assert progress.finished
    [failure] = progress.failures
    assert failure.kind == "fake"
    assert failure.error == "KnowledgeBaseError('embeddings server unreachable')"
    assert not progress.failures_truncated


@pytest.mark.parametrize(("failed", "truncated"), [(50, False), (51, True)])
def test_failures_past_the_first_50_are_truncated(
    tmp_path: Path, failed: int, *, truncated: bool
) -> None:
    titles = [f"boom{i}" for i in range(failed)]
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items(*titles)})
    kb = open_fake_kb(embedder=BoomEmbedder(), settings=warmup_settings(tmp_path, retries=0))
    report = warmup_memory(kb)
    drain(kb.huey)

    progress = get_warmup_progress(kb, report.run_id)

    assert progress.failed == failed
    assert len(progress.failures) == 50
    assert progress.failures_truncated is truncated


def test_a_run_with_nothing_to_queue_is_finished_at_once(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    warmup_memory(kb)
    drain(kb.huey)

    progress = get_warmup_progress(kb, warmup_memory(kb).run_id)

    assert (progress.total, progress.pending, progress.unchanged) == (0, 0, 1)
    assert progress.finished


def test_an_unknown_run_id_raises_naming_it(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))

    with pytest.raises(UnknownWarmupRun, match="'no-such-run'"):
        get_warmup_progress(kb, "no-such-run")


def test_a_recorded_request_never_issued_is_invalid_not_an_unknown_run(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    request = WarmupRequest(request_id="ghost", item_id=uuid4(), kind="fake")
    record_run(kb, "run-1", WarmupRun(requests=[request], unchanged=0))

    with pytest.raises(StoredItemInvalid, match="'run-1' records request 'ghost'"):
        get_warmup_progress(kb, "run-1")


def test_a_run_key_holding_a_non_string_is_invalid_not_absent(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    kb.huey.put("warmup:run-1", 7)  # pyright: ignore[reportUnknownMemberType]

    with pytest.raises(StoredItemInvalid, match="'warmup:run-1' holds int, not a string"):
        get_warmup_progress(kb, "run-1")


def test_a_run_key_holding_a_non_json_string_is_invalid(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    put_value(kb.huey, "warmup:run-1", "not json")

    with pytest.raises(StoredItemInvalid, match=r"warm-up run 'run-1''s record: .*json_invalid"):
        get_warmup_progress(kb, "run-1")
