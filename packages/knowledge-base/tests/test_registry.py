from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

import pytest
from fake_kind import FakeKind, FakePayload
from stevedore import ExtensionManager
from stevedore.extension import Extension

from tools_knowledge_base.errors import KnowledgeBaseError, UnknownKind
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import (
    MEMORY_KINDS,
    KindRegistry,
    _raise_failed,
    load_kinds,
)


def _extension(entry_name: str, kind: MemoryKind | None) -> Extension[MemoryKind]:
    entry = EntryPoint(name=entry_name, value="fake_kind:FakeKind", group=MEMORY_KINDS)
    return Extension(entry_name, entry, FakeKind, kind)


def _registry(*extensions: Extension[MemoryKind]) -> KindRegistry:
    return KindRegistry(ExtensionManager[MemoryKind].make_test_instance(list(extensions)))


def test_discovery_loads_every_installed_kind() -> None:
    installed = sorted(e.name for e in entry_points(group=MEMORY_KINDS))

    assert load_kinds().names() == installed


def test_a_kind_that_fails_to_load_raises_naming_the_entry_point() -> None:
    entry = EntryPoint(name="broken", value="nowhere:Kind", group=MEMORY_KINDS)
    manager = ExtensionManager[MemoryKind].make_test_instance([])
    cause = ImportError("no module named nowhere")

    with pytest.raises(
        KnowledgeBaseError,
        match=r"'broken' \(nowhere:Kind\) failed to load: ImportError: no module named nowhere",
    ) as raised:
        _raise_failed(manager, entry, cause)

    assert raised.value.__cause__ is cause


def test_loading_an_installed_kind_that_cannot_be_imported_raises() -> None:
    # tests/broken_kind-0.dist-info, on the test path, declares this group's one entry.
    with pytest.raises(KnowledgeBaseError, match=r"'broken' .* failed to load: ModuleNotFound"):
        load_kinds("tools_knowledge_base.tests.broken_kinds")


def test_get_returns_the_kind_by_its_own_name() -> None:
    fake = FakeKind()
    registry = _registry(_extension("entry-name-differs", fake))

    assert registry.get("fake") is fake
    assert registry.get("fake").key(FakePayload(title="t", tags=[])) == "t"


def test_names_and_iteration_are_sorted() -> None:
    zeta, alpha = FakeKind("zeta"), FakeKind("alpha")
    registry = _registry(_extension("z", zeta), _extension("a", alpha))

    assert registry.names() == ["alpha", "zeta"]
    assert list(registry) == [alpha, zeta]


def test_duplicate_kind_names_are_rejected() -> None:
    with pytest.raises(
        KnowledgeBaseError, match="two installed packages provide memory kind 'fake'"
    ):
        _registry(_extension("one", FakeKind()), _extension("two", FakeKind()))


def test_an_extension_not_instantiated_is_rejected() -> None:
    with pytest.raises(KnowledgeBaseError, match="'lazy' was not instantiated"):
        _registry(_extension("lazy", None))


def test_unknown_kind_is_rejected_naming_the_installed_ones() -> None:
    registry = _registry(_extension("fake", FakeKind()))

    with pytest.raises(UnknownKind, match=r"unknown memory kind 'nope'; installed: \['fake'\]"):
        registry.get("nope")
