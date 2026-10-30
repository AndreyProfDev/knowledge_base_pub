"""The generated verbs' options, arguments and help, over a strict kind with described fields."""

from __future__ import annotations

from uuid import uuid4

import pytest
from cli_harness import invoke, item_id_in
from fake_kb import fake_registry, open_fake_kb
from fake_kind import FakeKind
from pydantic import BaseModel, ConfigDict, Field

from tools_knowledge_base.cli.main import main
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.queue import drain


class TaskPayload(BaseModel):
    """Strict, so a repeated option must arrive as a list; a list field before a plain one."""

    model_config = ConfigDict(strict=True)

    steps: list[str] = Field(description="One step per option.")
    due_date: str = Field(description="When it is due.")


class TaskKind:
    """Keyed and embedded by its steps."""

    name = "task"
    payload_model: type[BaseModel] = TaskPayload
    counted_over = "steps"
    oversize_hint = "Fewer steps."

    def key(self, payload: BaseModel) -> str:
        return " ".join(payload.model_dump()["steps"])

    def embed_text(self, payload: BaseModel) -> str:
        return self.key(payload)

    def render(self, payload: BaseModel) -> str:
        task = payload.model_dump()
        return f"{'; '.join(task['steps'])} by {task['due_date']}"


def _kb() -> KnowledgeBase:
    return open_fake_kb(FakeKind(), TaskKind())


def _flat(output: str) -> str:
    return " ".join(output.split())


def test_a_repeated_option_reaches_a_strict_model_as_a_list_and_later_fields_stay() -> None:
    kb = _kb()

    code, output = invoke(
        kb, "store-task", "--steps", "plan", "--steps", "ship", "--due-date", "friday"
    )
    drain(kb.huey)

    assert code == 0, output
    _, shown = invoke(kb, "get", "task", str(item_id_in(output)))
    assert shown.startswith(f"task  {item_id_in(output)}  plan; ship by friday  (updated ")


def test_a_required_field_left_out_is_a_usage_error() -> None:
    code, output = invoke(_kb(), "store-task", "--steps", "plan")

    assert code == 2
    assert "Missing option '--due-date'" in output


def test_store_and_update_help_show_the_verb_and_each_field_description() -> None:
    kb = _kb()

    code, store = invoke(kb, "store-task", "--help")
    _, update = invoke(kb, "update-task", "--help")

    assert code == 0, store
    for text in (store, update):
        assert "One step per option." in text
        assert "When it is due." in text
    assert "Queue a new task item; prints its request and item ids." in _flat(store)
    assert update.startswith("Usage: knowledge-base-cli update-task [OPTIONS] ID\n")
    assert "Queue a replacement for task item ID; prints the id its new key derives." in _flat(
        update
    )


def test_get_and_delete_show_their_kind_choices_and_id_in_usage() -> None:
    kb = _kb()

    for verb in ("get", "delete"):
        code, output = invoke(kb, verb, "--help")
        assert code == 0, output
        assert output.startswith(f"Usage: knowledge-base-cli {verb} [OPTIONS] {{fake|task}} ID\n")


@pytest.mark.parametrize("verb", ["get", "delete"])
def test_an_uninstalled_kind_or_a_malformed_id_is_a_usage_error(verb: str) -> None:
    kb = _kb()

    code, output = invoke(kb, verb, "nope", str(uuid4()))
    assert code == 2
    assert "Invalid value for '{fake|task}': 'nope' is not one of 'fake', 'task'." in output
    code, output = invoke(kb, verb, "fake", "nope")
    assert code == 2
    assert "Invalid value for 'ID': 'nope' is not a valid UUID." in output


def test_update_with_a_malformed_id_is_a_usage_error() -> None:
    code, output = invoke(_kb(), "update-task", "nope", "--steps", "a", "--due-date", "x")

    assert code == 2
    assert "Invalid value for 'ID': 'nope' is not a valid UUID." in output


def test_main_opens_the_knowledge_base_over_the_kinds_it_loaded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["kinds"], load=lambda: fake_registry(TaskKind()))

    assert exit_info.value.code == 0
    assert [line.split(":")[0] for line in capsys.readouterr().out.splitlines()] == ["task"]
