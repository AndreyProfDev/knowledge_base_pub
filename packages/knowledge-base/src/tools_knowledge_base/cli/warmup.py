"""``warmup``."""

from __future__ import annotations

import click

from tools_knowledge_base.cli.context import CliContext
from tools_knowledge_base.operations import warmup_memory


@click.command("warmup")
@click.pass_obj
def warmup_command(obj: CliContext) -> None:
    """Embed and write every item in the warm-up directory not already stored unchanged."""
    report = warmup_memory(obj.kb())
    for kind, counts in report.kinds.items():
        click.echo(f"{kind}: {counts.written} written, {counts.unchanged} unchanged")
    click.echo(f"total written: {report.total_written}")
    for shadow in report.shadowed:
        click.echo(f"shadowed: {shadow.hand_written} differs from {shadow.dump}, which was used")
