"""The workflow kind through the whole flow: store -> worker -> search -> delete."""

from __future__ import annotations

import pytest
from fake_kb import open_fake_kb
from fake_kind import FakePayload
from pydantic import ValidationError

from tools_knowledge_base.errors import ItemNotFound
from tools_knowledge_base.kinds.registry import load_kinds
from tools_knowledge_base.operations import (
    delete_memory_item,
    get_memory_item,
    get_memory_request,
    search_memory,
    store_memory,
)
from tools_knowledge_base.queue import drain
from tools_knowledge_base_workflow.kind import WorkflowKind, WorkflowPayload


def test_the_installed_entry_point_loads_the_workflow_kind() -> None:
    kind = load_kinds().get("workflow")

    assert isinstance(kind, WorkflowKind)
    assert kind.payload_model is WorkflowPayload


def test_a_workflow_is_stored_found_and_deleted() -> None:
    kb = open_fake_kb(WorkflowKind())
    workflow = {"name": "morning routine", "steps": ["coffee", "email"]}

    accepted = store_memory(kb, "workflow", workflow)
    assert drain(kb.huey) == (1, 0)
    assert get_memory_request(kb, accepted.request_id).status == "done"

    [hit] = search_memory(kb, "routine", kind="workflow")
    assert hit.id == accepted.item_id
    assert hit.payload == WorkflowPayload(name="morning routine", steps=["coffee", "email"])

    delete_memory_item(kb, "workflow", accepted.item_id)
    with pytest.raises(ItemNotFound):
        get_memory_item(kb, "workflow", accepted.item_id)


def test_missing_steps_or_an_overlong_description_fails_at_enqueue() -> None:
    kb = open_fake_kb(WorkflowKind())

    with pytest.raises(ValidationError):
        store_memory(kb, "workflow", {"name": "x"})
    with pytest.raises(ValidationError):
        store_memory(kb, "workflow", {"name": "x", "description": "d" * 496, "steps": ["s"]})

    assert kb.huey.pending_count() == 0
    # "x: " plus 495 characters plus "\ns" is the 500-character cap.
    store_memory(kb, "workflow", {"name": "x", "description": "d" * 495, "steps": ["s"]})
    assert kb.huey.pending_count() == 1


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": "  ", "steps": ["s"]}, "name"),
        ({"name": "", "steps": ["s"]}, "name"),
        ({"name": "w\n1. fake", "steps": ["s"]}, "name"),
        ({"name": "\x1c", "steps": ["s"]}, "name"),
        ({"name": "\N{ZERO WIDTH SPACE}", "steps": ["s"]}, "name"),
        ({"name": "x", "steps": ["\x1c"]}, "steps.0"),
        ({"name": "x", "steps": ["\N{ZERO WIDTH SPACE}"]}, "steps.0"),
        ({"name": "\N{HANGUL FILLER}", "steps": ["s"]}, "name"),
        ({"name": "\N{BRAILLE PATTERN BLANK}", "steps": ["s"]}, "name"),
        ({"name": "\N{COMBINING ACUTE ACCENT}", "steps": ["s"]}, "name"),
        ({"name": "x", "steps": ["\N{HANGUL FILLER}"]}, "steps.0"),
        ({"name": "x", "steps": ["\N{BRAILLE PATTERN BLANK}"]}, "steps.0"),
        ({"name": "x", "steps": ["\N{COMBINING ACUTE ACCENT}"]}, "steps.0"),
        ({"name": "x", "steps": []}, "steps"),
        ({"name": "x", "steps": [""]}, "steps.0"),
        ({"name": "x", "steps": ["ok", "two\nlines"]}, "steps.1"),
        ({"name": "x", "steps": ["trailing\n"]}, "steps.0"),
        ({"name": "x", "steps": ["   "]}, "steps.0"),
        ({"name": "x", "steps": ["a\rb"]}, "steps.0"),
        ({"name": "x", "steps": ["a\vb"]}, "steps.0"),
        ({"name": "x", "steps": ["a\x85b"]}, "steps.0"),
        ({"name": "x", "steps": ["a\N{LINE SEPARATOR}b"]}, "steps.0"),
        ({"name": "x", "steps": ["a\x1eb"]}, "steps.0"),
    ],
)
def test_an_invalid_name_or_step_fails_at_enqueue_naming_the_field(
    payload: dict[str, object], field: str
) -> None:
    kb = open_fake_kb(WorkflowKind())

    with pytest.raises(ValidationError) as caught:
        store_memory(kb, "workflow", payload)

    assert [".".join(map(str, error["loc"])) for error in caught.value.errors()] == [field]
    assert kb.huey.pending_count() == 0


def test_a_multi_line_step_is_rejected_in_plain_words() -> None:
    with pytest.raises(ValidationError, match="must be one non-blank line"):
        WorkflowPayload(name="x", steps=["a\fb"])


def test_surrounding_whitespace_is_not_part_of_the_identity() -> None:
    kind = WorkflowKind()

    assert kind.key(WorkflowPayload(name=" deploy\t", steps=["s"])) == "deploy"


def test_render_embed_text_and_key() -> None:
    kind = WorkflowKind()
    payload = WorkflowPayload(name="deploy", description="ship it", steps=["build", "push"])

    assert kind.render(payload) == "deploy: ship it\n1. build\n2. push"
    assert kind.embed_text(payload) == "deploy: ship it\nbuild\npush"
    assert kind.key(payload) == "deploy"


def test_render_is_one_header_line_then_exactly_the_steps() -> None:
    kind = WorkflowKind()
    payload = WorkflowPayload(
        name="deploy", description="intro\n2. forged\v3. too", steps=["build", "push"]
    )

    rendered = kind.render(payload)

    assert rendered.splitlines() == ["deploy: intro 2. forged 3. too", "1. build", "2. push"]
    assert kind.embed_text(payload) == "deploy: intro\n2. forged\v3. too\nbuild\npush"


def test_schema_carries_the_step_ui_hint_and_the_length_bounds() -> None:
    properties = WorkflowPayload.model_json_schema()["properties"]

    assert properties["steps"]["items"]["title"] == "Step"
    assert properties["steps"]["items"]["minLength"] == 1
    assert properties["steps"]["minItems"] == 1
    assert properties["name"]["minLength"] == 1
    assert "maxLength" not in properties["description"]
    assert properties["description"]["x-long-text"] is True


@pytest.mark.parametrize(
    "description",
    [
        "",
        "  ",
        chr(0x200B),
        "\x1c",
        "\N{HANGUL FILLER}",
        "\N{BRAILLE PATTERN BLANK}",
        "\N{COMBINING ACUTE ACCENT}",
    ],
)
def test_a_missing_or_blank_description_leaves_the_header_just_the_name(description: str) -> None:
    kind = WorkflowKind()
    payload = WorkflowPayload(name="deploy", description=description, steps=["build"])

    assert kind.render(payload) == "deploy\n1. build"
    assert kind.embed_text(payload) == "deploy\nbuild"


@pytest.mark.parametrize("method", ["key", "embed_text", "render"])
def test_another_kinds_payload_is_refused(method: str) -> None:
    with pytest.raises(TypeError, match="got a FakePayload payload"):
        getattr(WorkflowKind(), method)(FakePayload(title="t", tags=[]))
