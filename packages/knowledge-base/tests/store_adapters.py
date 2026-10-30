"""Each installed ``VectorStore`` adapter's settings, and the points the conformance suite uses."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

from fake_embedder import FakeEmbedder
from pydantic import JsonValue

from knowledge_base_config import Environment
from tools_knowledge_base.configs.settings import (
    KnowledgeBaseSettings,
    LanceDBSettings,
    VectorStoreSettings,
    get_settings,
)
from tools_knowledge_base.store.protocol import Point


def _qdrant(tmp_path: Path) -> KnowledgeBaseSettings:
    # The testing overlay: in-process local mode, its storage the client's own.
    return get_settings(Environment.TESTING)


def _lancedb(tmp_path: Path) -> KnowledgeBaseSettings:
    # One small fragment allowed, so every second write runs the compaction branch.
    return get_settings(Environment.TESTING).model_copy(
        update={
            "vector_store": VectorStoreSettings(
                collection_prefix="memory",
                backend="lancedb",
                lancedb=LanceDBSettings(path=tmp_path / "lancedb", max_small_fragments=1),
            )
        }
    )


ADAPTERS: dict[str, Callable[[Path], KnowledgeBaseSettings]] = {
    "lancedb": _lancedb,
    "qdrant": _qdrant,
}
"""Adapter name to the settings that select it; one row per installed adapter."""

COLLECTION = "memory-fake-8"
EMBEDDER = FakeEmbedder()
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def point(
    text: str,
    *,
    kind: str = "fake",
    point_id: UUID | None = None,
    at: datetime = T0,
) -> Point:
    """A point of ``kind`` titled ``text``, its vector the fake embedding of ``text``."""
    payload: dict[str, JsonValue] = {"title": text, "tags": ["a"]}
    return Point(
        id=point_id or uuid4(),
        kind=kind,
        updated_at=at,
        payload=payload,
        vector=EMBEDDER.embed_documents([text])[0],
    )


# Adapter-independent: it checks core's adapter table, not an adapter package's store.
_NOT_PER_ADAPTER = {"test_every_installed_adapter_has_a_row"}


class NoCoreTestsError(RuntimeError):
    """A core module yielded nothing to re-export, so an adapter package would run none of it."""

    def __init__(self, module: str) -> None:
        super().__init__(f"no core tests to re-export from {module}")


class DuplicateCoreTestError(RuntimeError):
    """Two core modules define a test of one name, so re-exporting both would drop one."""

    def __init__(self, name: str, modules: tuple[str, str]) -> None:
        super().__init__(f"core test {name} is defined in both {modules[0]} and {modules[1]}")


def core_tests(*modules: ModuleType) -> dict[str, object]:
    """Every per-adapter ``test*`` function and ``Test*`` class each of ``modules`` defines.

    Names a module only imports are skipped, a name two modules define is refused, and so
    is a module that yields none.
    """
    found: dict[str, object] = {}
    origin: dict[str, str] = {}
    for module in modules:
        own = {
            name: value
            for name, value in vars(module).items()
            if name.startswith(("test", "Test"))
            and name not in _NOT_PER_ADAPTER
            and getattr(value, "__module__", None) == module.__name__
        }
        if not own:
            raise NoCoreTestsError(module.__name__)
        for name, value in own.items():
            if name in found:
                raise DuplicateCoreTestError(name, (origin[name], module.__name__))
            found[name] = value
            origin[name] = module.__name__
    return found
