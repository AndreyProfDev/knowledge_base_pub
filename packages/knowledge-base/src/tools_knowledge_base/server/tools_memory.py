"""The kind-agnostic tools: search and request status."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Annotated, Any, Concatenate, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import MemoryHit
from tools_knowledge_base.operations import (
    MAX_LIMIT,
    get_memory_request,
    search_memory,
)
from tools_knowledge_base.server.tools_kinds import Tool, named

_KEYWORD = inspect.Parameter.KEYWORD_ONLY


def bind[**P, R](
    func: Callable[Concatenate[KnowledgeBase, P], R], kb: KnowledgeBase, doc: str
) -> Callable[P, R]:
    """Curry ``kb`` out of ``func``'s signature, keeping its name; ``doc`` is what the model reads.

    ``update_wrapper`` also sets ``__wrapped__``, which ``inspect.signature`` follows
    back to ``func``: the tool schema would then offer ``kb`` to the model.
    """
    bound = functools.update_wrapper(functools.partial(func, kb), func)
    del bound.__wrapped__
    bound.__doc__ = doc
    return bound


def _search_parameters(kinds: list[str]) -> list[inspect.Parameter]:
    """``search_memory``'s schema: ``kind`` an enum of the installed kinds, ``top_k`` in range.

    Runtime type expressions, typed ``Any``: the kinds are known only once ``kb`` is open,
    and a type checker reads neither a computed ``Literal`` nor ``Annotated | None`` as a
    value.
    """
    literal: Any = Literal
    positive: Any = Annotated[int, Field(ge=1, le=MAX_LIMIT)]
    return [
        inspect.Parameter("query", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
        inspect.Parameter("kind", _KEYWORD, default=None, annotation=literal[tuple(kinds)] | None),
        inspect.Parameter("top_k", _KEYWORD, default=None, annotation=positive | None),
        inspect.Parameter("min_score", _KEYWORD, default=None, annotation=float | None),
    ]


def tools(kb: KnowledgeBase) -> list[Tool]:
    """The generic tools, bound to ``kb``; all read-only."""
    read_only = ToolAnnotations(read_only_hint=True)
    kinds = kb.kinds.names()
    search_doc = (
        "Search the stored memories semantically for `query`, best match first. `kind` "
        f"limits the search to one kind, one of: {', '.join(kinds)}; omitted, every kind is "
        "searched. `top_k` caps the number of hits and `min_score` drops weaker ones; both "
        "default to the server's configuration. `min_score` is a cosine similarity; "
        "higher is closer."
    )
    request_doc = (
        "Report a queued request by the `request_id` a store, update or delete returned: "
        "`queued` until this server has run it, then `done`, or `failed` with the error."
    )

    def search(
        query: str,
        *,
        kind: str | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[MemoryHit]:
        return search_memory(kb, query, kind=kind, top_k=top_k, min_score=min_score)

    return [
        (
            named(search, "search_memory", search_doc, _search_parameters(kinds), list[MemoryHit]),
            read_only,
        ),
        (bind(get_memory_request, kb, request_doc), read_only),
    ]
