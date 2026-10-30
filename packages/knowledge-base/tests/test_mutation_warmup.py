"""Warm-up's change detection, its run ids, and the dump file's exact text."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind, FakePayload
from warmup_harness import FailingHuey, UnrecordableHuey, fake_items, warmup_settings, write_yaml

from tools_knowledge_base.errors import WarmupPartiallyQueued
from tools_knowledge_base.operations import get_warmup_progress, warmup_memory
from tools_knowledge_base.operations.store import item_id_of
from tools_knowledge_base.queue import drain
from tools_knowledge_base.store.protocol import Point
from tools_knowledge_base.warmup_dump import dump_file_name, write_dump

_LOGGER = "tools_knowledge_base.operations.warmup"


@pytest.mark.parametrize("corrupt", ["one", "two"])
def test_a_corrupt_stored_item_requeues_only_itself(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, corrupt: str
) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kind = FakeKind("fake")
    kb = open_fake_kb(kind, settings=warmup_settings(tmp_path))
    warmup_memory(kb)
    drain(kb.huey)
    item_id = item_id_of(kind, FakePayload(title=corrupt, tags=["a"]))
    point = Point(
        id=item_id,
        kind="fake",
        updated_at=datetime.now(UTC),
        payload={"title": corrupt},
        vector=[1.0] + [0.0] * 7,
    )
    kb.store.upsert([point])

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        report = warmup_memory(kb)

    assert (report.total_queued, report.kinds["fake"].unchanged) == (1, 1)
    [record] = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
    assert record == (
        f"warm-up replaces stored fake item {item_id}: its payload fails the model: "
        "[{'type': 'missing', 'loc': ('tags',), 'msg': 'Field required'}]"
    )


class _MetaPayload(FakePayload):
    meta: dict[str, str]


def test_reordered_mapping_keys_leave_an_item_unchanged(tmp_path: Path) -> None:
    kind = FakeKind("fake")
    kind.payload_model = _MetaPayload
    kb = open_fake_kb(kind, settings=warmup_settings(tmp_path))
    file = tmp_path / "a.yaml"
    file.write_text("fake:\n- {title: one, tags: [], meta: {b: '2', a: '1'}}\n", encoding="utf-8")
    assert warmup_memory(kb).total_queued == 1
    drain(kb.huey)

    file.write_text("fake:\n- {title: one, tags: [], meta: {a: '1', b: '2'}}\n", encoding="utf-8")

    assert warmup_memory(kb).kinds["fake"].unchanged == 1


def test_an_interrupted_run_is_recorded_under_its_uuid(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    huey = FailingHuey(1, KeyboardInterrupt())
    kb = open_fake_kb(FakeKind("fake"), huey=huey, settings=warmup_settings(tmp_path))

    with pytest.raises(KeyboardInterrupt) as caught:
        warmup_memory(kb)

    [note] = caught.value.__notes__
    run_id = str(UUID(note.split()[2]))
    assert get_warmup_progress(kb, run_id).total == 1


def test_an_unrecordable_run_names_its_uuid(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    kb = open_fake_kb(
        FakeKind("fake"), huey=UnrecordableHuey("warmup:"), settings=warmup_settings(tmp_path)
    )

    with pytest.raises(WarmupPartiallyQueued) as caught:
        warmup_memory(kb)

    assert str(UUID(caught.value.run_id)) == caught.value.run_id


@pytest.mark.parametrize(
    ("title", "text"),
    [
        ("é", "fake:\n- title: é\n  tags:\n  - b\n  - a\n"),
        ("a\x85b", 'fake:\n- title: "a\\Nb"\n  tags:\n  - b\n  - a\n'),
    ],
)
def test_a_dump_file_keeps_field_order_and_writes_unicode_raw(
    tmp_path: Path, title: str, text: str
) -> None:
    item_id = UUID(int=1)

    write_dump(tmp_path, "fake", item_id, {"title": title, "tags": ["b", "a"]})

    assert (tmp_path / dump_file_name("fake", item_id)).read_bytes().decode() == text
