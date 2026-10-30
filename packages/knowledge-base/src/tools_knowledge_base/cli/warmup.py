"""``warmup`` and ``warmup-progress RUN_ID``."""

from __future__ import annotations

import click

from tools_knowledge_base.cli.context import CliContext
from tools_knowledge_base.operations import get_warmup_progress, warmup_memory


@click.command("warmup")
@click.pass_obj
def warmup_command(obj: CliContext) -> None:
    """Queue every item in the warm-up directory not already stored unchanged."""
    report = warmup_memory(obj.kb())
    click.echo(f"run_id: {report.run_id}")
    for kind, counts in report.kinds.items():
        click.echo(f"{kind}: {counts.queued} queued, {counts.unchanged} unchanged")
    click.echo(f"total queued: {report.total_queued}")
    for shadow in report.shadowed:
        click.echo(f"shadowed: {shadow.hand_written} differs from {shadow.dump}, which was used")


@click.command("warmup-progress")
@click.argument("run_id")
@click.pass_obj
def warmup_progress_command(obj: CliContext, run_id: str) -> None:
    """Print how far the worker is through warm-up run RUN_ID."""
    progress = get_warmup_progress(obj.kb(), run_id)
    click.echo(
        f"{progress.done + progress.failed} of {progress.total} written: "
        f"{progress.done} done, {progress.failed} failed, {progress.pending} pending, "
        f"{progress.unchanged} unchanged"
    )
    for failure in progress.failures:
        click.echo(
            f"failed: {failure.kind}  {failure.item_id}  {failure.request_id}: {failure.error}"
        )
    if progress.failures_truncated:
        click.echo("and more failures")
    if progress.finished:
        click.echo("finished")
    else:
        click.echo("a failing write stays pending through its retries, about 150 s")
