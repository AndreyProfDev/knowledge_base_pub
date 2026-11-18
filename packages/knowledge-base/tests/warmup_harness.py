"""Warm-up directories under ``tmp_path``, reached through ``settings=``."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import override

import yaml
from fake_embedder import FakeEmbedder
from fake_kb import temp_sqlite_settings

from tools_knowledge_base.configs.settings import KnowledgeBaseSettings, WarmupSettings
from tools_knowledge_base.errors import KnowledgeBaseError


def warmup_settings(path: Path, *, dump: bool = False) -> KnowledgeBaseSettings:
    """The testing overlay loading warm-up files from ``path``, and with ``dump`` writing there.

    ``dump`` is off by default: a dump copy shadows a later edit of the hand-written file.
    """
    settings = temp_sqlite_settings()
    return settings.model_copy(update={"warmup": WarmupSettings(path=path, dump=dump)})


def write_yaml(path: Path, content: object) -> None:
    path.write_text(yaml.safe_dump(content), encoding="utf-8")


def fake_items(*titles: str) -> list[dict[str, object]]:
    return [{"title": title, "tags": ["a"]} for title in titles]


class FailOnCallEmbedder(FakeEmbedder):
    """Raises ``error`` on its ``call``-th ``embed_documents`` call (1-based)."""

    def __init__(self, call: int, error: Exception | None = None) -> None:
        super().__init__()
        self.call = call
        self.error = error or OSError("embeddings server unreachable")

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if len(self.batch_sizes) + 1 == self.call:
            self.batch_sizes.append(len(texts))
            raise self.error
        return super().embed_documents(texts)


class ShortEmbedder(FakeEmbedder):
    """Returns one vector too few."""

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return super().embed_documents(texts)[:-1]


class BoomEmbedder(FakeEmbedder):
    """Fails every text starting with ``boom``."""

    @override
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if any(text.startswith("boom") for text in texts):
            msg = "embeddings server unreachable"
            raise KnowledgeBaseError(msg)
        return super().embed_documents(texts)
