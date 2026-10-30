"""``knowledge-base-cli``: the group, built over the installed kinds."""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Callable, Sequence
from typing import cast, override

import click
from pydantic import ValidationError

from knowledge_base_config import Environment, environment_from_env
from tools_knowledge_base.cli.context import CliContext
from tools_knowledge_base.cli.memory import memory_commands
from tools_knowledge_base.cli.warmup import warmup_command, warmup_progress_command
from tools_knowledge_base.configs.settings import get_settings
from tools_knowledge_base.context import KnowledgeBase, open_knowledge_base
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.kinds.registry import KindRegistry, load_kinds


class _Cli(click.Group):
    """Exit 1 with the message when a command names what is not there, or is refused."""

    @override
    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except (KnowledgeBaseError, ValidationError) as error:
            raise click.ClickException(str(error)) from error


def build_cli(kinds: KindRegistry) -> click.Group:
    """The ``knowledge-base-cli`` group: its verbs and choices come from ``kinds``."""

    @click.group(cls=_Cli, context_settings={"help_option_names": ["-h", "--help"]})
    @click.option(
        "--env",
        type=click.Choice([e.value for e in Environment]),
        default=lambda: environment_from_env().value,
        show_default="TOOLS_ENV, else local",
        help="Which configuration overlay to load.",
    )
    @click.pass_context
    def knowledge_base_cli(ctx: click.Context, env: str) -> None:
        """Store, search and manage the knowledge base's memories."""
        ctx.obj = dataclasses.replace(cast("CliContext", ctx.obj), env=Environment(env))

    for command in [*memory_commands(kinds), warmup_command, warmup_progress_command]:
        knowledge_base_cli.add_command(command)
    return knowledge_base_cli


def main(
    args: Sequence[str] | None = None, *, load: Callable[[], KindRegistry] = load_kinds
) -> None:
    """Console-script entry point: the installed kinds, opened for the chosen overlay.

    A kind that fails to load is an error line and exit 1, not a traceback, even
    under ``--help``.
    """
    try:
        kinds = load()
    except KnowledgeBaseError as error:
        click.ClickException(str(error)).show()
        sys.exit(1)

    def open_kb(env: Environment) -> KnowledgeBase:
        return open_knowledge_base(get_settings(env), kinds=kinds)

    build_cli(kinds).main(args=args, obj=CliContext(open_kb=open_kb))
