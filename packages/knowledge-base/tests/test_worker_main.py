"""``knowledge-base-worker``: opens the configured knowledge base, or says why it cannot."""

from __future__ import annotations

from click.testing import CliRunner

from tools_knowledge_base.configs.settings import QueueSettings
from tools_knowledge_base.context import KnowledgeBase
from tools_knowledge_base.errors import KnowledgeBaseError
from tools_knowledge_base.worker import main


def test_main_once_opens_the_configured_knowledge_base_and_drains_it() -> None:
    result = CliRunner().invoke(main, ["--once"])

    assert result.exit_code == 0, result.output
    assert result.output == "ran 0 task(s), 0 failed\n"


def test_main_reports_a_knowledge_base_that_will_not_open_and_takes_h() -> None:
    def refuse() -> KnowledgeBase:
        msg = "collection holds 8-dimension vectors"
        raise KnowledgeBaseError(msg)

    result = CliRunner().invoke(main, ["--once"], obj=refuse)

    assert (result.exit_code, result.output) == (1, "Error: collection holds 8-dimension vectors\n")
    helped = CliRunner().invoke(main, ["-h"])
    assert helped.exit_code == 0
    assert "for the environment TOOLS_ENV names" in helped.output


def test_main_reports_settings_that_fail_validation() -> None:
    result = CliRunner().invoke(main, ["--once"], obj=lambda: QueueSettings.model_validate({}))

    assert result.exit_code == 1
    assert result.output.startswith("Error: 5 validation errors for QueueSettings\npath\n")
