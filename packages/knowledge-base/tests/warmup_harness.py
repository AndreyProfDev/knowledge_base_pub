"""Warm-up directories under ``tmp_path``, reached through ``settings=``."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import override

import yaml
from fake_embedder import FakeEmbedder
from huey import MemoryHuey  # pyright: ignore[reportMissingTypeStubs]
from huey.api import ChordResult, Result, ResultGroup  # pyright: ignore[reportMissingTypeStubs]

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import (
    KnowledgeBaseSettings,
    WarmupSettings,
    get_settings,
)
from tools_knowledge_base.errors import KnowledgeBaseError


def warmup_settings(
    path: Path, retries: int | None = None, *, dump: bool = False, due_retries: bool = False
) -> KnowledgeBaseSettings:
    """The testing overlay loading warm-up files from ``path``, and with ``dump`` writing there.

    ``dump`` is off by default: a dump copy shadows a later edit of the hand-written file.
    ``due_retries`` makes a retry due at once, so a drain runs it.
    """
    settings = get_settings(Environment.TESTING)
    update: dict[str, object] = {"warmup": WarmupSettings(path=path, dump=dump)}
    queue: dict[str, object] = {} if retries is None else {"retries": retries}
    if due_retries:
        queue["retry_delay_seconds"] = 0
    update["queue"] = settings.queue.model_copy(update=queue)
    return settings.model_copy(update=update)


def write_yaml(path: Path, content: object) -> None:
    path.write_text(yaml.safe_dump(content), encoding="utf-8")


def fake_items(*titles: str) -> list[dict[str, object]]:
    return [{"title": title, "tags": ["a"]} for title in titles]


class FailingHuey(MemoryHuey):
    """A ``MemoryHuey`` whose enqueues after the first ``allowed`` raise ``error``."""

    def __init__(self, allowed: int, error: BaseException | None = None) -> None:
        super().__init__("knowledge-base")  # pyright: ignore[reportUnknownMemberType]
        self.allowed = allowed
        self.error = error or OSError("queue storage unreachable")

    @override
    def enqueue(self, task: object) -> ResultGroup | ChordResult | Result | None:
        if not self.allowed:
            raise self.error
        self.allowed -= 1
        return super().enqueue(task)  # pyright: ignore[reportUnknownMemberType]


class UnrecordableHuey(MemoryHuey):
    """A ``MemoryHuey`` whose ``put`` raises for a key starting with ``prefix``."""

    def __init__(self, prefix: str) -> None:
        super().__init__("knowledge-base")  # pyright: ignore[reportUnknownMemberType]
        self.prefix = prefix

    @override
    def put(self, key: str, data: object) -> None:
        if key.startswith(self.prefix):
            msg = "queue storage unreachable"
            raise OSError(msg)
        super().put(key, data)  # pyright: ignore[reportUnknownMemberType]


class FailingUnrecordableHuey(FailingHuey):
    """A ``FailingHuey`` whose ``put`` of a warm-up run record raises."""

    @override
    def put(self, key: str, data: object) -> None:
        if key.startswith("warmup:"):
            msg = "run storage unreachable"
            raise OSError(msg)
        super().put(key, data)  # pyright: ignore[reportUnknownMemberType]


class BoomEmbedder(FakeEmbedder):
    """Fails every text starting with ``boom``."""

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if any(text.startswith("boom") for text in texts):
            msg = "embeddings server unreachable"
            raise KnowledgeBaseError(msg)
        return super().embed_documents(texts)
