"""The verbs, built from the kind registry: ``--kind`` choices and one store/update pair each.

Items print through their kind's ``render``, the one place it is used.
"""

from __future__ import annotations

import json
from typing import Literal, get_args, get_origin
from uuid import UUID

import click
from pydantic import BaseModel

from tools_knowledge_base.cli.context import CliContext
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.kinds.protocol import MemoryKind
from tools_knowledge_base.kinds.registry import KindRegistry
from tools_knowledge_base.models import MemoryItem, WriteAccepted
from tools_knowledge_base.operations import (
    MAX_LIMIT,
    delete_memory_item,
    get_memory_item,
    get_memory_request,
    list_memory_items,
    list_memory_kinds,
    reembed_memory,
    search_memory,
    store_memory,
    update_memory_item,
)


def _line(kb: KnowledgeBase, item: MemoryItem) -> str:
    return f"{item.kind}  {item.id}  {kb.kinds.get(item.kind).render(item.payload)}"


def _echo_accepted(accepted: WriteAccepted) -> None:
    click.echo(f"request_id: {accepted.request_id}")
    click.echo(f"item_id: {accepted.item_id}")
    click.echo(f"status: {accepted.status}")


def _payload_options(model: type[BaseModel]) -> list[click.Parameter]:
    """One option per payload field: a ``Literal`` as choices, a ``list`` repeated."""
    options: list[click.Parameter] = []
    for name, field in model.model_fields.items():
        decls = [f"--{name.replace('_', '-')}", name]
        origin = get_origin(field.annotation)
        if origin is list:
            options.append(click.Option(decls, multiple=True, help=field.description))
            continue
        param_type = (
            click.Choice([str(arg) for arg in get_args(field.annotation)])
            if origin is Literal
            else click.STRING
        )
        options.append(
            click.Option(
                decls,
                type=param_type,
                required=field.is_required(),
                help=field.description,
            )
        )
    return options


def _payload(model: type[BaseModel], values: dict[str, object]) -> dict[str, object]:
    """The given options as a payload: repeated ones as lists, unset ones left to defaults.

    An unrepeated list option reads ``()``: ``[]`` for a required list field, left out
    for one with a default, so that default applies.
    """
    return {
        name: list(value) if isinstance(value, tuple) else value  # pyright: ignore[reportUnknownArgumentType]
        for name, value in values.items()
        if value is not None and (value != () or model.model_fields[name].is_required())
    }


def store_command(kind: MemoryKind) -> click.Command:
    """``store-<kind>``: queue a new item from one option per payload field."""

    @click.pass_obj
    def store(obj: CliContext, **values: object) -> None:
        _echo_accepted(store_memory(obj.kb(), kind.name, _payload(kind.payload_model, values)))

    return click.Command(
        f"store-{kind.name}",
        params=_payload_options(kind.payload_model),
        callback=store,
        help=f"Queue a new {kind.name} item; prints its request and item ids.",
    )


def update_command(kind: MemoryKind) -> click.Command:
    """``update-<kind> ID``: queue the item's replacement, the full payload as options."""

    @click.pass_obj
    def update(obj: CliContext, item_id: UUID, **values: object) -> None:
        payload = _payload(kind.payload_model, values)
        _echo_accepted(update_memory_item(obj.kb(), kind.name, item_id, payload))

    id_name = "item_id"  # pragma: no mutate, equivalent: click lowercases argument names
    item = click.Argument([id_name], type=click.UUID, metavar="ID")
    return click.Command(
        f"update-{kind.name}",
        params=[item, *_payload_options(kind.payload_model)],
        callback=update,
        help=f"Queue a replacement for {kind.name} item ID; prints the id its new key derives.",
    )


def search_command(kinds: KindRegistry) -> click.Command:
    """``search QUERY``: the nearest items, best first, with their scores."""

    @click.command("search")
    @click.argument("query")
    @click.option("--kind", type=click.Choice(kinds.names()), help="Only items of this kind.")
    @click.option(
        "--top-k",
        type=click.IntRange(1, MAX_LIMIT),
        help="How many hits; defaults to search.top_k.",
    )
    @click.option("--min-score", type=float, help="Score floor; defaults to the embedder's.")
    @click.pass_obj
    def search(
        obj: CliContext, query: str, kind: str | None, top_k: int | None, min_score: float | None
    ) -> None:
        """Search every kind, or one, for the items nearest QUERY."""
        kb = obj.kb()
        hits = search_memory(kb, query, kind=kind, top_k=top_k, min_score=min_score)
        for hit in hits:
            click.echo(f"{hit.score:.3f}  {_line(kb, hit)}")
        if not hits:
            click.echo("no matches")

    return search


def item_commands(kinds: KindRegistry) -> list[click.Command]:
    """``get``, ``list`` and ``delete``, their KIND one of the installed kinds."""
    kind_name = "kind"  # pragma: no mutate, equivalent: click lowercases argument names
    id_name = "item_id"  # pragma: no mutate, equivalent: click lowercases argument names
    kind_argument = click.argument(kind_name, type=click.Choice(kinds.names()))
    id_argument = click.argument(id_name, type=click.UUID, metavar="ID")

    @click.command("get")
    @kind_argument
    @id_argument
    @click.pass_obj
    def get(obj: CliContext, kind: str, item_id: UUID) -> None:
        """Print item ID of KIND."""
        kb = obj.kb()
        item = get_memory_item(kb, kind, item_id)
        click.echo(f"{_line(kb, item)}  (updated {item.updated_at.isoformat()})")

    @click.command("list")
    @kind_argument
    @click.option(
        "--limit",
        type=click.IntRange(1, MAX_LIMIT),
        default=50,
        show_default=True,
        help="Items per page.",
    )
    @click.option("--cursor", type=click.UUID, help="Start here: a previous page's next cursor.")
    @click.pass_obj
    def list_items(obj: CliContext, kind: str, limit: int, cursor: UUID | None) -> None:
        """Print one page of KIND's items."""
        kb = obj.kb()
        page = list_memory_items(kb, kind, limit=limit, cursor=cursor)
        for item in page.items:
            click.echo(_line(kb, item))
        if page.next_cursor is not None:
            click.echo(f"next cursor: {page.next_cursor}")

    @click.command("delete")
    @kind_argument
    @id_argument
    @click.pass_obj
    def delete(obj: CliContext, kind: str, item_id: UUID) -> None:
        """Delete item ID of KIND; its dump file goes by a queued request."""
        accepted = delete_memory_item(obj.kb(), kind, item_id)
        click.echo(f"deleted {kind} {item_id}")
        _echo_accepted(accepted)

    return [get, list_items, delete]


@click.command("request-status")
@click.argument("request_id")
@click.pass_obj
def request_status_command(obj: CliContext, request_id: str) -> None:
    """Print where queued request REQUEST_ID is: queued, done, or failed and why."""
    state = get_memory_request(obj.kb(), request_id)
    click.echo(state.status if state.error is None else f"{state.status}: {state.error}")


@click.command("kinds")
@click.pass_obj
def kinds_command(obj: CliContext) -> None:
    """Print each installed kind, its character cap and its payload's JSON Schema."""
    for kind in list_memory_kinds(obj.kb()):
        click.echo(
            f"{kind.name}: at most {kind.max_chars} characters; {json.dumps(kind.payload_schema)}"
        )


@click.command("reembed")
@click.option("--from", "source", required=True, help="The collection to copy from.")
@click.pass_obj
def reembed_command(obj: CliContext, source: str) -> None:
    """Fill the active embedder's collection from another one. Run with the worker stopped.

    Exits 1 when any item was too long to copy: the new collection is incomplete.
    """
    report = reembed_memory(obj.kb(), source)
    click.echo(
        f"copied {report.copied}, skipped {report.skipped_existing} already present, "
        f"{report.skipped_deleted} deleted since"
    )
    for item_id in report.too_long:
        click.echo(f"too long, left out: {item_id}")
    if report.too_long:
        msg = f"{len(report.too_long)} item(s) too long for the active embedder were not copied"
        raise click.ClickException(msg)


def memory_commands(kinds: KindRegistry) -> list[click.Command]:
    """Every verb: the generic ones, then each kind's ``store-*`` and ``update-*``."""
    generic = [
        search_command(kinds),
        *item_commands(kinds),
        request_status_command,
        kinds_command,
        reembed_command,
    ]
    return generic + [
        command(kind) for kind in kinds for command in (store_command, update_command)
    ]
