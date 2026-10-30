"""``knowledge-base-worker``: runs queued writes, as a consumer or ``--once`` and exit."""

from __future__ import annotations

import logging
from collections.abc import Callable

import click
from huey import Huey  # pyright: ignore[reportMissingTypeStubs]
from pydantic import ValidationError

from knowledge_base_config import environment_from_env
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.queue import drain, run_consumer


def run_worker(
    kb: KnowledgeBase, *, once: bool, run: Callable[[Huey], None] = run_consumer
) -> None:
    """Drain the due tasks and say how many ran and failed, or ``run`` a consumer.

    The consumer stops gracefully on SIGINT. Under ``once``, a task interrupted by
    Ctrl-C goes back on the queue, the rest stay queued, and the interrupt propagates.

    Raises:
        click.exceptions.Exit: with code 1 when ``once`` and any task failed.
        KeyboardInterrupt: when ``once`` and a task was interrupted.
    """
    if once:
        drained = drain(kb.huey)
        click.echo(f"ran {drained.ran} task(s), {drained.failed} failed")
        if drained.failed:
            raise click.exceptions.Exit(1)
        return
    run(kb.huey)


def _open_configured() -> KnowledgeBase:
    return open_knowledge_base(get_settings(environment_from_env()))


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--once", is_flag=True, help="Run every due task, then exit.")
@click.pass_obj
def main(open_kb: Callable[[], KnowledgeBase] | None, *, once: bool) -> None:
    """Run the knowledge base's queued writes, for the environment TOOLS_ENV names."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        kb = (open_kb or _open_configured)()
    except (KnowledgeBaseError, ValidationError) as error:
        raise click.ClickException(str(error)) from error
    run_worker(kb, once=once)
