"""The installed memory kinds, by name, loaded through stevedore."""

from __future__ import annotations

from collections.abc import Iterator
from importlib.metadata import EntryPoint

from stevedore import ExtensionManager

from tools_knowledge_base.errors import KnowledgeBaseError, UnknownKind
from tools_knowledge_base.kinds.protocol import MemoryKind

MEMORY_KINDS = "tools_knowledge_base.memory_kinds"


class KindRegistry:
    """Every loaded kind, keyed by its own ``name`` (not the entry point's)."""

    def __init__(self, manager: ExtensionManager[MemoryKind]) -> None:
        self._kinds: dict[str, MemoryKind] = {}
        for extension in manager:
            kind = extension.obj
            if kind is None:
                msg = f"memory kind entry point {extension.name!r} was not instantiated"
                raise KnowledgeBaseError(msg)
            if kind.name in self._kinds:
                msg = f"two installed packages provide memory kind {kind.name!r}"
                raise KnowledgeBaseError(msg)
            self._kinds[kind.name] = kind

    def get(self, name: str) -> MemoryKind:
        """The kind called ``name``.

        Raises:
            UnknownKind: no installed package provides it.
        """
        try:
            return self._kinds[name]
        except KeyError:
            msg = f"unknown memory kind {name!r}; installed: {self.names()}"
            raise UnknownKind(msg) from None

    def names(self) -> list[str]:
        """Installed kind names, sorted."""
        return sorted(self._kinds)

    def __iter__(self) -> Iterator[MemoryKind]:
        """Each installed kind, in name order."""
        return (self._kinds[name] for name in self.names())


def _raise_failed(
    _manager: ExtensionManager[MemoryKind], entry: EntryPoint, exc: BaseException
) -> None:
    msg = (
        f"memory kind entry point {entry.name!r} ({entry.value}) failed to load: "
        f"{type(exc).__name__}: {exc}"
    )
    raise KnowledgeBaseError(msg) from exc


def load_kinds(namespace: str = MEMORY_KINDS) -> KindRegistry:
    """Load every kind installed under the entry-point group ``namespace``.

    Raises:
        KnowledgeBaseError: an installed kind fails to load; skipping it would turn
            every later write of that kind into a misleading ``UnknownKind``.
    """
    manager: ExtensionManager[MemoryKind] = ExtensionManager(
        namespace, invoke_on_load=True, on_load_failure_callback=_raise_failed
    )
    return KindRegistry(manager)
