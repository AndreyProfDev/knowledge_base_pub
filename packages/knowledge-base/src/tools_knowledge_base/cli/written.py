"""What a write verb prints about its request."""

from __future__ import annotations

import click

from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.models import WriteAccepted
from tools_knowledge_base.operations import get_memory_request


def echo_accepted(accepted: WriteAccepted) -> None:
    """Print the request id, the item id and the status."""
    click.echo(f"request_id: {accepted.request_id}")
    click.echo(f"item_id: {accepted.item_id}")
    click.echo(f"status: {accepted.status}")


def echo_written(kb: KnowledgeBase, accepted: WriteAccepted) -> None:
    """Run the queued write here (the process ends with the command), then report it.

    Raises:
        click.ClickException: the write failed; the message is its error.
    """
    kb.writes.drain()
    state = get_memory_request(kb, accepted.request_id)
    if state.error is not None:
        raise click.ClickException(state.error)
    echo_accepted(accepted.model_copy(update={"status": state.status}))
