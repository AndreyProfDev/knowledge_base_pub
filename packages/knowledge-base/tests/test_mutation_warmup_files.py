"""Warm-up file errors carry their exact message, input and title."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind, FakePayload
from pydantic import ValidationError
from warmup_harness import warmup_settings, write_yaml

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.operations.store import item_id_of
from tools_knowledge_base.operations.warmup_files import load_warmup_items
from tools_knowledge_base.warmup_dump import dump_file_name


class DatedPayload(FakePayload):
    """A fake item with a field whose JSON form differs from its Python one."""

    on: date


def _kb(path: Path) -> KnowledgeBase:
    return open_fake_kb(FakeKind("fake"), settings=warmup_settings(path))


def _caught(path: Path) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        load_warmup_items(_kb(path))
    return caught.value


@pytest.mark.parametrize(
    ("text", "loc", "msg"),
    [
        ("- a\n", ("a.yaml",), "must map kind names to lists of payloads"),
        ("fake: x\n", ("a.yaml", "fake"), "must be a list of payloads"),
        ("fake: [x]\n", ("a.yaml", "fake", 0), "must be a mapping of payload fields"),
    ],
)
def test_a_misshapen_file_names_the_shape_it_needs(
    tmp_path: Path, text: str, loc: tuple[str | int, ...], msg: str
) -> None:
    (tmp_path / "a.yaml").write_text(text, encoding="utf-8")

    error = _caught(tmp_path)

    assert error.title == "warmup_memory"
    assert [(e["type"], e["loc"], e["msg"]) for e in error.errors()] == [
        ("warmup_item_invalid", loc, msg)
    ]


def test_a_bad_payload_field_keeps_the_value_written(tmp_path: Path) -> None:
    title = "t" * 41
    tags: list[str] = []
    write_yaml(tmp_path / "a.yaml", {"fake": [{"title": title, "tags": tags}]})

    [error] = _caught(tmp_path).errors()

    assert (error["loc"], error["input"]) == (("a.yaml", "fake", 0, "title"), title)


def test_an_unsupported_tag_names_where_it_is(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("fake:\n  - !!int 3\n", encoding="utf-8")

    [error] = _caught(tmp_path).errors()

    assert "tag tag:yaml.org,2002:int is not supported" in error["msg"]
    assert "line 2, column 5" in error["msg"]


def test_an_identical_copy_with_a_non_json_field_is_not_shadowed(tmp_path: Path) -> None:
    kind = FakeKind("fake")
    kind.payload_model = DatedPayload
    kb = open_fake_kb(kind, settings=warmup_settings(tmp_path))
    payload = {"title": "one", "tags": ["a"], "on": "2024-01-02"}
    item_id = item_id_of(kind, DatedPayload(title="one", tags=["a"], on=date(2024, 1, 2)))
    write_yaml(tmp_path / "a.yaml", {"fake": [payload]})
    write_yaml(tmp_path / dump_file_name("fake", item_id), {"fake": [payload]})

    files = load_warmup_items(kb)

    assert [item.file for item in files.items] == [dump_file_name("fake", item_id)]
    assert files.shadowed == []
