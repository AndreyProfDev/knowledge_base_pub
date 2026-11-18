"""``warmup`` over a ``tmp_path`` warm-up directory."""

from __future__ import annotations

from pathlib import Path

from cli_harness import invoke
from fake_kb import fake_registry, open_fake_kb
from fake_kind import FakeKind, FakePayload
from warmup_harness import FailOnCallEmbedder, fake_items, warmup_settings, write_yaml

from tools_knowledge_base.context import open_knowledge_base
from tools_knowledge_base.embeddings import OpenAIEmbedder
from tools_knowledge_base.operations.store import item_id_of
from tools_knowledge_base.warmup_dump import dump_file_name


def test_warmup_prints_the_report(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two", "three")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))

    code, output = invoke(kb, "warmup")

    assert code == 0, output
    assert output == "fake: 3 written, 0 unchanged\ntotal written: 3\n"


def test_a_rerun_reports_every_item_unchanged(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    invoke(kb, "warmup")

    _, output = invoke(kb, "warmup")

    assert "fake: 0 written, 2 unchanged\ntotal written: 0\n" in output


def test_warmup_prints_a_hand_written_copy_its_dump_copy_shadowed(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    item_id = item_id_of(kb.kinds.get("fake"), FakePayload(title="one", tags=[]))
    dump = dump_file_name("fake", item_id)
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    write_yaml(tmp_path / dump, {"fake": [{"title": "one", "tags": ["dumped"]}]})

    code, output = invoke(kb, "warmup")

    assert code == 0, output
    assert output.endswith(
        f"shadowed: a.yaml:fake[0] differs from {dump}:fake[0], which was used\n"
    )


def test_a_keyless_embedder_exits_1_naming_the_missing_key(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    settings = warmup_settings(tmp_path)
    keyless = OpenAIEmbedder(settings.embeddings.embedders["openai-small"])
    kb = open_knowledge_base(settings, embedder=keyless, kinds=fake_registry(FakeKind("fake")))

    code, output = invoke(kb, "warmup")

    assert code == 1
    assert "has no api_key" in output


def test_a_failed_batch_exits_1_with_the_partial_write_error(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    kb = open_fake_kb(embedder=FailOnCallEmbedder(1), settings=warmup_settings(tmp_path))

    code, output = invoke(kb, "warmup")

    assert code == 1
    assert output == (
        "Error: warm-up stopped at fake batch 1 after writing 0 items: "
        "OSError: embeddings server unreachable\n"
    )


def test_a_bad_file_exits_1_and_a_missing_directory_too(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"nope": fake_items("one")})
    assert invoke(open_fake_kb(settings=warmup_settings(tmp_path)), "warmup")[0] == 1

    missing = open_fake_kb(settings=warmup_settings(tmp_path / "absent"))
    assert invoke(missing, "warmup")[0] == 1


def test_help_lists_warmup_and_not_warmup_progress(tmp_path: Path) -> None:
    kb = open_fake_kb(settings=warmup_settings(tmp_path))

    code, output = invoke(kb, "--help")

    assert code == 0, output
    assert " warmup " in output
    assert "warmup-progress" not in output
