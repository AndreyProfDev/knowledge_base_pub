"""Core's vector-store suites, collected here so ``make mutation`` runs them on this package.

mutmut runs only the package's own ``tests`` (paths outside it lose their node ids), and
``conftest.py`` here narrows the ``settings`` and ``store`` fixtures to LanceDB. Every
``test*`` function and ``Test*`` class of the two core modules (pytest's default collection
prefixes) is re-exported, so a test added there runs here too.
"""

from __future__ import annotations

import test_vector_store_conformance
import test_vector_store_search
from store_adapters import core_tests

globals().update(core_tests(test_vector_store_conformance, test_vector_store_search))
