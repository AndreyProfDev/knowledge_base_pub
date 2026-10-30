"""``knowledge-base-cli`` over fake kinds: the generated verbs and the generic ones."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cli_harness import cli_kb, invoke, item_id_in
from fake_embedder import FakeEmbedder
from fake_kb import stored

from tools_knowledge_base.cli.main import main
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.kinds.registry import load_kinds
from tools_knowledge_base.operations import store_memory
from tools_knowledge_base.queue import drain, enqueue_write


def test_store_then_search_prints_the_item_with_its_score() -> None:
    kb = cli_kb()
    code, output = invoke(kb, "store-fake", "--title", "sky", "--tags", "blue", "--tags", "day")
    assert code == 0, output
    assert "request_id: " in output
    assert "status: queued" in output
    drain(kb.huey)

    code, output = invoke(kb, "search", "sky blue", "--kind", "fake", "--top-k", "1")

    assert code == 0, output
    assert re.fullmatch(rf"\d\.\d{{3}}  fake  {_item_id_of(kb)}  sky \[blue, day\]\n", output)


def _item_id_of(kb: KnowledgeBase) -> UUID:
    [item] = kb.store.list("fake", limit=1, cursor=None)[0]
    return item.id


def test_search_without_hits_says_so_and_offers_only_installed_kinds() -> None:
    kb = cli_kb()

    assert invoke(kb, "search", "anything", "--min-score", "0.5") == (0, "no matches\n")
    code, output = invoke(kb, "search", "anything", "--kind", "nope")
    assert code == 2
    assert "'fake', 'note'" in output


def test_search_kind_and_min_score_reach_the_search() -> None:
    kb = cli_kb()
    stored(kb, "red apple")
    stored(kb, "blue ocean wave")
    store_memory(kb, "note", {"category": "fact", "text": "red apple"})
    drain(kb.huey)

    _, every = invoke(kb, "search", "red apple", "--min-score", "-1")
    _, notes = invoke(kb, "search", "red apple", "--kind", "note", "--min-score", "-1")
    _, close = invoke(kb, "search", "red apple", "--kind", "fake", "--min-score", "0.99")

    assert sorted(line.split("  ")[1] for line in every.splitlines()) == ["fake", "fake", "note"]
    assert [line.split("  ")[1] for line in notes.splitlines()] == ["note"]
    assert [line.split("  ")[3] for line in close.splitlines()] == ["red apple []"]


def test_list_defaults_to_pages_of_50() -> None:
    kb = cli_kb()
    for i in range(51):
        store_memory(kb, "fake", {"title": f"item {i}", "tags": []})
    drain(kb.huey)

    code, output = invoke(kb, "list", "fake")

    assert code == 0, output
    lines = output.splitlines()
    assert len(lines) == 51
    assert lines[-1].startswith("next cursor: ")


@pytest.mark.parametrize("value", ["0", "1001"])
def test_a_list_limit_or_search_top_k_out_of_range_is_a_usage_error(value: str) -> None:
    kb = cli_kb()

    for args in (("list", "fake", "--limit", value), ("search", "sky", "--top-k", value)):
        code, output = invoke(kb, *args)
        assert code == 2
        assert f"{value} is not in the range 1<=x<=1000" in output


def test_a_literal_field_is_a_choice_and_optional_or_defaulted_ones_may_be_left_out() -> None:
    kb = cli_kb()
    code, output = invoke(kb, "store-note", "--category", "wish", "--text", "x")
    assert code == 2
    assert "'fact', 'goal'" in output

    code, output = invoke(kb, "store-note", "--category", "goal", "--text", "ship it")
    drain(kb.huey)

    assert code == 0, output
    _, shown = invoke(kb, "get", "note", str(item_id_in(output)))
    assert "(goal) ship it via None #inbox  (updated " in shown


def test_a_rejected_payload_exits_1_with_the_reason() -> None:
    code, output = invoke(cli_kb(), "store-fake", "--title", " ")

    assert code == 1
    assert "embed text is empty" in output


def test_update_prints_the_new_id_and_the_old_one_is_gone_after_the_worker() -> None:
    kb = cli_kb()
    _, stored = invoke(kb, "store-fake", "--title", "sky")
    drain(kb.huey)
    old = item_id_in(stored)

    code, output = invoke(kb, "update-fake", str(old), "--title", "sky by day")
    drain(kb.huey)

    assert code == 0, output
    new = item_id_in(output)
    assert new != old
    assert invoke(kb, "get", "fake", str(old)) == (1, f"Error: no fake item has id {old}\n")
    code, output = invoke(kb, "delete", "fake", str(new))
    assert code == 0, output
    assert output.startswith(f"deleted fake {new}\nrequest_id: ")
    assert item_id_in(output) == new
    assert "status: queued" in output
    drain(kb.huey)
    request_id = re.findall(r"request_id: (\S+)", output)[0]
    assert invoke(kb, "request-status", request_id) == (0, "done\n")
    assert invoke(kb, "list", "fake") == (0, "")


def test_list_pages_with_the_printed_cursor() -> None:
    kb = cli_kb()
    for title in ("a", "b"):
        invoke(kb, "store-fake", "--title", title)
    drain(kb.huey)

    _, first = invoke(kb, "list", "fake", "--limit", "1")
    match = re.search(r"next cursor: (\S+)", first)
    assert match is not None, first
    _, second = invoke(kb, "list", "fake", "--cursor", match.group(1))

    assert len(first.splitlines()) == 2
    assert len(second.splitlines()) == 1
    assert "next cursor" not in second


def test_request_status_prints_queued_done_or_failed_with_the_error() -> None:
    kb = cli_kb()
    _, stored = invoke(kb, "store-fake", "--title", "sky")
    request_id = re.findall(r"request_id: (\S+)", stored)[0]
    assert invoke(kb, "request-status", request_id) == (0, "queued\n")
    failing = enqueue_write(
        kb.write_memory,
        kind="uninstalled",
        item_id=uuid4(),
        payload={},
        updated_at=datetime.now(UTC),
        replaces=None,
    )
    drain(kb.huey)

    assert invoke(kb, "request-status", request_id) == (0, "done\n")
    code, output = invoke(kb, "request-status", failing)
    assert code == 0
    assert output.startswith("failed: ")
    assert "unknown memory kind 'uninstalled'" in output


def test_kinds_prints_each_kind_with_its_payload_schema() -> None:
    code, output = invoke(cli_kb(), "kinds")

    assert code == 0
    assert [line.split(":")[0] for line in output.splitlines()] == ["fake", "note"]
    assert '"title": "FakePayload"' in output


def test_reembed_lists_the_too_long_and_exits_1_as_the_copy_is_incomplete(tmp_path: Path) -> None:
    model_a = cli_kb(tmp_path, FakeEmbedder("fake-a"))
    invoke(model_a, "store-fake", "--title", "sky")
    _, long = invoke(model_a, "store-fake", "--title", "long", "--tags", "a", "--tags", "b")
    assert drain(model_a.huey) == (2, 0)
    model_b = cli_kb(tmp_path, FakeEmbedder("fake-b", max_input_tokens=2))

    code, output = invoke(model_b, "reembed", "--from", "memory-fake-a")

    assert code == 1, output
    assert output == (
        "copied 1, skipped 0 already present, 0 deleted since\n"
        f"too long, left out: {item_id_in(long)}\n"
        "Error: 1 item(s) too long for the active embedder were not copied\n"
    )
    assert invoke(model_b, "reembed", "--from", "memory-nope")[0] == 1
    model_c = cli_kb(tmp_path, FakeEmbedder("fake-c"))
    assert invoke(model_c, "reembed", "--from", "memory-fake-a") == (
        0,
        "copied 2, skipped 0 already present, 0 deleted since\n",
    )


def test_main_opens_the_installed_kinds_on_the_overlay(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["request-status", "unknown"])

    assert exit_info.value.code == 1
    assert "no request 'unknown' was queued" in capsys.readouterr().err


def test_main_reports_a_kind_that_fails_to_load_even_under_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"], load=lambda: load_kinds("tools_knowledge_base.tests.broken_kinds"))

    assert exit_info.value.code == 1
    assert capsys.readouterr().err.startswith("Error: memory kind entry point 'broken'")
