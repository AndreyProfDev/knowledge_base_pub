"""The kind-agnostic tools: search, request status, and warm-up."""

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
    get_warmup_progress,
    search_memory,
    warmup_memory,
)
from tools_knowledge_base.server.tools_kinds import Tool, named

_KEYWORD = inspect.Parameter.KEYWORD_ONLY
_WARMUP_DOC = (
    "Queue every item in the server's warm-up directory of YAML files that is not already "
    "stored unchanged; a stored item with the same key but different content is "
    "overwritten, and nothing is deleted. Any bad file or item queues nothing and is "
    "reported with its file, kind and index; a directory holding no items is an error. "
    "Poll get_warmup_progress with the `run_id`."
)
_PROGRESS_DOC = (
    "Report warm-up run `run_id`: how many of its writes are done, failed and pending, "
    "and the first failures. A failing write stays pending through its retries, about "
    "150 s, before it counts as failed."
)


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
    """The generic tools, bound to ``kb``; all but ``warmup_memory`` read-only."""
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
        "`queued` until the worker has run it, then `done`, or `failed` with the error."
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
        (
            bind(warmup_memory, kb, _WARMUP_DOC),
            ToolAnnotations(destructive_hint=True, idempotent_hint=True),
        ),
        (bind(get_warmup_progress, kb, _PROGRESS_DOC), read_only),
    ]
