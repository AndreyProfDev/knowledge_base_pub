"""Dump files: written atomically, and their copy of an item wins over a hand-written one."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakeKind, FakePayload
from pydantic import ValidationError
from warmup_harness import fake_items, warmup_settings, write_yaml

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import WarmupShadow
from tools_knowledge_base.operations.store import item_id_of
from tools_knowledge_base.operations.warmup_files import load_warmup_items
from tools_knowledge_base.warmup_dump import dump_file_name, remove_dump, write_dump


def _kb(path: Path) -> KnowledgeBase:
    return open_fake_kb(FakeKind("fake"), settings=warmup_settings(path))


def _id(kb: KnowledgeBase, title: str) -> UUID:
    return item_id_of(kb.kinds.get("fake"), FakePayload(title=title, tags=[]))


def _dump_name(kb: KnowledgeBase, title: str) -> str:
    return dump_file_name("fake", _id(kb, title))


def test_a_dump_copy_beats_a_hand_written_one(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    write_yaml(tmp_path / "z.yaml", {"fake": fake_items("one")})
    dumped = _dump_name(kb, "one")
    write_yaml(tmp_path / dumped, {"fake": [{"title": "one", "tags": ["dumped"]}]})

    items, shadowed = load_warmup_items(kb)

    assert [(item.file, item.model.model_dump()) for item in items] == [
        ("a.yaml", {"title": "two", "tags": ["a"]}),
        (dumped, {"title": "one", "tags": ["dumped"]}),
    ]
    assert shadowed == [
        WarmupShadow(hand_written=hand, dump=f"{dumped}:fake[0]")
        for hand in ("a.yaml:fake[0]", "z.yaml:fake[0]")
    ]


def test_an_identical_hand_written_copy_drops_without_a_shadow(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    write_yaml(tmp_path / _dump_name(kb, "one"), {"fake": fake_items("one")})

    items, shadowed = load_warmup_items(kb)

    assert [item.file for item in items] == [_dump_name(kb, "one")]
    assert shadowed == []


def test_two_hand_written_copies_still_error(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    write_yaml(tmp_path / "b.yaml", {"fake": fake_items("one")})

    with pytest.raises(ValidationError) as caught:
        load_warmup_items(_kb(tmp_path))

    assert [(e["loc"], e["msg"]) for e in caught.value.errors()] == [
        (("b.yaml", "fake", 0), "same fake key as a.yaml:fake[0]; b.yaml:fake[0] repeats it")
    ]


def test_two_copies_inside_one_dump_file_error_not_last_wins(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    dumped = _dump_name(kb, "one")
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    write_yaml(
        tmp_path / dumped,
        {"fake": [{"title": "one", "tags": ["first"]}, {"title": "one", "tags": ["second"]}]},
    )

    with pytest.raises(ValidationError) as caught:
        load_warmup_items(kb)

    assert [(e["loc"], e["msg"]) for e in caught.value.errors()] == [
        ((dumped, "fake", 1), f"same fake key as {dumped}:fake[0]; {dumped}:fake[1] repeats it")
    ]


def test_a_dump_named_file_holding_another_item_counts_as_hand_written(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    misnamed = _dump_name(kb, "other")
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    write_yaml(tmp_path / misnamed, {"fake": fake_items("one")})

    with pytest.raises(ValidationError) as caught:
        load_warmup_items(kb)

    [(loc, msg)] = [(e["loc"], e["msg"]) for e in caught.value.errors()]
    assert loc == (misnamed, "fake", 0)
    assert msg.startswith("same fake key as a.yaml:fake[0]")


def test_write_dump_round_trips_through_load(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "warmup"
    kb = _kb(root)
    payload = FakePayload(title="ünï: yes", tags=["42", "2024-01-02", "null"])
    item_id = item_id_of(kb.kinds.get("fake"), payload)

    write_dump(root, "fake", item_id, payload.model_dump(mode="json"))
    write_dump(root, "fake", item_id, payload.model_dump(mode="json"))

    [item] = load_warmup_items(kb).items
    assert (item.file, item.item_id, item.model) == (
        dump_file_name("fake", item_id),
        item_id,
        payload,
    )
    assert sorted(p.name for p in root.iterdir()) == [dump_file_name("fake", item_id)]


def test_write_dump_keeps_a_next_line_character(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    payload = FakePayload(title="a\x85b ü", tags=[])
    item_id = item_id_of(kb.kinds.get("fake"), payload)

    write_dump(tmp_path, "fake", item_id, payload.model_dump(mode="json"))

    [item] = load_warmup_items(kb).items
    assert (item.item_id, item.model) == (item_id, payload)


def test_a_leftover_temp_file_is_ignored(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    (tmp_path / ".fake-x.yaml.tmp").write_text("fake: [half", encoding="utf-8")

    assert [item.file for item in load_warmup_items(_kb(tmp_path)).items] == ["a.yaml"]


def test_remove_dump_deletes_the_file_and_ignores_a_missing_one(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    item_id = _id(kb, "one")
    write_dump(tmp_path, "fake", item_id, {"title": "one", "tags": []})

    remove_dump(tmp_path, "fake", item_id)
    remove_dump(tmp_path, "fake", item_id)

    assert list(tmp_path.iterdir()) == []
