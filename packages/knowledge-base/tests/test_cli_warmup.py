"""``warmup`` and ``warmup-progress`` over a ``tmp_path`` warm-up directory."""

from __future__ import annotations

import re
from pathlib import Path

from cli_harness import invoke
from fake_kb import fake_registry, open_fake_kb
from fake_kind import FakeKind, FakePayload
from warmup_harness import BoomEmbedder, FailingHuey, fake_items, warmup_settings, write_yaml

from tools_knowledge_base.context import open_knowledge_base
from tools_knowledge_base.embeddings import OpenAIEmbedder
from tools_knowledge_base.operations import get_warmup_progress
from tools_knowledge_base.operations.store import item_id_of
from tools_knowledge_base.operations.warmup_progress import FAILURES_SHOWN
from tools_knowledge_base.queue import drain
from tools_knowledge_base.warmup_dump import dump_file_name


def _run_id(output: str) -> str:
    match = re.search(r"run_id: (\S+)", output)
    assert match is not None, output
    return match.group(1)


def test_warmup_prints_the_report_and_progress_follows_it_to_the_end(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two", "three")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))

    code, output = invoke(kb, "warmup")
    assert code == 0, output
    assert "fake: 3 queued, 0 unchanged\ntotal queued: 3\n" in output

    code, shown = invoke(kb, "warmup-progress", _run_id(output))
    assert code == 0, shown
    assert shown.startswith("0 of 3 written: 0 done, 0 failed, 3 pending, 0 unchanged\n")
    assert "about 150 s" in shown

    drain(kb.huey)
    _, shown = invoke(kb, "warmup-progress", _run_id(output))
    assert shown == "3 of 3 written: 3 done, 0 failed, 0 pending, 0 unchanged\nfinished\n"


def test_progress_lists_failures_and_says_when_there_are_more(tmp_path: Path) -> None:
    titles = [f"boom{n}" for n in range(FAILURES_SHOWN + 1)]
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items(*titles)})
    kb = open_fake_kb(embedder=BoomEmbedder(), settings=warmup_settings(tmp_path, retries=0))
    _, output = invoke(kb, "warmup")
    drain(kb.huey)

    _, shown = invoke(kb, "warmup-progress", _run_id(output))

    failed = [line for line in shown.splitlines() if line.startswith("failed: fake  ")]
    assert len(failed) == FAILURES_SHOWN
    assert failed[0].endswith(": KnowledgeBaseError('embeddings server unreachable')")
    assert shown.endswith("and more failures\nfinished\n")


def test_a_rerun_reports_every_item_unchanged(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(settings=warmup_settings(tmp_path))
    invoke(kb, "warmup")
    drain(kb.huey)

    _, output = invoke(kb, "warmup")

    assert "fake: 0 queued, 2 unchanged\ntotal queued: 0\n" in output


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


def test_an_unknown_run_exits_1_naming_it() -> None:
    code, output = invoke(open_fake_kb(), "warmup-progress", "nope")

    assert code == 1
    assert "no warm-up run 'nope'" in output


def test_an_enqueue_failing_partway_exits_1_naming_the_run(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one", "two")})
    kb = open_fake_kb(huey=FailingHuey(1), settings=warmup_settings(tmp_path))

    code, output = invoke(kb, "warmup")

    assert code == 1
    match = re.search(
        r"warm-up run (\S+) stopped after queueing 1 requests and was recorded: OSError", output
    )
    assert match is not None, output
    assert get_warmup_progress(kb, match.group(1)).total == 1


def test_a_keyless_embedder_exits_1_before_anything_is_queued(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"fake": fake_items("one")})
    settings = warmup_settings(tmp_path)
    keyless = OpenAIEmbedder(settings.embeddings.embedders["openai-small"])
    kb = open_knowledge_base(settings, embedder=keyless, kinds=fake_registry(FakeKind("fake")))

    code, output = invoke(kb, "warmup")

    assert code == 1
    assert "has no api_key" in output
    assert kb.huey.pending_count() == 0


def test_a_bad_file_exits_1_and_a_missing_directory_too(tmp_path: Path) -> None:
    write_yaml(tmp_path / "a.yaml", {"nope": fake_items("one")})
    assert invoke(open_fake_kb(settings=warmup_settings(tmp_path)), "warmup")[0] == 1

    missing = open_fake_kb(settings=warmup_settings(tmp_path / "absent"))
    assert invoke(missing, "warmup")[0] == 1
