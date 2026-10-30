"""Warm-up YAML: only unique string keys, lists, strings and null load; the rest is a file error."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind
from pydantic import ValidationError
from warmup_harness import warmup_settings

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import WarmupDirectoryMissing
from tools_knowledge_base.operations.warmup_files import load_warmup_items


def _kb(path: Path) -> KnowledgeBase:
    return open_fake_kb(FakeKind("fake"), settings=warmup_settings(path))


def _errors(path: Path) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        load_warmup_items(_kb(path))
    return [(error["loc"], error["msg"]) for error in caught.value.errors()]


def test_plain_scalars_load_as_the_string_written(tmp_path: Path) -> None:
    text = "fake:\n  - title: 2024-01-02\n    tags: [yes, on, 42, 1.0, '1:30', 1:30]\n"
    (tmp_path / "a.yaml").write_text(text, encoding="utf-8")

    [item] = load_warmup_items(_kb(tmp_path)).items

    assert item.model.model_dump() == {
        "title": "2024-01-02",
        "tags": ["yes", "on", "42", "1.0", "1:30", "1:30"],
    }


@pytest.mark.parametrize("value", ["~", "null", "Null", "NULL", ""])
def test_every_yaml_null_spelling_loads_as_null(tmp_path: Path, value: str) -> None:
    (tmp_path / "a.yaml").write_text(f"fake:\n  - title: {value}\n    tags: []\n", encoding="utf-8")

    [(loc, msg)] = _errors(tmp_path)

    assert (loc, msg) == (("a.yaml", "fake", 0, "title"), "Input should be a valid string")


def test_anchors_and_aliases_load(tmp_path: Path) -> None:
    text = "fake:\n  - {title: one, tags: &t [a, b]}\n  - {title: two, tags: *t}\n"
    (tmp_path / "a.yaml").write_text(text, encoding="utf-8")

    assert [item.model.model_dump()["tags"] for item in load_warmup_items(_kb(tmp_path)).items] == [
        ["a", "b"],
        ["a", "b"],
    ]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("fake: []\nfake:\n  - {title: t, tags: []}\n", "key 'fake' is repeated"),
        ("fake:\n  - title: t\n    title: u\n    tags: []\n", "key 'title' is repeated"),
        ("fake:\n  - {title: !!binary aGk=, tags: []}\n", "tag:yaml.org,2002:binary"),
        ("fake:\n  - {title: !!timestamp 2024-01-02, tags: []}\n", "timestamp"),
        ("fake: !!set {a}\n", "tag:yaml.org,2002:set"),
        ("fake: !!omap [{a: b}]\n", "tag:yaml.org,2002:omap"),
        ("fake:\n  - {title: t, tags: [!!int 1]}\n", "tag:yaml.org,2002:int"),
        ("null: []\n", "keys must be strings"),
        ("? [a]\n: []\n", "keys must be strings"),
        ("fake: []\n---\nfake: []\n", "expected a single document"),
        ("fake: !!map [a, b]\n", "only a mapping can be tagged tag:yaml.org,2002:map"),
        ("fake:\n  - !!map abc\n", "only a mapping can be tagged tag:yaml.org,2002:map"),
    ],
)
def test_anything_outside_the_shape_is_an_error_at_the_file(
    tmp_path: Path, text: str, problem: str
) -> None:
    (tmp_path / "a.yaml").write_text(text, encoding="utf-8")

    [(loc, msg)] = _errors(tmp_path)

    assert loc == ("a.yaml",)
    assert msg.startswith("not valid YAML")
    assert problem in msg


@pytest.mark.parametrize("field", ["titel", "<<"])
def test_an_unknown_payload_field_is_an_error_not_dropped(tmp_path: Path, field: str) -> None:
    text = f"fake:\n  - {{title: t, tags: [], {field}: {{tags: [b]}}}}\n"
    (tmp_path / "a.yaml").write_text(text, encoding="utf-8")

    [(loc, msg)] = _errors(tmp_path)

    assert loc == ("a.yaml", "fake", 0, field)
    assert msg == "not a fake field; expected one of ['tags', 'title']"


@pytest.mark.parametrize("data", ["caf\xe9: []\n".encode("latin-1"), "fake: []\n".encode("utf-16")])
def test_a_file_that_is_not_utf8_is_an_error_beside_the_others(tmp_path: Path, data: bytes) -> None:
    (tmp_path / "a.yaml").write_bytes(data)
    (tmp_path / "b.yaml").write_text("fake: [unclosed", encoding="utf-8")

    errors = _errors(tmp_path)

    assert [loc for loc, _ in errors] == [("a.yaml",), ("b.yaml",)]
    assert errors[0][1].startswith("not readable as UTF-8 text")


def test_a_utf8_bom_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_bytes("﻿fake:\n  - {title: t, tags: []}\n".encode())

    assert len(load_warmup_items(_kb(tmp_path)).items) == 1


def test_an_unreadable_file_is_an_error_beside_the_others(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").symlink_to(tmp_path / "gone.yaml")
    (tmp_path / "b.yaml").write_text("fake: [unclosed", encoding="utf-8")
    target = tmp_path / "c.yaml"
    target.write_text("fake: []\n", encoding="utf-8")
    target.chmod(0)
    try:
        if _can_read(target):
            pytest.skip("running as root: chmod 0 does not stop reads")
        errors = _errors(tmp_path)
    finally:
        target.chmod(0o644)

    assert [loc for loc, _ in errors] == [("a.yaml",), ("b.yaml",), ("c.yaml",)]
    assert errors[2][1].startswith("not readable as UTF-8 text")


def test_an_unlistable_directory_is_reported_unreadable(tmp_path: Path) -> None:
    root = tmp_path / "warmup"
    root.mkdir()
    root.chmod(0)
    try:
        if _can_list(root):
            pytest.skip("running as root: chmod 0 does not stop listing")
        with pytest.raises(
            WarmupDirectoryMissing, match=f"{root} is unreadable: Permission denied"
        ):
            load_warmup_items(_kb(root))
    finally:
        root.chmod(0o755)


def _can_read(path: Path) -> bool:
    try:
        path.read_bytes()
    except PermissionError:
        return False
    return True


def _can_list(path: Path) -> bool:
    try:
        list(path.iterdir())
    except PermissionError:
        return False
    return True
