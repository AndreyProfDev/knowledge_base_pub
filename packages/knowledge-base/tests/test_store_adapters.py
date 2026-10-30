"""``core_tests``: what the adapter packages re-export of core's store suites."""

from __future__ import annotations

from types import ModuleType

import pytest
from store_adapters import DuplicateCoreTestError, NoCoreTestsError, core_tests


def _module(name: str, *tests: str, imported: tuple[str, ...] = ()) -> ModuleType:
    """A module defining ``tests`` and holding ``imported``, objects defined elsewhere."""
    module = ModuleType(name)
    for test in (*tests, *imported):

        def body() -> None: ...

        body.__module__ = name if test in tests else "elsewhere"
        setattr(module, test, body)
    return module


def test_re_exports_what_each_module_defines_and_skips_what_it_imports() -> None:
    first = _module("first", "test_a", imported=("test_helper", "TestImported"))
    second = _module("second", "test_b")

    found = core_tests(first, second)

    assert found == {"test_a": first.test_a, "test_b": second.test_b}


def test_the_adapter_table_check_is_not_re_exported() -> None:
    module = _module("m", "test_a", "test_every_installed_adapter_has_a_row")

    assert core_tests(module) == {"test_a": module.test_a}


def test_a_name_two_modules_define_is_refused() -> None:
    with pytest.raises(DuplicateCoreTestError, match="test_a is defined in both first and second"):
        core_tests(_module("first", "test_a"), _module("second", "test_a"))


def test_a_module_yielding_no_tests_is_refused() -> None:
    with pytest.raises(NoCoreTestsError, match=r"from empty$"):
        core_tests(_module("full", "test_a"), _module("empty", imported=("test_helper",)))
