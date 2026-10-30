"""``warmup_memory``: all-or-nothing validation, then only missing or changed items queued."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from pydantic import ValidationError
from warmup_harness import fake_items, warmup_settings, write_yaml

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import (
    WarmupDirectoryEmpty,
    WarmupDirectoryMissing,
)
from tools_knowledge_base.models import WarmupKindCounts
from tools_knowledge_base.operations import list_memory_items, warmup_memory
from tools_knowledge_base.queue import drain
from tools_knowledge_base.store.protocol import Point


def _kb(path: Path) -> KnowledgeBase:
    return open_fake_kb(FakeKind("fake"), FakeKind("other"), settings=warmup_settings(path))


def _errors(kb: KnowledgeBase) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        warmup_memory(kb)
    assert kb.huey.pending_count() == 0
    return [(error["loc"], error["msg"]) for error in caught.value.errors()]


def test_a_second_run_on_the_same_files_leaves_every_item_unchanged(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    write_yaml(tmp_path / "b.yaml", {"other": fake_items("three")})
    kb = _kb(tmp_path)

    first = warmup_memory(kb)
    assert first.kinds == {
        "fake": WarmupKindCounts(queued=2, unchanged=0),
        "other": WarmupKindCounts(queued=1, unchanged=0),
    }
    assert first.total_queued == kb.huey.pending_count() == 3
    drain(kb.huey)

    second = warmup_memory(kb)
    assert second.kinds == {
        "fake": WarmupKindCounts(queued=0, unchanged=2),
        "other": WarmupKindCounts(queued=0, unchanged=1),
    }
    assert second.total_queued == kb.huey.pending_count() == 0
    assert second.run_id != first.run_id


def test_an_edited_non_key_field_requeues_only_that_item_under_its_id(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = _kb(tmp_path)
    warmup_memory(kb)
    drain(kb.huey)
    before = _stored(kb)

    edited: dict[str, object] = {"title": "two", "tags": []}
    write_yaml(tmp_path / "a.yaml", {"fake": [*fake_items("one"), edited]})
    report = warmup_memory(kb)
    assert report.kinds["fake"] == WarmupKindCounts(queued=1, unchanged=1)
    drain(kb.huey)

    after = _stored(kb)
    assert after.keys() == before.keys()
    assert {payload["title"]: payload["tags"] for payload in after.values()} == {
        "one": ["a"],
        "two": [],
    }


def _stored(kb: KnowledgeBase) -> dict[UUID, dict[str, object]]:
    return {item.id: item.payload.model_dump() for item in list_memory_items(kb, "fake").items}


def test_the_same_key_in_two_files_is_rejected_naming_both(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "dup")})
    write_yaml(tmp_path / "b.yaml", {"fake": [{"title": "dup", "tags": ["other"]}]})

    assert _errors(_kb(tmp_path)) == [
        (("b.yaml", "fake", 0), "same fake key as a.yaml:fake[1]; b.yaml:fake[0] repeats it")
    ]


def test_one_over_cap_item_rejects_the_run_and_queues_none(tmp_path: Path) -> None:
    long = {"title": "long", "tags": ["x" * 500]}
    write_yaml(tmp_path / "a.yaml", {"fake": [*fake_items("one"), long, *fake_items("two")]})

    [(loc, msg)] = _errors(_kb(tmp_path))

    assert loc == ("a.yaml", "fake", 1)
    assert msg.startswith("fake item is 505 characters; the fake limit is 500")


def test_an_unknown_top_level_kind_is_rejected(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"nope": fake_items("one"), "fake": fake_items("two")})

    [(loc, msg)] = _errors(_kb(tmp_path))

    assert loc == ("a.yaml", "nope")
    assert "'nope'" in msg


def test_every_failure_is_reported_at_its_location(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("fake: [unclosed", encoding="utf-8")
    write_yaml(tmp_path / "b.yaml", ["not", "a", "mapping"])
    write_yaml(tmp_path / "c.yaml", {"fake": "not a list", "other": ["not a mapping"]})
    write_yaml(tmp_path / "d.yaml", {"fake": [{"title": "t"}]})
    (tmp_path / "e.yaml").write_text("", encoding="utf-8")
    (tmp_path / "f.yml").write_text("broken: [", encoding="utf-8")

    errors = _errors(_kb(tmp_path))

    assert [loc for loc, _ in errors] == [
        ("a.yaml",),
        ("b.yaml",),
        ("c.yaml", "fake"),
        ("c.yaml", "other", 0),
        ("d.yaml", "fake", 0, "tags"),
        ("f.yml",),
    ]
    assert errors[0][1].startswith("not valid YAML")
    assert errors[4][1] == "Field required"
    assert errors[5][1].startswith("not valid YAML")


def test_yml_files_are_read_and_dotfiles_skipped(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yml", {"fake": fake_items("one")})
    (tmp_path / ".gitignore").write_text("*\n", encoding="utf-8")

    assert warmup_memory(_kb(tmp_path)).total_queued == 1


def test_a_non_yaml_entry_or_subdirectory_is_an_error(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    (tmp_path / "sub.yaml").mkdir()
    (tmp_path / "gone.yaml").symlink_to(tmp_path / "missing.yaml")

    assert _errors(_kb(tmp_path)) == [
        (("gone.yaml",), "not a regular file; warm-up does not read it"),
        (("notes.txt",), "not a .yaml file; warm-up does not read it"),
        (("sub.yaml",), "not a regular file; warm-up does not read it"),
    ]


@pytest.mark.parametrize("files", [{}, {".gitignore": "*\n"}, {"a.yaml": "", "b.yml": "{}"}])
def test_a_directory_holding_no_items_raises_naming_it(
    tmp_path: Path, files: dict[str, str]
) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    kb = _kb(tmp_path)

    with pytest.raises(WarmupDirectoryEmpty, match=f"{tmp_path.resolve()} holds no items"):
        warmup_memory(kb)
    assert kb.huey.pending_count() == 0


def test_a_missing_directory_names_its_path(tmp_path: Path) -> None:
    with pytest.raises(WarmupDirectoryMissing, match="absent"):
        warmup_memory(_kb(tmp_path / "absent"))


def test_a_missing_relative_directory_is_named_absolute() -> None:
    with pytest.raises(WarmupDirectoryMissing, match=re.escape(str(Path.cwd() / "absent-warmup"))):
        warmup_memory(_kb(Path("absent-warmup")))


def test_a_stored_payload_failing_its_model_is_requeued(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    kb = _kb(tmp_path)
    warmup_memory(kb)
    drain(kb.huey)
    [item_id] = _stored(kb)
    corrupt = Point(
        id=item_id,
        kind="fake",
        updated_at=datetime.now(UTC),
        payload={"title": "one"},
        vector=[1.0] + [0.0] * 7,
    )
    kb.store.upsert([corrupt])

    with caplog.at_level(logging.WARNING, logger="tools_knowledge_base.operations.warmup"):
        assert warmup_memory(kb).total_queued == 1

    [record] = [r for r in caplog.records if r.name == "tools_knowledge_base.operations.warmup"]
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith(
        f"warm-up replaces stored fake item {item_id}: its payload fails the model:"
    )
