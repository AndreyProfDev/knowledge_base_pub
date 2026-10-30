"""``CliContext``: how a command opens its knowledge base; tests pass one as ``obj=``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from knowledge_base_config import Environment
from tools_knowledge_base.context import KnowledgeBase


@dataclass(frozen=True)
class CliContext:
    """The ``--env`` overlay, and the opener a command calls with it."""

    open_kb: Callable[[Environment], KnowledgeBase]
    env: Environment = Environment.LOCAL

    def kb(self) -> KnowledgeBase:
        """The knowledge base for ``env``, opened when a command runs, so ``--help`` needs none."""
        return self.open_kb(self.env)
