"""``warmup_memory`` stopping partway: the run is recorded with the requests queued so far."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind, FakePayload
from pydantic import field_serializer
from pydantic_core import PydanticSerializationError
from warmup_harness import (
    FailingHuey,
    FailingUnrecordableHuey,
    UnrecordableHuey,
    fake_items,
    warmup_settings,
    write_yaml,
)

from tools_knowledge_base.errors import WarmupPartiallyQueued
from tools_knowledge_base.operations import get_warmup_progress, warmup_memory


def test_an_enqueue_failing_partway_records_the_requests_queued_so_far(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two", "three")})
    kb = open_fake_kb(FakeKind("fake"), huey=FailingHuey(2), settings=warmup_settings(tmp_path))

    with pytest.raises(WarmupPartiallyQueued) as caught:
        warmup_memory(kb)

    run_id = caught.value.run_id
    assert str(caught.value) == (
        f"warm-up run {run_id} stopped after queueing 2 requests and was recorded: "
        "OSError: queue storage unreachable"
    )
    assert isinstance(caught.value.__cause__, OSError)
    progress = get_warmup_progress(kb, run_id)
    assert (progress.total, progress.pending) == (2, 2)


def test_an_interrupt_partway_is_reraised_with_a_note_naming_the_run(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    huey = FailingHuey(1, KeyboardInterrupt())
    kb = open_fake_kb(FakeKind("fake"), huey=huey, settings=warmup_settings(tmp_path))

    with pytest.raises(KeyboardInterrupt) as caught:
        warmup_memory(kb)

    [note] = caught.value.__notes__
    run_id = note.split()[2]
    assert note == f"warm-up run {run_id} recorded 1 queued requests"
    assert get_warmup_progress(kb, run_id).total == 1


def test_a_clean_run_that_cannot_be_recorded_is_partially_queued(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    huey = UnrecordableHuey("warmup:")
    kb = open_fake_kb(FakeKind("fake"), huey=huey, settings=warmup_settings(tmp_path))

    with pytest.raises(WarmupPartiallyQueued) as caught:
        warmup_memory(kb)

    assert str(caught.value) == (
        f"warm-up run {caught.value.run_id} queued 2 requests but could not be recorded: "
        "OSError: queue storage unreachable"
    )
    assert huey.pending_count() == 2


def test_a_failed_record_after_a_failed_enqueue_says_so(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    huey = FailingUnrecordableHuey(1)
    kb = open_fake_kb(FakeKind("fake"), huey=huey, settings=warmup_settings(tmp_path))

    with pytest.raises(WarmupPartiallyQueued) as caught:
        warmup_memory(kb)

    assert str(caught.value) == (
        f"warm-up run {caught.value.run_id} stopped after queueing 1 requests and could not "
        "be recorded: OSError: queue storage unreachable"
    )
    cause = caught.value.__cause__
    assert cause is not None
    assert cause.__notes__ == ["recording: OSError: run storage unreachable"]
    assert huey.pending_count() == 1


def test_an_interrupt_that_cannot_be_recorded_says_so_in_a_note(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    huey = FailingUnrecordableHuey(1, KeyboardInterrupt())
    kb = open_fake_kb(FakeKind("fake"), huey=huey, settings=warmup_settings(tmp_path))

    with pytest.raises(KeyboardInterrupt) as caught:
        warmup_memory(kb)

    [note] = caught.value.__notes__
    assert note.endswith(" could not be recorded: OSError: run storage unreachable")


class _BoomPayload(FakePayload):
    @field_serializer("title", when_used="json")
    def _title(self, title: str) -> str:
        if title == "boom":
            msg = "digest bug on boom"
            raise LookupError(msg)
        return title


def test_a_failure_outside_the_enqueue_is_not_partially_queued_and_records_the_run(
    tmp_path: Path,
) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "boom", "two")})
    kind = FakeKind("fake")
    kind.payload_model = _BoomPayload
    kb = open_fake_kb(kind, settings=warmup_settings(tmp_path))

    with pytest.raises(PydanticSerializationError, match="digest bug on boom") as caught:
        warmup_memory(kb)

    assert not isinstance(caught.value, WarmupPartiallyQueued)
    [note] = caught.value.__notes__
    run_id = note.split()[2]
    assert note == f"warm-up run {run_id} recorded 1 queued requests"
    assert get_warmup_progress(kb, run_id).total == 1
