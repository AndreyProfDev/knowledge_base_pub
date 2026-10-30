"""Per-kind tools generated from each kind's ``payload_model``: store, update, get, list, delete.

Each is a closure over one kind, its ``__signature__`` built by hand: the MCP SDK reads
the input schema off the parameters and the output schema off ``return_annotation``
(``func_metadata`` honours ``__signature__``), so ``store_knowledge`` takes
``category`` and ``content`` rather than an opaque payload dict.

One rule decides which payloads reach the tools: every payload field must be *plain*,
because field name, tool parameter, schema property and stored key are one name. A
field is not plain when it has an alias (``alias``, ``validation_alias`` or
``serialization_alias``, as an alias generator sets them), is excluded from dumps, has
a name that is not a Python identifier or is a keyword, or is called ``id`` (the item
id the tools take). Such a kind raises ``KnowledgeBaseError`` naming kind and field.
"""

from __future__ import annotations

import inspect
import keyword
from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic import Field
from pydantic.fields import FieldInfo

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.models import MemoryItem, MemoryPage, WriteAccepted
from tools_knowledge_base.operations import (
    MAX_LIMIT,
    delete_memory_item,
    get_memory_item,
    list_memory_items,
    store_memory,
    update_memory_item,
)

type Tool = tuple[Callable[..., Any], ToolAnnotations | None]

_KEYWORD = inspect.Parameter.KEYWORD_ONLY
_ID = inspect.Parameter("id", _KEYWORD, annotation=UUID)


def named(
    fn: Callable[..., Any],
    name: str,
    doc: str,
    parameters: list[inspect.Parameter] | None = None,
    returns: object = None,
) -> Callable[..., Any]:
    """``fn`` renamed to the tool ``name``, with ``doc`` and any signature the schema reads."""
    fn.__name__ = name
    fn.__qualname__ = name
    fn.__doc__ = doc
    if parameters is not None:
        fn.__signature__ = inspect.Signature(parameters, return_annotation=returns)  # pyright: ignore[reportFunctionMemberAccess]
    return fn


def _not_plain(name: str, field: FieldInfo) -> str | None:
    """Why the payload field ``name`` cannot be a tool parameter, or None if it is plain."""
    aliases = (field.alias, field.validation_alias, field.serialization_alias)
    if any(alias is not None for alias in aliases):
        return "it has an alias, so its tool parameter, payload and output names differ"
    if field.exclude:
        return "it is excluded, so model_dump drops it from every stored payload"
    if not name.isidentifier() or keyword.iskeyword(name):
        return "its name is not a Python identifier, so it cannot be a tool parameter"
    if name == "id":
        return "it is called id, which the tools take as the item id"
    return None


def _payload_parameters(kind: MemoryKind) -> list[inspect.Parameter]:
    """One keyword-only parameter per payload field; its ``FieldInfo`` carries the rest.

    Raises:
        KnowledgeBaseError: a payload field is not plain (see the module docstring).
    """
    fields = kind.payload_model.model_fields
    for name, field in fields.items():
        if reason := _not_plain(name, field):
            msg = f"kind {kind.name!r} payload field {name!r} is not plain: {reason}"
            raise KnowledgeBaseError(msg)
    return [
        inspect.Parameter(name, _KEYWORD, annotation=Annotated[field.annotation, field])
        for name, field in fields.items()
    ]


def _item_id(arguments: dict[str, object]) -> UUID:
    """The ``id`` argument, taken out so the rest is the payload."""
    return UUID(str(arguments.pop("id")))


def _kind_tools(kb: KnowledgeBase, kind: MemoryKind) -> list[Tool]:
    """The five tools of one kind."""
    name = kind.name
    payload = _payload_parameters(kind)

    def store(**arguments: object) -> WriteAccepted:
        return store_memory(kb, name, arguments)

    def update(**arguments: object) -> WriteAccepted:
        item_id = _item_id(arguments)
        return update_memory_item(kb, name, item_id, arguments)

    def get(**arguments: object) -> MemoryItem:
        return get_memory_item(kb, name, _item_id(arguments))

    def list_(
        *, limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 50, cursor: UUID | None = None
    ) -> MemoryPage:
        return list_memory_items(kb, name, limit=limit, cursor=cursor)

    def delete(**arguments: object) -> WriteAccepted:
        return delete_memory_item(kb, name, _item_id(arguments))

    # ``__doc__``, not ``inspect.getdoc``: a payload without a docstring would inherit
    # pydantic's own ``BaseModel`` docstring. RST double backticks become Markdown's.
    holds = inspect.cleandoc(kind.payload_model.__doc__ or "").replace("``", "`")
    accepted = (
        f"Returns the request id to poll with get_memory_request, and the item id. {holds}"
    ).rstrip()
    cap = kb.settings.item_limits.for_kind(name)
    accepted += f" At most {cap} characters in total, counted over {kind.counted_over}."
    upserts = "storing one with the same identity updates it in place"
    return [
        (
            named(
                store,
                f"store_{name}",
                f"Store one {name} item; {upserts}. {accepted}",
                payload,
                WriteAccepted,
            ),
            None,
        ),
        (
            named(
                update,
                f"update_{name}",
                f"Replace the {name} item `id` with this payload. The returned item_id "
                "is the item's id from then on: it differs from `id` when the identity "
                f"fields change, and `id` is then gone. {accepted}",
                [_ID, *payload],
                WriteAccepted,
            ),
            None,
        ),
        (
            named(get, f"get_{name}", f"Get the {name} item `id`.", [_ID], MemoryItem),
            ToolAnnotations(read_only_hint=True),
        ),
        (
            named(
                list_,
                f"list_{name}",
                f"List {name} items, a page at a time: pass `next_cursor` back as `cursor`.",
            ),
            ToolAnnotations(read_only_hint=True),
        ),
        (
            named(
                delete,
                f"delete_{name}",
                f"Delete the {name} item `id` at once. Returns the request id removing its "
                "warm-up dump file: poll it with get_memory_request; until it is done the "
                "file can bring the item back.",
                [_ID],
                WriteAccepted,
            ),
            ToolAnnotations(destructive_hint=True, idempotent_hint=True),
        ),
    ]


def tools(kb: KnowledgeBase) -> list[Tool]:
    """Every installed kind's five tools, in kind-name order."""
    return [tool for kind in kb.kinds for tool in _kind_tools(kb, kind)]
