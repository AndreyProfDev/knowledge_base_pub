"""``knowledge-base-cli`` run in-process over a fake and a note kind, for the CLI tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from click.testing import CliRunner
from fake_embedder import FakeEmbedder
from fake_kb import lancedb_settings, open_fake_kb
from fake_kind import FakeKind
from pydantic import BaseModel, Field

from knowledge_base_config import Environment
from tools_knowledge_base.cli.context import CliContext
from tools_knowledge_base.cli.main import build_cli
from tools_knowledge_base.context import KnowledgeBase


class NotePayload(BaseModel):
    category: Literal["fact", "goal"]
    text: str
    source: str | None = None
    labels: list[str] = Field(default_factory=lambda: ["inbox"])


class NoteKind:
    """A second fake: a ``Literal`` field, an optional one and a defaulted list."""

    name = "note"
    payload_model: type[BaseModel] = NotePayload
    counted_over = "text"
    oversize_hint = "Shorten the note."

    def key(self, payload: BaseModel) -> str:
        return payload.model_dump()["text"]

    def embed_text(self, payload: BaseModel) -> str:
        return payload.model_dump()["text"]

    def render(self, payload: BaseModel) -> str:
        note = payload.model_dump()
        labels = ",".join(note["labels"])
        return f"({note['category']}) {note['text']} via {note['source']} #{labels}"


def cli_kb(
    settings_path: Path | None = None, embedder: FakeEmbedder | None = None
) -> KnowledgeBase:
    """The fake and note kinds, on LanceDB under ``settings_path`` when one is given."""
    settings = None if settings_path is None else lancedb_settings(settings_path)
    return open_fake_kb(FakeKind(), NoteKind(), settings=settings, embedder=embedder)


def invoke(kb: KnowledgeBase, *args: str) -> tuple[int, str]:
    """Exit code and output of ``knowledge-base-cli --env testing ARGS`` over ``kb``."""
    opened: list[Environment] = []

    def open_kb(env: Environment) -> KnowledgeBase:
        opened.append(env)
        return kb

    result = CliRunner().invoke(
        build_cli(kb.kinds), ["--env", "testing", *args], obj=CliContext(open_kb=open_kb)
    )
    assert opened in ([], [Environment.TESTING])
    return result.exit_code, result.output


def item_id_in(output: str) -> UUID:
    """The ``item_id:`` a store or update verb printed."""
    match = re.search(r"item_id: (\S+)", output)
    assert match is not None, output
    return UUID(match.group(1))
