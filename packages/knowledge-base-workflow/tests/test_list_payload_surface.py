"""The generated ``store-workflow`` / ``update-workflow`` bind a repeated ``--steps`` as a list."""

from __future__ import annotations

from cli_harness import invoke, item_id_in
from fake_kb import open_fake_kb

from tools_knowledge_base.operations import get_memory_item
from tools_knowledge_base.queue import drain
from tools_knowledge_base_workflow.kind import WorkflowKind, WorkflowPayload


def test_repeated_steps_bind_in_order() -> None:
    kb = open_fake_kb(WorkflowKind())

    code, out = invoke(kb, "store-workflow", "--name", "routine", "--steps", "x", "--steps", "y")
    assert code == 0, out
    assert drain(kb.huey) == (1, 0)

    assert get_memory_item(kb, "workflow", item_id_in(out)).payload == WorkflowPayload(
        name="routine", steps=["x", "y"]
    )


def test_omitted_steps_are_rejected_and_nothing_is_queued() -> None:
    kb = open_fake_kb(WorkflowKind())

    code, out = invoke(kb, "store-workflow", "--name", "empty", "--description", "nothing yet")
    assert code != 0, out
    assert "steps" in out
    assert kb.huey.pending_count() == 0


def test_an_update_without_steps_is_rejected_and_the_stored_steps_survive() -> None:
    kb = open_fake_kb(WorkflowKind())
    _, out = invoke(kb, "store-workflow", "--name", "routine", "--steps", "a", "--steps", "b")
    assert drain(kb.huey) == (1, 0)
    item_id = item_id_in(out)

    code, out = invoke(kb, "update-workflow", str(item_id), "--name", "renamed")
    assert code != 0, out
    assert "steps" in out
    assert kb.huey.pending_count() == 0

    assert get_memory_item(kb, "workflow", item_id).payload == WorkflowPayload(
        name="routine", steps=["a", "b"]
    )


def test_the_help_explains_steps_and_the_optional_description() -> None:
    code, out = invoke(open_fake_kb(WorkflowKind()), "store-workflow", "--help")
    assert code == 0, out
    flat = " ".join(out.split())
    assert (
        "One or more steps, in order — on the CLI repeat --steps once per step;"
        " each a single non-blank line." in flat
    )
    assert "Optional. Replaced along with the whole workflow on update." in flat
    assert (
        "One non-blank line; surrounding whitespace is stripped, not part of the identity." in flat
    )


def test_an_update_without_a_description_clears_the_stored_one() -> None:
    kb = open_fake_kb(WorkflowKind())
    _, out = invoke(kb, "store-workflow", "--name", "r", "--description", "old", "--steps", "a")
    assert drain(kb.huey) == (1, 0)
    item_id = item_id_in(out)

    code, out = invoke(kb, "update-workflow", str(item_id), "--name", "r", "--steps", "a")
    assert code == 0, out
    assert drain(kb.huey) == (1, 0)

    assert get_memory_item(kb, "workflow", item_id).payload == WorkflowPayload(
        name="r", steps=["a"]
    )


def test_update_replaces_the_steps_and_search_accepts_the_kind() -> None:
    kb = open_fake_kb(WorkflowKind())
    _, out = invoke(kb, "store-workflow", "--name", "routine", "--steps", "a", "--steps", "b")
    assert drain(kb.huey) == (1, 0)
    item_id = item_id_in(out)

    code, out = invoke(kb, "update-workflow", str(item_id), "--name", "routine", "--steps", "z")
    assert code == 0, out
    assert item_id_in(out) == item_id
    assert drain(kb.huey) == (1, 0)

    code, out = invoke(kb, "search", "routine", "--kind", "workflow")
    assert code == 0, out
    assert "routine\n1. z" in out
    assert "2. " not in out
